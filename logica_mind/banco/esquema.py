"""Esquema do Banco de dados: a camada ESTRUTURADA do Logica Mind.

O Mind sempre teve uma camada só, a Memória: guarda texto, recupera por semelhança,
deduplica a 0.92 e esquece por curva. Isso é certo para "o que significa" e é fatal
para "o que é" — lista de compras e marcação de hábito SÃO repetição, e a memória
apaga repetição por projeto.

O Banco de dados é o contrato que faltava, no mesmo produto e no mesmo banco:

    Memória                          Registro
    o que significa                  o que é
    semelhança pontuada              filtro exato, ordenação, junção
    deduplica a 0.92                 nunca deduplica
    esquece (curva)                  nunca esquece
    extrai fatos do texto            transação, unicidade

O modelo é o do Notion, e o ponto dele é que o usuário INVENTA as colunas. Por isso
`linha.props` é jsonb: DDL por propriedade seria insustentável e EAV seria pior. Mas
tudo que o SISTEMA filtra sempre (`user_id`, `no_id`, posição, datas, arquivamento)
é coluna de verdade, porque índice em coluna ganha de índice em expressão.

RECORTE POR TENANT É ESTRUTURAL, NÃO DISCIPLINA. A coluna física continua chamada
`user_id` por compatibilidade, mas guarda o owner estável da empresa. Pessoas ficam
somente na autoria/auditoria. A chave é denormalizada e amarrada por FK composta
`(pai_id, user_id) -> pai(id, user_id)`; assim o banco recusa uma linha órfã do tenant.
"""

