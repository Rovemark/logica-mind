"""Superfície HTTP do Banco de dados, dentro do processo do Logica Mind.

O Arquiteto escolheu MESMO PROCESSO com o risco na mesa. Este arquivo é onde esse
risco é contido, e a contenção não é opinião: a docstring de `_BoundedHTTPServer`
registra o colapso medido em produção, **3.803 threads, 2,9 GB, `/api/recall`
devolvendo HTTP 000 enquanto `/api/health` seguia 200 em 0,5 ms e escondia tudo**. E a
linha de base medida antes deste trabalho mostrou que o recall já roda com
concorrência efetiva de 1: sozinho 0,96 s, com oito simultâneos p50 de 7,9 s.

As defesas, em ordem de força:

1. PRAZO NO BANCO, não aqui. `ALTER ROLE lm_bd SET statement_timeout='3s'`. Se o
   código esquecer, o banco não esquece. É a única que não depende de disciplina.
2. POOL PRÓPRIO, teto 4. O Banco de dados não encosta na conexão da memória.
3. SEMÁFORO DE ADMISSÃO, teto 8 dos 32 workers. Garantia dura: sobram ao menos 24
   para o recall, faça o Banco de dados o que fizer. Cheio, devolve 503 na hora em vez de
   enfileirar.
4. CHAVE DE DESLIGAMENTO QUENTE. `LM_BANCO=0` exige reinício, e reiniciar o Mind
   custa a memória do organismo (30 a 60 s recarregando o embedder) — ninguém puxaria
   essa alavanca na hora certa. Por isso existe também o arquivo `banco.flag`:
   `echo 0 > banco.flag` desliga na hora, sem reinício.
5. PAGINAÇÃO OBRIGATÓRIA e teto de linhas. Nada de resposta sem fim.
6. `/api/banco/saude` com números do pool. O `/api/health` raso NÃO muda: ele é a
   sonda de vida do PM2 e o comentário em `server.py:1558` explica que torná-lo
   profundo foi o que fez o LogicaOS cair no vault.

E duas questões de identidade que precisam ser ditas em voz alta:

- `LOGICA_MIND_PUBLIC=1` abre TODO GET `/api/*`. Sem tratamento, o modo demo público
  passaria a expor finanças pessoais e diário. Aqui o Banco de dados **ignora** esse modo e
  exige Bearer explícito para ler.
- O Mind tem UM token global e confia em loopback. Isso basta para memória de agente e
  NÃO basta para vida pessoal. `LM_BANCO_USERS` mapeia token para usuário; sem ele,
  tudo é do `dono`. **O `user_id` nunca vem do corpo do pedido**, vem da identidade
  autenticada. Enquanto o mapa não estiver configurado, o recorte por usuário é
  organização, não segurança, e isso está dito aqui em vez de fingido.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import threading
import time
from typing import Optional
from urllib.parse import parse_qs, urlparse

from . import calculados as C, dependencias as D, esquema, modelos as M, notificacoes as NF, nucleo as N, ponte as P, recorrencia as R, xp as X
from .calculados import ErroDeCalculo
from .consulta import montar, montar_contagem_por_grupo, ErroDeConsulta
from .nucleo import ErroDeBanco
from .xp import ErroDeProgresso

PREFIXO = "/api/banco/"

# Lista FECHADA de tabelas que o navegador pode abrir. O nome vai direto no SQL
# (identificador não aceita parâmetro), então ele nunca pode vir do pedido sem passar
# por aqui.
_TABELAS = ("espaco", "no", "propriedade", "vista", "linha", "elo", "documento",
            "revisao_documento", "comentario", "referencia_pagina",
            "xp_evento", "atributo_saldo", "perfil", "sequencia", "conquista",
            "conquista_do_usuario", "evento_pendente", "notificacao")
# As que têm dono: a leitura é sempre recortada por ele. `conquista` é catálogo do
# produto e não tem dono.
_COM_DONO = tuple(x for x in _TABELAS if x != "conquista")

# O schema `sistema` guarda a operação do LogicaOS (ex-Supabase): agentes, tarefas,
# rotinas, canais, memória de trabalho. A tela lê de lá também, mas SÓ LEITURA: o
# papel tem GRANT apenas de SELECT e uma política própria FOR SELECT. Separei as duas
# camadas de propósito, e um defeito na tela não pode alterar dado operacional.
_SCHEMA_SISTEMA = os.environ.get("LM_PG_SCHEMA_OS", "sistema")

# O DONO enxerga tudo. O recorte por user_id é do PRODUTO (a vida de cada pessoa);
# esta tela é um navegador de banco, e navegador que esconde metade do banco do
# próprio dono não serve para conferir migração nem para achar defeito.
def _owner_empresa() -> str:
    """Owner estável do tenant; pessoas são apenas autoria/auditoria."""
    owner = str(os.environ.get("LOGICAOS_OWNER_ID") or "").strip()
    return owner if owner else "dono"


def _eh_dono(user_id):
    # `dono` permanece só como compatibilidade de base pré-migração.
    return user_id in ("dono", _owner_empresa())


def _jsonavel(v):
    """datetime, uuid, Decimal e memoryview não sobrevivem ao json.dumps."""
    import datetime as _dt, decimal as _dec, uuid as _uuid
    if v is None or isinstance(v, (str, int, float, bool, list, dict)):
        return v
    if isinstance(v, (_dt.datetime, _dt.date)):
        return v.isoformat()
    if isinstance(v, _dec.Decimal):
        return float(v)
    if isinstance(v, memoryview):
        return f"<{len(v)} bytes>"
    return str(v)

_LIGADO_ENV = os.environ.get("LM_BANCO", "1").lower() not in ("0", "false", "no", "off")
_SLOTS = int(os.environ.get("LM_BANCO_SLOTS", "8") or 8)
_SEM = threading.BoundedSemaphore(_SLOTS)
_TETO_CORPO = 8 * 1024 * 1024      # 8 MB; documento maior que isto é anexo, não texto

_pool = None
_pool_lock = threading.Lock()

# ── chave de desligamento quente ──────────────────────────────────────────────
_flag_cache = {"valor": None, "em": 0.0}


def _caminho_flag() -> str:
    return os.environ.get("LM_BANCO_FLAG") or os.path.join(
        os.path.dirname(os.environ.get("LM_DB", "") or "."), "banco.flag")


def ligado() -> bool:
    """Lê o arquivo de desligamento no máximo a cada 5 s. `echo 0 > banco.flag`
    desliga sem reiniciar o Mind."""
    if not _LIGADO_ENV:
        return False
    agora = time.monotonic()
    if agora - _flag_cache["em"] < 5.0 and _flag_cache["valor"] is not None:
        return _flag_cache["valor"]
    valor = True
    try:
        with open(_caminho_flag(), "r") as f:
            valor = f.read().strip() not in ("0", "off", "false")
    except FileNotFoundError:
        valor = True
    except Exception:
        valor = True
    _flag_cache["valor"] = valor
    _flag_cache["em"] = agora
    return valor


def somente_leitura() -> bool:
    return os.environ.get("LM_BANCO", "1").lower() == "ro"


# ── pool ──────────────────────────────────────────────────────────────────────
def pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                from psycopg_pool import ConnectionPool
                dsn = os.environ.get("LM_PG_DSN_BD") or os.environ.get("POSTGRES_DSN", "")
                if not dsn:
                    raise RuntimeError("LM_PG_DSN_BD não configurado")
                _pool = ConnectionPool(
                    dsn, min_size=1,
                    max_size=int(os.environ.get("LM_PG_POOL_BD", "4")),
                    timeout=2.0, kwargs={"autocommit": True}, open=True)
                with _pool.connection() as con, con.cursor() as cur:
                    cur.execute("SET search_path TO banco, public")
                    esquema.aplicar(cur)
                    X.semear_conquistas(cur)
    return _pool


# ── identidade ────────────────────────────────────────────────────────────────
def _mapa_usuarios() -> dict:
    bruto = os.environ.get("LM_BANCO_USERS", "")
    if not bruto:
        return {}
    try:
        return json.loads(bruto)
    except Exception:
        return {}


def _usuario_delegado(tok: str, token_global: str, agora: Optional[float] = None) -> Optional[str]:
    """Valida a credencial efêmera emitida pela Life para uma sessão autenticada.

    O segredo global nunca chega ao navegador. Ele apenas assina owner + janela de
    um minuto dentro do processo da Life; o Banco materializa esse owner antes de
    qualquer query e continua ignorando `user_id` vindo do corpo.
    """
    if not token_global or not tok.startswith("life-v1."):
        return None
    partes = tok.split(".")
    if len(partes) != 4:
        return None
    _, encoded, bucket_texto, assinatura = partes
    if not encoded or not re.fullmatch(r"[A-Za-z0-9_-]+", encoded or ""):
        return None
    try:
        bucket = int(bucket_texto)
    except (TypeError, ValueError):
        return None
    bucket_atual = int((time.time() if agora is None else agora) // 60)
    if abs(bucket_atual - bucket) > 1:
        return None
    mensagem = f"life-banco-v1:{encoded}:{bucket}".encode("utf-8")
    esperada = base64.urlsafe_b64encode(
        hmac.new(token_global.encode("utf-8"), mensagem, hashlib.sha256).digest()
    ).rstrip(b"=").decode("ascii")
    if not hmac.compare_digest(assinatura, esperada):
        return None
    try:
        padding = "=" * ((4 - len(encoded) % 4) % 4)
        owner = base64.urlsafe_b64decode(encoded + padding).decode("utf-8").strip()
    except (ValueError, UnicodeDecodeError):
        return None
    if not owner or len(owner) > 300 or any(ord(ch) < 32 or ord(ch) == 127 for ch in owner):
        return None
    return owner


def usuario_de(cabecalho_auth: str, token_global: str) -> Optional[str]:
    """Token para usuário. A Life delega owner; o global preserva appliance legado."""
    if not cabecalho_auth.startswith("Bearer "):
        return None
    tok = cabecalho_auth[7:]
    mapa = _mapa_usuarios()
    if tok in mapa:
        return str(mapa[tok])
    delegado = _usuario_delegado(tok, token_global)
    if delegado:
        return delegado
    if token_global and tok == token_global:
        return _owner_empresa()
    return None


# ── despacho ──────────────────────────────────────────────────────────────────
class Resposta:
    __slots__ = ("codigo", "corpo")

    def __init__(self, codigo: int, corpo: dict):
        self.codigo = codigo
        self.corpo = corpo


def _erro(codigo, mensagem, extra=None):
    c = {"ok": False, "erro": {"codigo": codigo, "msg": mensagem}}
    if extra:
        c["erro"].update(extra)
    return Resposta(codigo, c)


def _ok(dados=None, **kw):
    c = {"ok": True}
    if dados is not None:
        c["dados"] = dados
    c.update(kw)
    return Resposta(200, c)


def trata(metodo: str, caminho: str, qs: dict, corpo: dict, user_id: str) -> Resposta:
    """Roteia uma chamada já autenticada e já admitida pelo semáforo."""
    acao = caminho[len(PREFIXO):]
    escrita = metodo == "POST"
    if escrita and somente_leitura():
        return _erro(503, "Registro em modo somente leitura")

    def um(nome, padrao=None):
        v = qs.get(nome)
        return (v[0] if isinstance(v, list) and v else v) or padrao

    with pool().connection() as con, con.cursor() as cur:
        cur.execute("SET search_path TO banco, public")

        # ---- leitura ----
        if acao == "saude":
            s = pool().get_stats()
            t0 = time.perf_counter()
            cur.execute("SELECT 1")
            cur.execute("SELECT count(*) FILTER (WHERE processado_em IS NULL AND tentativas < 5), "
                        "count(*) FILTER (WHERE processado_em IS NULL AND tentativas >= 5) "
                        "FROM banco.evento_pendente WHERE user_id=%s", (user_id,))
            ponte_pendentes, ponte_falhos = cur.fetchone()
            return _ok({
                "ligado": True,
                "pool": {"em_uso": s.get("pool_size", 0) - s.get("pool_available", 0),
                         "disponivel": s.get("pool_available", 0),
                         "max": pool().max_size,
                         "esperando": s.get("requests_waiting", 0)},
                "slots_livres": _SEM._value,
                "slots_max": _SLOTS,
                "memoria_life": {"ligada": P.ligada(), "namespace": P.NAMESPACE,
                                  "pendentes": int(ponte_pendentes),
                                  "falhos": int(ponte_falhos)},
                "latencia_ms": round((time.perf_counter() - t0) * 1000, 2),
            })

        if acao == "arvore":
            cur.execute(
                "SELECT id,espaco_id,pai_id,tipo,nome,icone,posicao,modelo FROM banco.no "
                "WHERE user_id=%s AND arquivado_em IS NULL ORDER BY posicao, nome", (user_id,))
            nos = [{"id": str(i), "espaco_id": str(e), "pai_id": str(p) if p else None,
                    "tipo": t, "nome": n, "icone": ic, "posicao": float(po), "modelo": m}
                   for i, e, p, t, n, ic, po, m in cur.fetchall()]
            cur.execute("SELECT id,nome,icone,ordem FROM banco.espaco "
                        "WHERE user_id=%s AND arquivado_em IS NULL ORDER BY ordem", (user_id,))
            espacos = [{"id": str(i), "nome": n, "icone": ic, "ordem": float(o)}
                       for i, n, ic, o in cur.fetchall()]
            return _ok({"espacos": espacos, "nos": nos})

        if acao == "no":
            no_id = um("id")
            if not no_id:
                return _erro(400, "id obrigatório")
            cur.execute("SELECT id,espaco_id,pai_id,tipo,nome,icone,capa,modelo,chave_titulo "
                        "FROM banco.no WHERE id=%s AND user_id=%s", (no_id, user_id))
            r = cur.fetchone()
            if not r:
                return _erro(404, "nó não encontrado")
            dados = {"id": str(r[0]), "espaco_id": str(r[1]), "pai_id": str(r[2]) if r[2] else None,
                     "tipo": r[3], "nome": r[4], "icone": r[5], "capa": r[6],
                     "modelo": r[7], "chave_titulo": r[8]}
            if r[3] == "banco":
                dados["propriedades"] = N.propriedades(cur, user_id, no_id)
                dados["vistas"] = N.vistas(cur, user_id, no_id)
            return _ok(dados)

        if acao == "linhas":
            no_id = um("no")
            if not no_id:
                return _erro(400, "no obrigatório")
            props = N.propriedades(cur, user_id, no_id)
            tipos = N.tipos_de(props)
            try:
                filtro = json.loads(um("filtro", "null") or "null")
                ordenacao = json.loads(um("ordenacao", "null") or "null")
            except json.JSONDecodeError:
                return _erro(400, "filtro/ordenacao não são JSON válido")
            limite = int(um("limite", 50) or 50)
            try:
                sql, params = montar(no_id, user_id, tipos, filtro=filtro,
                                     ordenacao=ordenacao, limite=limite,
                                     cursor=um("cursor"))
            except ErroDeConsulta as e:
                return _erro(400, str(e))
            cur.execute(sql, params)
            linhas = cur.fetchall()
            tem_mais = len(linhas) > limite
            linhas = linhas[:limite]
            saida = [{"id": str(l[0]), "no_id": str(l[1]), "titulo": l[2], "props": l[3],
                      "posicao": float(l[4]), "criado_em": l[5].isoformat(),
                      "atualizado_em": l[6].isoformat(),
                      "arquivado_em": l[7].isoformat() if l[7] else None} for l in linhas]
            # Hierarquia e dependências precisam dos elos de TODAS as linhas, mas um
            # N+1 aqui deixaria a lista lenta. Um único SELECT anexa os dois sentidos.
            if saida:
                ids = [item["id"] for item in saida]
                por_id = {item["id"]: {"saindo": [], "entrando": []} for item in saida}
                cur.execute("SELECT e.propriedade_id,e.origem_id,e.destino_id,lo.titulo,ld.titulo,"
                            "p.config->>'semantica',ld.props "
                            "FROM banco.elo e JOIN banco.linha lo ON lo.id=e.origem_id "
                            "JOIN banco.linha ld ON ld.id=e.destino_id "
                            "JOIN banco.propriedade p ON p.id=e.propriedade_id AND p.user_id=e.user_id "
                            "WHERE e.user_id=%s "
                            "AND (e.origem_id=ANY(%s::uuid[]) OR e.destino_id=ANY(%s::uuid[]))",
                            (user_id, ids, ids))
                for prop_id, origem_id, destino_id, titulo_origem, titulo_destino, semantica, props_destino in cur.fetchall():
                    origem, destino = str(origem_id), str(destino_id)
                    if origem in por_id:
                        elo = {"propriedade_id": str(prop_id), "id": destino,
                               "titulo": titulo_destino, "sentido": "saindo"}
                        if semantica:
                            elo["semantica"] = semantica
                        if semantica == "dependencia":
                            elo["pendente"] = not D.esta_concluido(props_destino or {})
                        por_id[origem]["saindo"].append(elo)
                    if destino in por_id:
                        por_id[destino]["entrando"].append({"propriedade_id": str(prop_id), "id": origem,
                                                             "titulo": titulo_origem, "sentido": "entrando"})
                for item in saida:
                    item["elos"] = por_id[item["id"]]
            prox = f"{linhas[-1][4]}|{linhas[-1][0]}" if (tem_mais and linhas) else None
            resp = {"linhas": saida, "cursor": prox, "tem_mais": tem_mais}
            agrupar = um("agrupar")
            if agrupar:
                try:
                    sql, params = montar_contagem_por_grupo(no_id, user_id, tipos, agrupar, filtro)
                    cur.execute(sql, params)
                    resp["contagem_por_grupo"] = {str(g): n for g, n in cur.fetchall()}
                except ErroDeConsulta as e:
                    return _erro(400, str(e))
            return _ok(resp)

        if acao == "linha":
            linha_id = um("id")
            cur.execute("SELECT id,no_id,titulo,props,posicao FROM banco.linha "
                        "WHERE id=%s AND user_id=%s AND deletado_em IS NULL", (linha_id, user_id))
            r = cur.fetchone()
            if not r:
                return _erro(404, "linha não encontrada")
            return _ok({"id": str(r[0]), "no_id": str(r[1]), "titulo": r[2], "props": r[3],
                        "posicao": float(r[4]), "elos": N.ligados(cur, user_id, linha_id)})

        if acao == "busca":
            termo = (um("q") or "").strip()
            if len(termo) < 2:
                return _ok([])
            padrao = f"%{termo[:200]}%"
            limite = max(1, min(int(um("limite", 50) or 50), 100))
            # Um único round-trip procura título, propriedades, documento e
            # comentários. Todas as pernas repetem user_id deliberadamente: busca
            # global que vaza uma linha torna inútil todo o recorte do produto.
            cur.execute("""
                SELECT tipo,no_id,linha_id,titulo,contexto,base FROM (
                  SELECT 'pagina'::text tipo,n.id no_id,NULL::uuid linha_id,n.nome titulo,
                         left(COALESCE(d.texto,''),240) contexto,''::text base,
                         CASE WHEN lower(n.nome)=lower(%s) THEN 0 ELSE 2 END relevancia,
                         n.atualizado_em momento
                    FROM banco.no n
                    LEFT JOIN banco.documento d ON d.no_id=n.id AND d.user_id=n.user_id
                   WHERE n.user_id=%s AND n.tipo='pagina' AND n.arquivado_em IS NULL
                     AND (n.nome ILIKE %s OR d.texto ILIKE %s)
                  UNION ALL
                  SELECT 'linha'::text tipo,l.no_id,l.id linha_id,l.titulo,
                         left(COALESCE(NULLIF(d.texto,''),l.props::text,''),240) contexto,n.nome base,
                         CASE WHEN lower(l.titulo)=lower(%s) THEN 0 ELSE 1 END relevancia,
                         l.atualizado_em momento
                    FROM banco.linha l
                    JOIN banco.no n ON n.id=l.no_id AND n.user_id=l.user_id
                    LEFT JOIN banco.documento d ON d.linha_id=l.id AND d.user_id=l.user_id
                   WHERE l.user_id=%s AND l.deletado_em IS NULL AND l.arquivado_em IS NULL
                     AND (l.titulo ILIKE %s OR l.props::text ILIKE %s OR d.texto ILIKE %s
                          OR EXISTS (SELECT 1 FROM banco.comentario c WHERE c.user_id=l.user_id
                                     AND c.linha_id=l.id AND c.corpo ILIKE %s))
                ) encontrados ORDER BY relevancia,momento DESC LIMIT %s
            """, (termo, user_id, padrao, padrao,
                  termo, user_id, padrao, padrao, padrao, padrao, limite))
            return _ok([{"tipo": tp, "no_id": str(no),
                         "linha_id": str(li) if li else None, "titulo": titulo,
                         "contexto": contexto or "", "base": base or ""}
                        for tp, no, li, titulo, contexto, base in cur.fetchall()])

        if acao == "documento":
            no_id, linha_id = um("no"), um("linha")
            if not (no_id or linha_id):
                return _erro(400, "no ou linha obrigatório")
            return _ok(N.ler_documento(cur, user_id, no_id=no_id, linha_id=linha_id))

        if acao == "documento.revisoes":
            no_id, linha_id = um("no"), um("linha")
            if not (no_id or linha_id):
                return _erro(400, "no ou linha obrigatório")
            return _ok(N.listar_revisoes(cur, user_id, no_id=no_id, linha_id=linha_id))

        if acao == "backlinks":
            no_id = um("no")
            if not no_id:
                return _erro(400, "no obrigatório")
            return _ok(N.listar_backlinks(cur, user_id, no_id))

        if acao == "comentarios":
            no_id, linha_id = um("no"), um("linha")
            if not (no_id or linha_id):
                return _erro(400, "no ou linha obrigatório")
            return _ok(N.listar_comentarios(cur, user_id, no_id=no_id, linha_id=linha_id,
                                             incluir_resolvidos=um("resolvidos") == "1"))

        if acao == "notificacoes":
            return _ok(NF.listar(cur, user_id,
                incluir_lidas=um("lidas") == "1", incluir_futuras=um("futuras") == "1",
                limite=int(um("limite", 100) or 100)))

        if acao == "progresso":
            return _ok(X.painel(cur, user_id))

        if acao == "arranjos":
            # A primeira abertura pergunta QUE VIDA é esta: pessoal, empresa ou as duas.
            # Instalar tudo para todo mundo é produto que ninguém usa.
            return _ok(M.arranjos())

        if acao == "modelos":
            return _ok(M.catalogo())

        # ── inspeção: o painel do Mind precisa OLHAR o banco, não só falar com ele ──
        # Construir a camada inteira sem tela foi o buraco que o Arquiteto apontou:
        # dá pra conversar por HTTP e não dá pra ver. E ver é como se descobre que a
        # migração trouxe tudo, ou que uma vista aponta pro lugar errado.
        if acao == "tabelas":
            esquema_pedido = um("esquema", "banco")
            if esquema_pedido == _SCHEMA_SISTEMA:
                cur.execute("""SELECT c.relname, pg_size_pretty(pg_total_relation_size(c.oid))
                               FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                               WHERE n.nspname=%s AND c.relkind='r' ORDER BY 1""", (_SCHEMA_SISTEMA,))
                tam = dict(cur.fetchall())
                cur.execute("""SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod), NOT a.attnotnull
                               FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
                               JOIN pg_namespace n ON n.oid=c.relnamespace
                               WHERE n.nspname=%s AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped
                               ORDER BY c.relname, a.attnum""", (_SCHEMA_SISTEMA,))
                colsis: dict = {}
                for rel, nome, tipo, nulo in cur.fetchall():
                    colsis.setdefault(rel, []).append({"nome": nome, "tipo": tipo, "nulo": nulo})
                if tam:
                    partes = " UNION ALL ".join(
                        f"SELECT '{tb}' t, count(*) n FROM {_SCHEMA_SISTEMA}.\"{tb}\"" for tb in tam)
                    cur.execute(partes)
                    cnt = dict(cur.fetchall())
                else:
                    cnt = {}
                return _ok([{"nome": tb, "total": cnt.get(tb, 0), "minhas": None,
                             "escopada": False, "esquema": _SCHEMA_SISTEMA,
                             "tamanho": tam[tb], "colunas": colsis.get(tb, [])}
                            for tb in sorted(tam)])

            # TRÊS consultas, não 56. A primeira versão fazia dois count(*), um
            # pg_total_relation_size e um information_schema.columns POR TABELA:
            # medido em 3 a 5 segundos, contra um statement_timeout de 3s. Ou seja,
            # a tela ficava em "Carregando…" e às vezes o próprio banco matava a
            # consulta. O information_schema é uma view sobre o catálogo com junção e
            # checagem de permissão em cada linha; catorze delas custam caro.
            dono = _eh_dono(user_id)
            partes = " UNION ALL ".join(
                f"SELECT '{tb}' t, count(*) n, count(*) FILTER (WHERE user_id=%s) m FROM banco.{tb}"
                if (tb in _COM_DONO and not dono) else
                f"SELECT '{tb}' t, count(*) n, count(*) m FROM banco.{tb}"
                for tb in _TABELAS)
            cur.execute(partes, [] if dono else [user_id] * len(_COM_DONO))
            contagens = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

            cur.execute("""SELECT c.relname, pg_size_pretty(pg_total_relation_size(c.oid))
                           FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                           WHERE n.nspname='banco' AND c.relkind='r'""")
            tamanhos = dict(cur.fetchall())

            # pg_attribute direto: mesma informação do information_schema, sem as
            # junções e a checagem de permissão por linha que o tornam lento.
            cur.execute("""SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod),
                                  NOT a.attnotnull
                           FROM pg_attribute a
                           JOIN pg_class c ON c.oid = a.attrelid
                           JOIN pg_namespace n ON n.oid = c.relnamespace
                           WHERE n.nspname='banco' AND c.relkind='r'
                             AND a.attnum > 0 AND NOT a.attisdropped
                           ORDER BY c.relname, a.attnum""")
            colunas: dict = {}
            for rel, nome, tipo, nulo in cur.fetchall():
                colunas.setdefault(rel, []).append({"nome": nome, "tipo": tipo, "nulo": nulo})

            saida = []
            for tb in _TABELAS:
                total, minhas = contagens.get(tb, (0, None))
                saida.append({"nome": tb, "total": total, "minhas": minhas,
                              "escopada": tb in _COM_DONO and not dono,
                              "esquema": "banco",
                              "tamanho": tamanhos.get(tb, "?"),
                              "colunas": colunas.get(tb, [])})
            return _ok(saida)

        if acao == "tabela":
            nome = um("nome")
            esq = um("esquema", "banco")
            if esq == _SCHEMA_SISTEMA:
                # a lista fechada aqui é o próprio catálogo: só tabela real do schema
                cur.execute("""SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                               WHERE n.nspname=%s AND c.relname=%s AND c.relkind='r'""",
                            (_SCHEMA_SISTEMA, nome))
                if not cur.fetchone():
                    return _erro(400, f"tabela desconhecida em {_SCHEMA_SISTEMA}: {nome!r}")
                lim = max(1, min(int(um("limite", 50) or 50), 200))
                des = max(0, int(um("desloc", 0) or 0))
                cur.execute("""SELECT a.attname FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
                               JOIN pg_namespace n ON n.oid=c.relnamespace
                               WHERE n.nspname=%s AND c.relname=%s AND a.attnum>0 AND NOT a.attisdropped
                               ORDER BY a.attnum""", (_SCHEMA_SISTEMA, nome))
                colunas = [r[0] for r in cur.fetchall()]
                cur.execute(f'SELECT count(*) FROM {_SCHEMA_SISTEMA}."{nome}"')
                total = cur.fetchone()[0]
                ordem = ("created_at DESC" if "created_at" in colunas
                         else ("id DESC" if "id" in colunas else f'"{colunas[0]}"'))
                cur.execute(f'SELECT * FROM {_SCHEMA_SISTEMA}."{nome}" ORDER BY {ordem} LIMIT %s OFFSET %s',
                            (lim, des))
                return _ok({"nome": nome, "esquema": _SCHEMA_SISTEMA, "colunas": colunas,
                            "linhas": [[_jsonavel(v) for v in r] for r in cur.fetchall()],
                            "total": total, "limite": lim, "desloc": des,
                            "escopada": False, "somente_leitura": True})
            if nome not in _TABELAS:
                return _erro(400, f"tabela desconhecida: {nome!r}")
            limite = max(1, min(int(um("limite", 50) or 50), 200))
            desloc = max(0, int(um("desloc", 0) or 0))
            cur.execute("""SELECT a.attname FROM pg_attribute a
                           JOIN pg_class c ON c.oid=a.attrelid
                           JOIN pg_namespace n ON n.oid=c.relnamespace
                           WHERE n.nspname='banco' AND c.relname=%s
                             AND a.attnum > 0 AND NOT a.attisdropped
                           ORDER BY a.attnum""", (nome,))
            colunas = [r[0] for r in cur.fetchall()]
            # O nome da tabela veio de uma lista fechada e as colunas do catálogo do
            # próprio banco: nada aqui é texto do usuário interpolado.
            onde, par = "", []
            if nome in _COM_DONO and not _eh_dono(user_id):
                onde = " WHERE user_id = %s"
                par = [user_id]
            cur.execute(f"SELECT count(*) FROM banco.{nome}{onde}", par)
            total = cur.fetchone()[0]
            ordem = "criado_em DESC" if "criado_em" in colunas else (
                "id DESC" if "id" in colunas else colunas[0])
            cur.execute(f"SELECT * FROM banco.{nome}{onde} ORDER BY {ordem} "
                        "LIMIT %s OFFSET %s", par + [limite, desloc])
            linhas = [[_jsonavel(v) for v in r] for r in cur.fetchall()]
            return _ok({"nome": nome, "esquema": "banco", "colunas": colunas,
                        "linhas": linhas, "total": total, "limite": limite,
                        "desloc": desloc,
                        "escopada": nome in _COM_DONO and not _eh_dono(user_id),
                        "dono": _eh_dono(user_id)})

        if acao == "indices":
            # `idx_scan` é a pergunta que ninguém faz e devia: índice com zero leitura
            # é índice que custa escrita e não paga nada. Índice sob demanda criado
            # por uma vista que o usuário abandonou aparece aqui com 0.
            cur.execute("""SELECT i.indexrelname, i.relname, i.idx_scan,
                                  pg_size_pretty(pg_relation_size(i.indexrelid)),
                                  x.indisvalid, pg_get_indexdef(i.indexrelid)
                           FROM pg_stat_user_indexes i
                           JOIN pg_index x ON x.indexrelid = i.indexrelid
                           WHERE i.schemaname='banco'
                           ORDER BY i.idx_scan DESC, i.indexrelname""")
            return _ok([{"nome": n, "tabela": tb, "leituras": s, "tamanho": tam,
                         "valido": v, "definicao": d}
                        for n, tb, s, tam, v, d in cur.fetchall()])

        if acao == "pendentes":
            cur.execute("""SELECT id, tipo, payload, criado_em, processado_em, tentativas, erro
                           FROM banco.evento_pendente WHERE user_id=%s
                           ORDER BY id DESC LIMIT 100""", (user_id,))
            return _ok([{"id": i, "tipo": tp, "payload": pl,
                         "criado_em": c.isoformat() if c else None,
                         "processado_em": p.isoformat() if p else None,
                         "tentativas": tt, "erro": e}
                        for i, tp, pl, c, p, tt, e in cur.fetchall()])

        if acao == "lixeira":
            cur.execute("SELECT id,no_id,titulo,deletado_em FROM banco.linha "
                        "WHERE user_id=%s AND deletado_em IS NOT NULL "
                        "ORDER BY deletado_em DESC LIMIT 200", (user_id,))
            return _ok([{"id": str(i), "no_id": str(n), "titulo": t,
                         "deletado_em": d.isoformat()} for i, n, t, d in cur.fetchall()])

        # ---- escrita ----
        if not escrita:
            return _erro(404, f"ação de leitura desconhecida: {acao}")

        try:
            if acao == "espaco.criar":
                return _ok(N.criar_espaco(cur, user_id, corpo.get("nome") or "Espaço",
                                          corpo.get("icone")))
            if acao == "espaco.arquivar":
                espaco_id = corpo.get("id")
                if not espaco_id:
                    return _erro(400, "id do espaço obrigatório")
                cur.execute("SELECT count(*) FROM banco.no WHERE espaco_id=%s AND user_id=%s "
                            "AND arquivado_em IS NULL", (espaco_id, user_id))
                if int(cur.fetchone()[0]) > 0:
                    return _erro(409, "o espaço precisa estar vazio antes de ser arquivado")
                cur.execute("UPDATE banco.espaco SET arquivado_em=now() "
                            "WHERE id=%s AND user_id=%s AND arquivado_em IS NULL",
                            (espaco_id, user_id))
                if not cur.rowcount:
                    return _erro(404, "espaço não encontrado")
                return _ok({"id": espaco_id})
            if acao == "no.criar":
                criado = N.criar_no(cur, user_id, espaco_id=corpo.get("espaco_id"),
                                    pai_id=corpo.get("pai_id"),
                                    tipo=corpo.get("tipo", "pagina"),
                                    nome=corpo.get("nome") or "Sem título",
                                    icone=corpo.get("icone"),
                                    chave_titulo=corpo.get("chave_titulo"))
                P.enfileirar_no(cur, user_id, criado["id"])
                return _ok(criado)
            if acao == "no.mover":
                posicao = N.mover_no(cur, user_id, corpo["id"],
                                     pai_id=corpo.get("pai_id"),
                                     antes_de=corpo.get("antes_de"),
                                     depois_de=corpo.get("depois_de"))
                _enfileirar_ramo(cur, user_id, corpo["id"])
                return _ok({"posicao": posicao})
            if acao == "no.renomear":
                cur.execute("UPDATE banco.no SET nome=%s, icone=CASE WHEN %s THEN %s ELSE icone END, "
                            "capa=CASE WHEN %s THEN %s ELSE capa END, "
                            "atualizado_em=now() WHERE id=%s AND user_id=%s",
                            (corpo.get("nome"), "icone" in corpo, corpo.get("icone"),
                             "capa" in corpo, corpo.get("capa"), corpo["id"], user_id))
                if not cur.rowcount:
                    return _erro(404, "nó não encontrado")
                _enfileirar_ramo(cur, user_id, corpo["id"])
                return _ok({"id": corpo["id"]})
            if acao == "no.definir_titulo":
                cur.execute("SELECT p.id,p.chave,p.tipo FROM banco.propriedade p "
                            "JOIN banco.no n ON n.id=p.no_id AND n.user_id=p.user_id "
                            "WHERE p.id=%s AND p.no_id=%s AND p.user_id=%s AND n.tipo='banco'",
                            (corpo.get("propriedade_id"), corpo.get("id"), user_id))
                propriedade = cur.fetchone()
                if not propriedade:
                    return _erro(404, "propriedade de título não encontrada neste banco")
                if propriedade[2] not in ("texto", "texto_longo", "url", "email", "telefone"):
                    return _erro(400, "a propriedade de título precisa ser textual")
                chave = propriedade[1]
                cur.execute("UPDATE banco.no SET chave_titulo=%s, atualizado_em=now() "
                            "WHERE id=%s AND user_id=%s", (chave, corpo["id"], user_id))
                cur.execute("UPDATE banco.linha SET titulo=COALESCE(props->>%s,''), atualizado_em=now() "
                            "WHERE no_id=%s AND user_id=%s AND deletado_em IS NULL",
                            (chave, corpo["id"], user_id))
                atualizadas = cur.rowcount
                _enfileirar_no_e_linhas(cur, user_id, corpo["id"])
                return _ok({"id": corpo["id"], "chave_titulo": chave,
                            "linhas_atualizadas": atualizadas})
            if acao == "no.arquivar":
                cur.execute("UPDATE banco.no SET arquivado_em=now() WHERE id=%s AND user_id=%s",
                            (corpo["id"], user_id))
                if not cur.rowcount:
                    return _erro(404, "nó não encontrado")
                P.enfileirar_remocao(cur, user_id, recurso=f"no:{corpo['id']}",
                                     no_id=corpo["id"], ramo=True)
                return _ok({"id": corpo["id"]})

            if acao == "modelo.instalar":
                instalado = M.instalar(cur, user_id, corpo["chave"], N,
                                       espaco_id=corpo.get("espaco_id"))
                M.ligar_relacoes(cur, user_id)
                _enfileirar_no_e_linhas(cur, user_id, instalado["id"])
                return _ok(instalado)
            if acao == "modelos.atualizar":
                atualizados = M.atualizar_instalados(cur, user_id, N)
                cur.execute("SELECT id FROM banco.no WHERE user_id=%s AND arquivado_em IS NULL",
                            (user_id,))
                for (no_id,) in cur.fetchall():
                    _enfileirar_no_e_linhas(cur, user_id, str(no_id))
                return _ok(atualizados)
            if acao == "arranjo.instalar":
                # Cria o(s) ESPAÇO(S) e os bancos de um arranjo. Idempotente por modelo:
                # rodar de novo não duplica banco, só acrescenta o que faltava.
                chave = corpo.get("chave") or "pessoal"
                if chave not in M.ARRANJOS:
                    return _erro(400, f"arranjo desconhecido: {chave}")
                cur.execute("SELECT modelo FROM banco.no WHERE user_id=%s AND modelo IS NOT NULL "
                            "AND arquivado_em IS NULL", (user_id,))
                ja = {r[0] for r in cur.fetchall()}
                partes = M.ARRANJOS[chave].get("espacos") or (chave,)
                saida = []
                for parte in partes:
                    a = M.ARRANJOS[parte]
                    # Reaproveita o espaço de mesmo nome: um segundo "Minha vida" ao lado
                    # do primeiro seria a pior forma de "não duplicar".
                    cur.execute("SELECT id FROM banco.espaco WHERE user_id=%s AND nome=%s "
                                "AND arquivado_em IS NULL LIMIT 1", (user_id, a["espaco"]["nome"]))
                    r = cur.fetchone()
                    if r:
                        espaco_id = str(r[0])
                    else:
                        espaco_id = N.criar_espaco(cur, user_id, a["espaco"]["nome"],
                                                   a["espaco"].get("icone"))["id"]
                    for m in a["modelos"]:
                        if m in ja:
                            continue
                        saida.append(M.instalar(cur, user_id, m, N, espaco_id=espaco_id))
                        ja.add(m)
                relacoes = M.ligar_relacoes(cur, user_id)
                for item in saida:
                    _enfileirar_no_e_linhas(cur, user_id, item["id"])
                return _ok({"arranjo": chave, "criados": len(saida), "bancos": saida,
                            "relacoes_configuradas": relacoes})

            if acao == "modelo.instalar_padrao":
                # Primeira abertura. Cinco bancos, não quinze: quinze vazios na tela
                # inicial é a definição literal de produto que ninguém usa.
                feitos = []
                cur.execute("SELECT modelo FROM banco.no WHERE user_id=%s AND modelo IS NOT NULL",
                            (user_id,))
                ja = {r[0] for r in cur.fetchall()}
                for chave in M.PADRAO:
                    if chave not in ja:
                        feitos.append(M.instalar(cur, user_id, chave, N,
                                                 espaco_id=corpo.get("espaco_id")))
                M.ligar_relacoes(cur, user_id)
                for item in feitos:
                    _enfileirar_no_e_linhas(cur, user_id, item["id"])
                return _ok(feitos)

            if acao == "propriedade.criar":
                tipo, config = corpo["tipo"], corpo.get("config") or {}
                if tipo in ("formula", "rollup"):
                    C.validar_config(cur, user_id, corpo["no_id"], tipo, config)
                p = N.criar_propriedade(cur, user_id, corpo["no_id"], corpo["nome"],
                                        tipo, config)
                if tipo in ("formula", "rollup"):
                    C.recalcular_banco(cur, user_id, corpo["no_id"])
                _enfileirar_no_e_linhas(cur, user_id, corpo["no_id"])
                return _ok(p)
            if acao == "propriedade.renomear":
                cur.execute("UPDATE banco.propriedade SET nome=%s, config=COALESCE(%s,config) "
                            "WHERE id=%s AND user_id=%s",
                            (corpo.get("nome"), json.dumps(corpo["config"]) if corpo.get("config") else None,
                             corpo["id"], user_id))
                if not cur.rowcount:
                    return _erro(404, "propriedade não encontrada")
                cur.execute("SELECT no_id FROM banco.propriedade WHERE id=%s AND user_id=%s",
                            (corpo["id"], user_id))
                _enfileirar_no_e_linhas(cur, user_id, str(cur.fetchone()[0]))
                return _ok({"id": corpo["id"]})
            if acao == "propriedade.salvar":
                cur.execute("SELECT no_id,tipo,config FROM banco.propriedade WHERE id=%s AND user_id=%s",
                            (corpo["id"], user_id))
                propriedade_atual = cur.fetchone()
                if not propriedade_atual:
                    return _erro(404, "propriedade não encontrada")
                no_propriedade, tipo_propriedade, config_atual = propriedade_atual
                config_nova = corpo.get("config") if "config" in corpo else config_atual
                if tipo_propriedade in ("formula", "rollup"):
                    C.validar_config(cur, user_id, str(no_propriedade), tipo_propriedade, config_nova or {})
                cur.execute("UPDATE banco.propriedade SET "
                            "nome=COALESCE(%s,nome), "
                            "config=CASE WHEN %s THEN %s::jsonb ELSE config END, "
                            "ordem=COALESCE(%s,ordem), oculta=COALESCE(%s,oculta) "
                            "WHERE id=%s AND user_id=%s",
                            (corpo.get("nome"), "config" in corpo,
                             json.dumps(corpo.get("config") or {}), corpo.get("ordem"),
                             corpo.get("oculta"), corpo["id"], user_id))
                if cur.rowcount and tipo_propriedade in ("formula", "rollup"):
                    C.recalcular_banco(cur, user_id, str(no_propriedade))
                if not cur.rowcount:
                    return _erro(404, "propriedade não encontrada")
                _enfileirar_no_e_linhas(cur, user_id, str(no_propriedade))
                return _ok({"id": corpo["id"]})
            if acao == "propriedade.apagar":
                cur.execute("SELECT p.chave,n.chave_titulo,p.no_id FROM banco.propriedade p "
                            "JOIN banco.no n ON n.id=p.no_id AND n.user_id=p.user_id "
                            "WHERE p.id=%s AND p.user_id=%s", (corpo["id"], user_id))
                r = cur.fetchone()
                if not r:
                    return _erro(404, "propriedade não encontrada")
                if r[0] == r[1]:
                    return _erro(400, "a propriedade de título não pode ser excluída")
                cur.execute("DELETE FROM banco.propriedade WHERE id=%s AND user_id=%s",
                            (corpo["id"], user_id))
                _enfileirar_no_e_linhas(cur, user_id, str(r[2]))
                return _ok({"id": corpo["id"]})

            if acao == "vista.criar":
                v = N.criar_vista(cur, user_id, corpo["no_id"], corpo.get("nome") or "Vista",
                                  corpo.get("tipo", "tabela"), corpo.get("config"),
                                  bool(corpo.get("padrao")))
                _indexar_da_vista(cur, user_id, corpo["no_id"], corpo.get("config") or {})
                return _ok(v)
            if acao == "vista.salvar":
                if corpo.get("padrao") is True:
                    cur.execute("SELECT no_id FROM banco.vista WHERE id=%s AND user_id=%s",
                                (corpo["id"], user_id))
                    atual = cur.fetchone()
                    if not atual:
                        return _erro(404, "vista não encontrada")
                    cur.execute("UPDATE banco.vista SET padrao=false WHERE no_id=%s "
                                "AND user_id=%s AND id<>%s", (atual[0], user_id, corpo["id"]))
                cur.execute("UPDATE banco.vista SET nome=COALESCE(%s,nome), config=%s, "
                            "ordem=COALESCE(%s,ordem), padrao=COALESCE(%s,padrao) "
                            "WHERE id=%s AND user_id=%s RETURNING no_id",
                            (corpo.get("nome"), json.dumps(corpo.get("config") or {}),
                             corpo.get("ordem"), corpo.get("padrao"), corpo["id"], user_id))
                r = cur.fetchone()
                if not r:
                    return _erro(404, "vista não encontrada")
                _indexar_da_vista(cur, user_id, str(r[0]), corpo.get("config") or {})
                return _ok({"id": corpo["id"]})
            if acao == "vista.apagar":
                cur.execute("SELECT no_id FROM banco.vista WHERE id=%s AND user_id=%s",
                            (corpo["id"], user_id))
                r = cur.fetchone()
                if not r:
                    return _erro(404, "vista não encontrada")
                cur.execute("SELECT count(*) FROM banco.vista WHERE no_id=%s AND user_id=%s",
                            (r[0], user_id))
                if int(cur.fetchone()[0]) <= 1:
                    return _erro(400, "o banco precisa manter pelo menos uma vista")
                cur.execute("DELETE FROM banco.vista WHERE id=%s AND user_id=%s",
                            (corpo["id"], user_id))
                cur.execute("UPDATE banco.vista SET padrao=true WHERE no_id=%s AND user_id=%s "
                            "AND NOT EXISTS (SELECT 1 FROM banco.vista WHERE no_id=%s AND user_id=%s AND padrao=true) "
                            "AND id=(SELECT id FROM banco.vista WHERE no_id=%s AND user_id=%s ORDER BY ordem LIMIT 1)",
                            (r[0], user_id, r[0], user_id, r[0], user_id))
                return _ok({"id": corpo["id"]})

            if acao == "linha.criar":
                criada = N.criar_linha(cur, user_id, corpo["no_id"], corpo.get("props"),
                                      corpo.get("antes_de"), corpo.get("depois_de"))
                NF.sincronizar_lembretes(cur, user_id, criada)
                calculada = C.recalcular_cascata(cur, user_id, criada["id"])
                P.enfileirar_linha(cur, user_id, criada["id"])
                return _ok({**criada, **(calculada or {})})
            if acao == "linha.atualizar":
                mudancas = corpo.get("mudancas") or {}
                D.validar_conclusao(cur, user_id, corpo["id"], mudancas)
                atualizada = N.atualizar_linha(cur, user_id, corpo["id"], mudancas)
                NF.sincronizar_lembretes(cur, user_id, atualizada)
                ajustados = D.reprogramar_dependentes(cur, user_id, corpo["id"])
                _registrar_reprogramacoes(cur, user_id, ajustados)
                recorrente = R.gerar_proxima(cur, user_id, atualizada, N)
                calculada = C.recalcular_cascata(cur, user_id, corpo["id"])
                if recorrente:
                    C.recalcular_cascata(cur, user_id, recorrente["id"])
                    NF.sincronizar_lembretes(cur, user_id, recorrente)
                    NF.criar(cur, user_id, chave=f"recorrencia:{corpo['id']}", tipo="recorrencia",
                             titulo="Próxima ocorrência criada", corpo=recorrente.get("titulo") or "",
                             no_id=recorrente.get("no_id"), linha_id=recorrente["id"])
                    P.enfileirar_linha(cur, user_id, recorrente["id"])
                P.enfileirar_linha(cur, user_id, corpo["id"])
                return _ok({**atualizada, **(calculada or {}), "recorrencia": recorrente,
                            "dependentes_ajustados": ajustados})
            if acao == "notificacao.criar":
                no_id, linha_id = corpo.get("no_id"), corpo.get("linha_id")
                if linha_id:
                    cur.execute("SELECT no_id FROM banco.linha WHERE id=%s AND user_id=%s", (linha_id, user_id))
                    alvo = cur.fetchone()
                    if not alvo:
                        return _erro(404, "linha da notificação não encontrada")
                    no_id = no_id or str(alvo[0])
                return _ok(NF.criar(cur, user_id, chave=corpo.get("chave") or f"sistema:{time.time_ns()}",
                    tipo=corpo.get("tipo") or "sistema", titulo=corpo.get("titulo") or "Logica Life",
                    corpo=corpo.get("corpo") or "", no_id=no_id, linha_id=linha_id,
                    agente=corpo.get("agente"), disponivel_em=corpo.get("disponivel_em")))
            if acao == "notificacao.ler":
                return _ok({"alteradas": NF.ler(cur, user_id, corpo.get("id"))})
            if acao == "notificacoes.ler_todas":
                return _ok({"alteradas": NF.ler(cur, user_id)})
            if acao == "linha.mover":
                return _ok({"posicao": N.mover_linha(cur, user_id, corpo["id"],
                                                     corpo.get("antes_de"), corpo.get("depois_de"))})
            if acao == "linha.apagar":
                cur.execute("DELETE FROM banco.notificacao WHERE user_id=%s AND linha_id=%s", (user_id, corpo["id"]))
                apagada = N.apagar_linha(cur, user_id, corpo["id"])
                if apagada:
                    P.enfileirar_remocao(cur, user_id, recurso=f"linha:{corpo['id']}", linha_id=corpo["id"])
                return _ok({"apagada": apagada})
            if acao == "linha.restaurar":
                restaurada = N.restaurar_linha(cur, user_id, corpo["id"])
                if restaurada:
                    P.enfileirar_linha(cur, user_id, corpo["id"])
                return _ok({"restaurada": restaurada})
            if acao == "linha.excluir":
                cur.execute("DELETE FROM banco.notificacao WHERE user_id=%s AND linha_id=%s", (user_id, corpo["id"]))
                excluida = N.excluir_linha_definitivamente(cur, user_id, corpo["id"])
                if excluida:
                    P.enfileirar_remocao(cur, user_id, recurso=f"linha:{corpo['id']}", linha_id=corpo["id"])
                return _ok({"excluida": excluida})
            if acao == "lixeira.esvaziar":
                # As linhas já saíram da memória quando entraram na lixeira.
                return _ok({"excluidos": N.esvaziar_lixeira(cur, user_id, dias=0)})
            if acao == "linha.lote":
                # N mutações numa transação: arrastar dez cartões de coluna é UM pedido,
                # e ou tudo entra ou nada entra.
                lote = (corpo.get("mudancas") or [])[:200]
                # O pool usa autocommit: validar o lote inteiro ANTES da primeira
                # escrita é o que preserva a promessa de não deixar metade concluída.
                for m in lote:
                    D.validar_conclusao(cur, user_id, m["id"], m.get("mudancas") or {})
                feitos = []
                for m in lote:
                    atualizada = N.atualizar_linha(cur, user_id, m["id"], m.get("mudancas") or {})
                    NF.sincronizar_lembretes(cur, user_id, atualizada)
                    ajustados = D.reprogramar_dependentes(cur, user_id, m["id"])
                    _registrar_reprogramacoes(cur, user_id, ajustados)
                    recorrente = R.gerar_proxima(cur, user_id, atualizada, N)
                    calculada = C.recalcular_cascata(cur, user_id, m["id"])
                    if recorrente:
                        C.recalcular_cascata(cur, user_id, recorrente["id"])
                        NF.sincronizar_lembretes(cur, user_id, recorrente)
                        P.enfileirar_linha(cur, user_id, recorrente["id"])
                    P.enfileirar_linha(cur, user_id, m["id"])
                    feitos.append({**atualizada, **(calculada or {}), "recorrencia": recorrente,
                                   "dependentes_ajustados": ajustados})
                return _ok(feitos)

            if acao == "documento.salvar":
                r = N.salvar_documento(cur, user_id, no_id=corpo.get("no_id"),
                                       linha_id=corpo.get("linha_id"), doc=corpo["doc"],
                                       texto=corpo.get("texto") or "",
                                       versao_base=corpo.get("versao_base"))
                if r["conflito"]:
                    return _erro(409, "esta página mudou em outra aba", {"versao": r["versao"]})
                if corpo.get("no_id"):
                    P.enfileirar_no(cur, user_id, corpo["no_id"])
                else:
                    P.enfileirar_linha(cur, user_id, corpo["linha_id"])
                return _ok(r)

            if acao == "documento.restaurar":
                restaurado = N.restaurar_revisao(cur, user_id, int(corpo["revisao_id"]),
                                                 versao_base=corpo.get("versao_base"))
                cur.execute("SELECT no_id,linha_id FROM banco.documento WHERE id=%s AND user_id=%s",
                            (restaurado["id"], user_id))
                alvo = cur.fetchone()
                if alvo and alvo[0]:
                    P.enfileirar_no(cur, user_id, str(alvo[0]))
                elif alvo and alvo[1]:
                    P.enfileirar_linha(cur, user_id, str(alvo[1]))
                return _ok(restaurado)

            if acao == "comentario.criar":
                comentario = N.criar_comentario(cur, user_id,
                                                no_id=corpo.get("no_id"), linha_id=corpo.get("linha_id"),
                                                block_id=corpo.get("block_id"), pai_id=corpo.get("pai_id"),
                                                corpo=corpo.get("corpo") or "")
                _enfileirar_alvo(cur, user_id, corpo.get("no_id"), corpo.get("linha_id"))
                return _ok(comentario)
            if acao == "comentario.resolver":
                cur.execute("SELECT no_id,linha_id FROM banco.comentario WHERE id=%s AND user_id=%s",
                            (corpo["id"], user_id))
                alvo = cur.fetchone()
                resolvido = N.resolver_comentario(cur, user_id, corpo["id"],
                                                  resolvido=bool(corpo.get("resolvido", True)))
                if alvo:
                    _enfileirar_alvo(cur, user_id, alvo[0], alvo[1])
                return _ok(resolvido)
            if acao == "comentario.apagar":
                cur.execute("SELECT no_id,linha_id FROM banco.comentario WHERE id=%s AND user_id=%s",
                            (corpo["id"], user_id))
                alvo = cur.fetchone()
                apagado = N.apagar_comentario(cur, user_id, corpo["id"])
                if apagado and alvo:
                    _enfileirar_alvo(cur, user_id, alvo[0], alvo[1])
                return _ok({"apagado": apagado})

            if acao == "elo.ligar":
                ligou = N.ligar(cur, user_id, corpo["propriedade_id"], corpo["origem_id"], corpo["destino_id"])
                ajuste = D.reprogramar_elo(cur, user_id, corpo["propriedade_id"], corpo["origem_id"], corpo["destino_id"])
                _registrar_reprogramacoes(cur, user_id, [ajuste] if ajuste else [])
                C.recalcular_cascata(cur, user_id, corpo["origem_id"])
                P.enfileirar_linha(cur, user_id, corpo["origem_id"])
                return _ok({"ligou": ligou, "data_ajustada": ajuste})
            if acao == "elo.desligar":
                desligou = N.desligar(cur, user_id, corpo["propriedade_id"], corpo["origem_id"], corpo["destino_id"])
                C.recalcular_cascata(cur, user_id, corpo["origem_id"])
                P.enfileirar_linha(cur, user_id, corpo["origem_id"])
                return _ok({"desligou": desligou})

            if acao == "xp.registrar":
                return _ok(X.registrar(cur, user_id, corpo["tipo"],
                                       linha_id=corpo.get("linha_id"), no_id=corpo.get("no_id"),
                                       atributo=corpo.get("atributo"), meta=corpo.get("meta")))
            if acao == "xp.reverter":
                return _ok({"revertido": X.reverter(cur, user_id, corpo["tipo"],
                                                    linha_id=corpo.get("linha_id"),
                                                    no_id=corpo.get("no_id"))})
            if acao == "sequencia.marcar":
                return _ok(X.marcar_sequencia(cur, user_id, corpo["chave"],
                                              janela_semanal=int(corpo.get("janela_semanal") or 0)))
            if acao == "progresso.recalcular":
                return _ok(X.recalcular_atributos(cur, user_id))
            if acao == "perfil.salvar":
                cur.execute("INSERT INTO banco.perfil (user_id,tz,modo_progresso) VALUES (%s,%s,%s) "
                            "ON CONFLICT (user_id) DO UPDATE SET tz=COALESCE(%s,banco.perfil.tz), "
                            "modo_progresso=COALESCE(%s,banco.perfil.modo_progresso), atualizado_em=now()",
                            (user_id, corpo.get("tz") or "America/Sao_Paulo",
                             corpo.get("modo") or "mostrar", corpo.get("tz"), corpo.get("modo")))
                return _ok(X.perfil(cur, user_id))
        except KeyError as e:
            return _erro(400, f"campo obrigatório ausente: {e}")
        except (ErroDeBanco, ErroDeProgresso, ErroDeConsulta, ErroDeCalculo) as e:
            return _erro(400, str(e))

        return _erro(404, f"ação de escrita desconhecida: {acao}")


def _enfileirar_alvo(cur, user_id, no_id=None, linha_id=None) -> None:
    if linha_id:
        P.enfileirar_linha(cur, user_id, str(linha_id))
    elif no_id:
        P.enfileirar_no(cur, user_id, str(no_id))


def _enfileirar_no_e_linhas(cur, user_id, no_id) -> None:
    """Atualiza o retrato da base e das linhas quando nome/esquema muda."""
    P.enfileirar_no(cur, user_id, str(no_id))
    cur.execute(
        "SELECT id FROM banco.linha WHERE no_id=%s AND user_id=%s "
        "AND deletado_em IS NULL AND arquivado_em IS NULL",
        (no_id, user_id),
    )
    for (linha_id,) in cur.fetchall():
        P.enfileirar_linha(cur, user_id, str(linha_id))


def _enfileirar_ramo(cur, user_id, no_id) -> None:
    cur.execute(
        "WITH RECURSIVE ramo AS ("
        " SELECT id FROM banco.no WHERE id=%s AND user_id=%s"
        " UNION ALL SELECT n.id FROM banco.no n JOIN ramo r ON n.pai_id=r.id"
        " WHERE n.user_id=%s"
        ") SELECT id FROM ramo",
        (no_id, user_id, user_id),
    )
    for (ident,) in cur.fetchall():
        _enfileirar_no_e_linhas(cur, user_id, str(ident))


def _registrar_reprogramacoes(cur, user_id, ajustados) -> None:
    for item in ajustados or []:
        NF.sincronizar_lembretes(cur, user_id, item)
        NF.criar(cur, user_id, chave=f"dependencia:{item['id']}:{item['novo_inicio']}",
                 tipo="dependencia", titulo="Prazo ajustado por dependência",
                 corpo=f"{item.get('causa') or 'Dependência'} → início em {item['novo_inicio']}",
                 no_id=item.get("no_id"), linha_id=item["id"])


def _indexar_da_vista(cur, user_id, no_id, config) -> None:
    """Quando a vista passa a filtrar ou ordenar por uma propriedade, ela ganha índice.
    Aqui, e não no caminho da requisição de leitura: criar índice é DDL, e DDL no
    caminho quente é como uma tela lenta vira uma tela travada."""
    chaves = set()

    def varre(n):
        if not isinstance(n, dict):
            return
        for k in ("e", "ou"):
            for f in n.get(k, []):
                varre(f)
        if "nao" in n:
            varre(n["nao"])
        if "prop" in n:
            chaves.add(n["prop"])

    varre(config.get("filtro"))
    for o in (config.get("ordenacao") or []):
        if o.get("prop"):
            chaves.add(o["prop"])
    if config.get("agrupar_por"):
        chaves.add(config["agrupar_por"])
    if not chaves:
        return
    tipos = {p["chave"]: p["tipo"] for p in N.propriedades(cur, user_id, no_id)}
    for c in list(chaves)[:6]:
        if c in tipos:
            try:
                N.garantir_indice(cur, user_id, no_id, c, tipos[c])
            except Exception as e:
                import sys as _s
                print(f"[banco] índice de {c} falhou: {e}", file=_s.stderr)


def despacha(metodo: str, caminho: str, qs: dict, corpo: dict,
             cabecalho_auth: str, token_global: str, publico: bool,
             de_loopback: bool = False) -> Optional[Resposta]:
    """Ponto de entrada do server.py. Devolve None quando o caminho não é do Banco de dados.

    A ordem das checagens é a ordem das defesas: desligado antes de autenticado, e
    autenticado antes de ocupar um slot."""
    if not caminho.startswith(PREFIXO):
        return None
    if not ligado():
        return _erro(503, "camada Banco de dados desligada")

    # ── confiança: a MESMA da camada de memória, MENOS o buraco do modo público ──
    #
    # Eu tinha exigido Bearer sempre, inclusive de loopback. Isso protege de um
    # processo local comprometido, mas quebra o painel do próprio Mind, que é servido
    # daqui e não manda autenticação nenhuma — a tela levaria 401 e o Arquiteto ficaria
    # sem enxergar o banco. Trocar o modelo de confiança por causa de uma tela seria
    # errado; manter uma tela que não funciona também.
    #
    # A regra fica assim, e o motivo de cada linha:
    #   loopback lê ....... igual à memória. Quem já está na máquina já lê a memória
    #                       inteira; negar aqui seria teatro.
    #   Bearer lê ......... de fora da máquina, sempre.
    #   LOGICA_MIND_PUBLIC  NÃO abre o Banco de dados. O modo demo abre todo GET /api
    #                       do Mind, e aqui moram finanças pessoais e diário.
    #   escrita ........... com LOGICA_MIND_TOKEN configurado, Bearer SEMPRE, inclusive
    #                       de loopback — espelha o _can_write() do server.
    user_id = usuario_de(cabecalho_auth or "", token_global or "")
    escrita = metodo == "POST"
    if not user_id:
        if publico:
            return _erro(401, "o Banco de dados não abre no modo público: aqui moram "
                              "finanças pessoais e diário")
        if not de_loopback:
            return _erro(401, "de fora da máquina, o Banco de dados exige Bearer")
        if escrita and token_global:
            return _erro(401, "escrita no Banco de dados exige Bearer, inclusive de loopback")
        user_id = _owner_empresa()

    if not _SEM.acquire(blocking=False):
        # Falhar rápido é a defesa. Enfileirar aqui seria repetir o colapso de 2026.
        return _erro(503, f"Registro saturado ({_SLOTS} em voo); tente de novo")
    try:
        return trata(metodo, caminho, qs, corpo or {}, user_id)
    finally:
        _SEM.release()