# `posicao` é `numeric` (precisão arbitrária no Postgres) com inserção pelo ponto
# médio: arrastar um item para o topo de uma lista de 300 escreve UMA linha, não 300.
# Custo conhecido: reordenar muitas vezes no mesmo ponto faz a escala crescer. Um job
# de recompactação por nó (reatribuir 1000, 2000, 3000…) resolve, e roda fora do
# caminho quente.
DDL = """
SET search_path TO banco, public;

-- ── árvore ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS espaco (
    id          uuid PRIMARY KEY,
    user_id     text NOT NULL,
    nome        text NOT NULL,
    icone       text,
    ordem       numeric NOT NULL DEFAULT 1000,
    criado_em   timestamptz NOT NULL DEFAULT now(),
    arquivado_em timestamptz,
    UNIQUE (id, user_id)
);

-- Um NÓ é página (documento) ou banco (tabela). Uma hierarquia só: duas árvores
-- paralelas fariam a barra lateral mentir sobre onde a coisa está.
CREATE TABLE IF NOT EXISTS no (
    id           uuid PRIMARY KEY,
    espaco_id    uuid NOT NULL,
    user_id      text NOT NULL,
    pai_id       uuid,
    tipo         text NOT NULL CHECK (tipo IN ('pagina','banco')),
    nome         text NOT NULL,
    icone        text,
    capa         text,
    modelo       text,                    -- de qual template nasceu (informativo)
    chave_titulo text,                    -- qual propriedade é o título, para tipo='banco'
    posicao      numeric NOT NULL DEFAULT 1000,
    criado_em    timestamptz NOT NULL DEFAULT now(),
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    arquivado_em timestamptz,
    -- O id sozinho já é PRIMARY KEY, mas o recorte estrutural usa FKs compostas.
    -- O Postgres exige que a lista referenciada tenha uma UNIQUE exata; sem esta
    -- garantia até a FK autorreferente abaixo impede o Banco de dados de subir.
    CONSTRAINT ux_no_id_user_id UNIQUE (id, user_id),
    FOREIGN KEY (espaco_id, user_id) REFERENCES espaco(id, user_id) ON DELETE CASCADE,
    FOREIGN KEY (pai_id, user_id)    REFERENCES no(id, user_id)     ON DELETE CASCADE
);

-- Migração de appliance N-1: CREATE TABLE IF NOT EXISTS não acrescenta constraints
-- a uma tabela que já existe. O nome é o mesmo índice criado pela UNIQUE acima, de
-- modo que instalações novas não ganham índice duplicado; instalações antigas são
-- reparadas antes de qualquer tabela filha referenciar (id, user_id).
CREATE UNIQUE INDEX IF NOT EXISTS ux_no_id_user_id ON no (id, user_id);

-- Uma versão interrompida podia ter deixado `no` criada antes da FK autorreferente.
-- Reponha a proteção sem duplicá-la quando o Postgres já tiver uma FK equivalente,
-- independentemente do nome automático usado pela versão anterior.
DO $lm_no_parent_fk$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM pg_constraint
         WHERE conrelid = 'banco.no'::regclass
           AND confrelid = 'banco.no'::regclass
           AND contype = 'f'
           AND conkey = ARRAY[
               (SELECT attnum FROM pg_attribute
                 WHERE attrelid = 'banco.no'::regclass AND attname = 'pai_id'),
               (SELECT attnum FROM pg_attribute
                 WHERE attrelid = 'banco.no'::regclass AND attname = 'user_id')
           ]::smallint[]
           AND confkey = ARRAY[
               (SELECT attnum FROM pg_attribute
                 WHERE attrelid = 'banco.no'::regclass AND attname = 'id'),
               (SELECT attnum FROM pg_attribute
                 WHERE attrelid = 'banco.no'::regclass AND attname = 'user_id')
           ]::smallint[]
    ) THEN
        ALTER TABLE banco.no
            ADD CONSTRAINT fk_no_pai_user
            FOREIGN KEY (pai_id, user_id)
            REFERENCES banco.no(id, user_id) ON DELETE CASCADE;
    END IF;
END
$lm_no_parent_fk$;

-- ── esquema que o USUÁRIO inventa ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS propriedade (
    id       uuid PRIMARY KEY,
    no_id    uuid NOT NULL,
    user_id  text NOT NULL,
    -- `chave` é slug IMUTÁVEL. Renomear "Prioridade" para "Urgência" não pode
    -- reescrever 10.000 linhas: o nome é rótulo, a chave é endereço.
    chave    text NOT NULL CHECK (chave ~ '^[a-z][a-z0-9_]{0,39}$'),
    nome     text NOT NULL,
    tipo     text NOT NULL,
    config   jsonb NOT NULL DEFAULT '{}'::jsonb,
    ordem    numeric NOT NULL DEFAULT 1000,
    oculta   boolean NOT NULL DEFAULT false,
    UNIQUE (id, user_id),
    UNIQUE (no_id, chave),
    FOREIGN KEY (no_id, user_id) REFERENCES no(id, user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS vista (
    id      uuid PRIMARY KEY,
    no_id   uuid NOT NULL,
    user_id text NOT NULL,
    nome    text NOT NULL,
    tipo    text NOT NULL CHECK (tipo IN ('tabela','quadro','calendario','galeria','lista')),
    config  jsonb NOT NULL DEFAULT '{}'::jsonb,   -- filtro (árvore), ordenação, agrupamento, colunas
    ordem   numeric NOT NULL DEFAULT 1000,
    padrao  boolean NOT NULL DEFAULT false,
    UNIQUE (id, user_id),
    FOREIGN KEY (no_id, user_id) REFERENCES no(id, user_id) ON DELETE CASCADE
);

-- ── o dado ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS linha (
    id        uuid PRIMARY KEY,
    no_id     uuid NOT NULL,
    user_id   text NOT NULL,
    -- `titulo` é coluna REAL, promovida de props pela chave_titulo do nó. Toda vista
    -- lista o título e toda relação renderiza o do destino; deixá-lo só no jsonb
    -- forçaria um ->> por linha em cada listagem e impediria índice de texto direto.
    titulo    text NOT NULL DEFAULT '',
    props     jsonb NOT NULL DEFAULT '{}'::jsonb,
    posicao   numeric NOT NULL DEFAULT 1000,
    criado_em timestamptz NOT NULL DEFAULT now(),
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    arquivado_em timestamptz,
    deletado_em  timestamptz,          -- lixeira de 30 dias, não DELETE imediato
    UNIQUE (id, user_id),
    FOREIGN KEY (no_id, user_id) REFERENCES no(id, user_id) ON DELETE CASCADE
);

-- Relação é TABELA, não jsonb: precisa de integridade referencial (apagar o destino
-- limpa o elo), leitura nos dois sentidos (retrolink) e contagem. Em jsonb os três
-- viram código Python, e código Python erra os três.
CREATE TABLE IF NOT EXISTS elo (
    id             uuid PRIMARY KEY,
    user_id        text NOT NULL,
    propriedade_id uuid NOT NULL,
    origem_id      uuid NOT NULL,
    destino_id     uuid NOT NULL,
    criado_em      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (propriedade_id, origem_id, destino_id),
    FOREIGN KEY (propriedade_id, user_id) REFERENCES propriedade(id, user_id) ON DELETE CASCADE,
    FOREIGN KEY (origem_id, user_id)      REFERENCES linha(id, user_id)       ON DELETE CASCADE,
    FOREIGN KEY (destino_id, user_id)     REFERENCES linha(id, user_id)       ON DELETE CASCADE
);

-- Documento TipTap: um jsonb por página, não uma linha por bloco. Fatiar em blocos
-- para um usuário com documentos pequenos é N+1 de graça. A tabela `bloco` só se
-- justifica quando houver edição colaborativa por bloco.
-- `versao` existe porque duas abas abertas comeriam uma à outra em silêncio, e esse
-- é o defeito mais caro que um editor pode ter: a perda só aparece dias depois.
CREATE TABLE IF NOT EXISTS documento (
    id       uuid PRIMARY KEY,
    user_id  text NOT NULL,
    no_id    uuid,
    linha_id uuid,
    doc      jsonb NOT NULL DEFAULT '{"type":"doc","content":[]}'::jsonb,
    texto    text NOT NULL DEFAULT '',      -- extrato plano, para busca
    versao   integer NOT NULL DEFAULT 1,
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, user_id),
    CHECK ((no_id IS NULL) <> (linha_id IS NULL)),
    FOREIGN KEY (no_id, user_id)    REFERENCES no(id, user_id)    ON DELETE CASCADE,
    FOREIGN KEY (linha_id, user_id) REFERENCES linha(id, user_id) ON DELETE CASCADE
);

-- Snapshot por versão. O documento atual continua barato de ler; a história fica
-- separada, append-only, e permite diff/restauração sem transformar toda abertura
-- de página numa varredura de revisões.
CREATE TABLE IF NOT EXISTS revisao_documento (
    id           bigserial PRIMARY KEY,
    user_id      text NOT NULL,
    documento_id uuid NOT NULL,
    no_id        uuid,
    linha_id     uuid,
    versao       integer NOT NULL,
    doc          jsonb NOT NULL,
    texto        text NOT NULL DEFAULT '',
    autor_id     text NOT NULL,
    criado_em    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (documento_id, versao),
    CHECK ((no_id IS NULL) <> (linha_id IS NULL)),
    FOREIGN KEY (documento_id) REFERENCES documento(id) ON DELETE CASCADE
);

-- Comentário pode apontar para a página/registro inteiro ou para um blockId estável.
-- Thread é autorreferência; resolver a raiz resolve visualmente a conversa inteira.
CREATE TABLE IF NOT EXISTS comentario (
    id          uuid PRIMARY KEY,
    user_id     text NOT NULL,
    no_id       uuid,
    linha_id    uuid,
    block_id    text,
    pai_id      uuid,
    autor_id    text NOT NULL,
    corpo       text NOT NULL,
    criado_em   timestamptz NOT NULL DEFAULT now(),
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    resolvido_em timestamptz,
    CHECK ((no_id IS NULL) <> (linha_id IS NULL)),
    FOREIGN KEY (no_id, user_id)    REFERENCES no(id, user_id)    ON DELETE CASCADE,
    FOREIGN KEY (linha_id, user_id) REFERENCES linha(id, user_id) ON DELETE CASCADE,
    FOREIGN KEY (pai_id) REFERENCES comentario(id) ON DELETE CASCADE
);

-- Índice materializado das referências encontradas no JSON TipTap. O documento
-- continua sendo a fonte da verdade; esta tabela existe para backlink não precisar
-- varrer todo o workspace a cada abertura de página.
CREATE TABLE IF NOT EXISTS referencia_pagina (
    id            uuid PRIMARY KEY,
    user_id       text NOT NULL,
    origem_no_id  uuid NOT NULL,
    destino_no_id uuid NOT NULL,
    block_id      text,
    tipo          text NOT NULL CHECK (tipo IN ('mention','pagina')),
    criado_em     timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (origem_no_id, user_id)  REFERENCES no(id, user_id) ON DELETE CASCADE,
    FOREIGN KEY (destino_no_id, user_id) REFERENCES no(id, user_id) ON DELETE CASCADE
);

-- ── gamificação: esquema do PRODUTO, nunca jsonb ──────────────────────────────
-- XP em jsonb seria auto-sabotagem: é justamente o dado que precisa de soma,
-- transação e unicidade.
CREATE TABLE IF NOT EXISTS xp_evento (
    id         bigserial PRIMARY KEY,
    user_id    text NOT NULL,
    ocorrido_em timestamptz NOT NULL DEFAULT now(),
    dia_local  date NOT NULL,              -- data LOCAL do usuário, não UTC (ver sequencia)
    tipo       text NOT NULL,
    atributo   text NOT NULL CHECK (atributo IN ('VIGOR','FOCO','MENTE','CORPO','ORDEM')),
    xp         integer NOT NULL,
    no_id      uuid,
    linha_id   uuid,
    -- Sem esta chave, duplo clique dobra o XP, e gamificação sem integridade vira
    -- número que ninguém confia. Formato: <tipo>:<linha_id>:<dia_local>.
    chave_idem text NOT NULL UNIQUE,
    meta       jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS atributo_saldo (
    user_id  text NOT NULL,
    atributo text NOT NULL,
    xp       bigint NOT NULL DEFAULT 0,
    valor    real   NOT NULL DEFAULT 0,     -- 0 a 100, média móvel de 30 dias
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, atributo)
);

CREATE TABLE IF NOT EXISTS perfil (
    user_id   text PRIMARY KEY,
    xp_total  bigint NOT NULL DEFAULT 0,
    nivel     integer NOT NULL DEFAULT 1,
    rank      text NOT NULL DEFAULT 'INICIANDO',
    -- FUSO É OBRIGATÓRIO. Marcar hábito às 23h30 no Brasil é 02h30 UTC do dia
    -- seguinte: com data UTC a sequência quebra sozinha. É o defeito mais comum
    -- desta categoria de produto.
    tz        text NOT NULL DEFAULT 'America/Sao_Paulo',
    modo_progresso text NOT NULL DEFAULT 'mostrar'
                   CHECK (modo_progresso IN ('mostrar','discreto','desligado')),
    criado_em timestamptz NOT NULL DEFAULT now(),
    atualizado_em timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sequencia (
    user_id      text NOT NULL,
    chave        text NOT NULL,            -- 'global' ou 'habito:<linha_id>'
    atual        integer NOT NULL DEFAULT 0,
    recorde      integer NOT NULL DEFAULT 0,
    ultima_data  date,
    salvo_conduto integer NOT NULL DEFAULT 1,   -- 1 por mês, acumula até 2
    pausado_ate  date,
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, chave)
);

CREATE TABLE IF NOT EXISTS conquista (
    slug      text PRIMARY KEY,
    nome      text NOT NULL,
    descricao text NOT NULL,
    tier      text NOT NULL CHECK (tier IN ('bronze','prata','ouro','platina'))
);

CREATE TABLE IF NOT EXISTS conquista_do_usuario (
    id       bigserial PRIMARY KEY,
    user_id  text NOT NULL,
    slug     text NOT NULL REFERENCES conquista(slug) ON DELETE CASCADE,
    ganha_em timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, slug)
);

-- ── caixa de saída para a Memória ─────────────────────────────────────────────
-- O handler HTTP NÃO pode chamar mind.remember() dentro da requisição: o extrator
-- roda a CLI `claude` e leva SEGUNDOS segurando um dos 32 workers. Seria o colapso
-- documentado no _BoundedHTTPServer entrando pela porta da frente.
CREATE TABLE IF NOT EXISTS evento_pendente (
    id          bigserial PRIMARY KEY,
    user_id     text NOT NULL,
    tipo        text NOT NULL,
    payload     jsonb NOT NULL,
    criado_em   timestamptz NOT NULL DEFAULT now(),
    processado_em timestamptz,
    tentativas  integer NOT NULL DEFAULT 0,
    erro        text
);

-- ── Inbox da Life ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS notificacao (
    id            uuid PRIMARY KEY,
    user_id       text NOT NULL,
    chave         text NOT NULL,
    tipo          text NOT NULL,
    titulo        text NOT NULL,
    corpo         text NOT NULL DEFAULT '',
    no_id         uuid,
    linha_id      uuid,
    agente        text,
    disponivel_em timestamptz NOT NULL DEFAULT now(),
    lida_em       timestamptz,
    criado_em     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, chave)
);

-- ── índices ───────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS ix_no_espaco    ON no (espaco_id, pai_id, posicao) WHERE arquivado_em IS NULL;
CREATE INDEX IF NOT EXISTS ix_no_user      ON no (user_id, atualizado_em DESC);
CREATE INDEX IF NOT EXISTS ix_prop_no      ON propriedade (no_id, ordem);
CREATE INDEX IF NOT EXISTS ix_vista_no     ON vista (no_id, ordem);
CREATE INDEX IF NOT EXISTS ix_linha_lista  ON linha (no_id, posicao) WHERE deletado_em IS NULL;
CREATE INDEX IF NOT EXISTS ix_linha_user   ON linha (user_id, atualizado_em DESC);
CREATE INDEX IF NOT EXISTS ix_linha_lixo   ON linha (user_id, deletado_em) WHERE deletado_em IS NOT NULL;
-- jsonb_path_ops: ~2-3x menor e mais rápido que jsonb_ops, e serve `@>`, que é o
-- operador do filtro por igualdade. NÃO serve faixa nem ordenação: para isso existe
-- o índice de expressão sob demanda (ver nucleo.garantir_indice).
CREATE INDEX IF NOT EXISTS ix_linha_props  ON linha USING gin (props jsonb_path_ops);
CREATE INDEX IF NOT EXISTS ix_linha_titulo ON linha USING gin (to_tsvector('simple', lm_unaccent_imm(titulo)));
CREATE INDEX IF NOT EXISTS ix_doc_texto    ON documento USING gin (to_tsvector('simple', lm_unaccent_imm(texto)));
CREATE UNIQUE INDEX IF NOT EXISTS ix_doc_no    ON documento (no_id)    WHERE no_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ix_doc_linha ON documento (linha_id) WHERE linha_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_revisao_doc ON revisao_documento (documento_id, versao DESC);
CREATE INDEX IF NOT EXISTS ix_comentario_no ON comentario (no_id, criado_em) WHERE no_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_comentario_linha ON comentario (linha_id, criado_em) WHERE linha_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_comentario_bloco ON comentario (user_id, block_id) WHERE block_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_referencia_destino ON referencia_pagina (user_id, destino_no_id, criado_em);
CREATE INDEX IF NOT EXISTS ix_referencia_origem ON referencia_pagina (user_id, origem_no_id);
CREATE INDEX IF NOT EXISTS ix_elo_origem  ON elo (origem_id, propriedade_id);
CREATE INDEX IF NOT EXISTS ix_elo_destino ON elo (destino_id, propriedade_id);
CREATE INDEX IF NOT EXISTS ix_xp_user     ON xp_evento (user_id, ocorrido_em DESC);
CREATE INDEX IF NOT EXISTS ix_xp_atributo ON xp_evento (user_id, atributo, ocorrido_em DESC);
CREATE INDEX IF NOT EXISTS ix_xp_dia      ON xp_evento (user_id, dia_local);
CREATE INDEX IF NOT EXISTS ix_pendente    ON evento_pendente (processado_em, id) WHERE processado_em IS NULL;
CREATE INDEX IF NOT EXISTS ix_notificacao_inbox ON notificacao (user_id, lida_em, disponivel_em DESC);
"""

# Tipos de propriedade que o Banco de dados aceita. A validação vive no servidor porque o
# navegador não é fonte de verdade sobre esquema.
TIPOS = (
    "texto", "texto_longo", "numero", "moeda", "selecao", "multi_selecao",
    "data", "checkbox", "url", "email", "telefone", "arquivo", "pessoa",
    "relacao", "rollup", "rollup_janela", "formula",
    "criado_em", "atualizado_em",
)

ATRIBUTOS = ("VIGOR", "FOCO", "MENTE", "CORPO", "ORDEM")


def aplicar(cur) -> None:
    """Cria o esquema de forma idempotente. Chamado no boot, como o _SCHEMA do
    PostgresStore: appliance que sobe sem tabela é appliance que morre calado.

    O `CREATE SCHEMA` fica fora do DDL de propósito. O papel do Banco de dados é DONO do
    schema `banco` mas NÃO tem CREATE no banco nem no `public`: assim ele cria as
    tabelas dele e não consegue criar nada ao lado da memória. Um `CREATE SCHEMA IF
    NOT EXISTS` exigiria esse privilégio mesmo quando o schema já existe."""
    cur.execute("SELECT 1 FROM pg_namespace WHERE nspname = 'banco'")
    if not cur.fetchone():
        cur.execute("CREATE SCHEMA banco")
    cur.execute(DDL)
