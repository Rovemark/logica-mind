"""Postgres store — o backend oficial do Logica Mind.

Paridade com o SQLiteStore, não um esboço. O que este arquivo era antes (140 linhas,
contrato base apenas) quebrava em 28 chamadas espalhadas por server.py, core.py e
dreaming.py assim que virasse o store primário, porque o MultiStore encaminha
session_stats/day/day_counts/timerange/count/mentions/tagged/page/… para os filhos.

Três defeitos do esboço, corrigidos aqui, cada um com o motivo medido:

1. EMBEDDING EM `bytea`, NÃO `jsonb`. O comentário do sqlite.py registra a medição:
   `json.loads` de 5.000 embeddings por recall custava ~0,85 s, e por isso o formato
   virou BLOB float32 (10-20× mais rápido, ~5× menor). Guardar em jsonb aqui
   reimportaria uma regressão já paga. O codec é o MESMO do sqlite (importado, não
   copiado) — a migração vira cópia de bytes, sem transcodificar 88 mil vetores.
   Leitura DUAL: linha legada em jsonb continua sendo lida.

2. BUSCA LEXICAL. O `_candidates` do sqlite une a janela de recência (5.000) com o
   FTS5 sobre o corpus INTEIRO. O esboço só fazia `ORDER BY created_at DESC LIMIT`:
   no namespace `astro` (86 mil memórias) isso tirava 81 mil do alcance lexical, em
   silêncio — memória antiga com a palavra exata nunca voltava. Aqui há coluna
   `busca tsvector` gerada + GIN, e a mesma união.
   Config `simple`, não `portuguese`: o corpus é PT e EN misturados, e o stemming
   português destrói termo técnico em inglês. É também o que mais se parece com o
   FTS5, que não faz stemming.

3. POOL DE CONEXÃO. Uma conexão só, com os 32 workers do servidor HTTP em cima,
   serializa igual ao lock do SQLite — foi exatamente o que a medição da linha de
   base mostrou (recall sozinho 0,96 s, com 8 simultâneos p50 7,9 s: concorrência
   efetiva de 1). O pool é o que quebra isso; sem ele a migração troca de arquivo e
   mantém o modo de colapso.

Os prazos (statement_timeout, lock_timeout) vivem NO PAPEL do banco
(`ALTER ROLE lm_mem SET statement_timeout='15s'`), não aqui: se o app esquecer, o
banco não esquece.
"""
from __future__ import annotations

import json
import os
from typing import List, Optional

from ..types import Memory, MemoryLayer, SearchResult
from .base import Store, rank, apply_filter, matches_filter, _tokset
# codec único, compartilhado com o SQLiteStore. Duplicar o empacotamento seria
# criar duas verdades sobre o formato do vetor.
from .sqlite import _pack_embedding, _unpack_embedding

_TABELA = "logica_mind_memory"

# `unaccent` é STABLE, e coluna gerada exige IMMUTABLE. O embrulho abaixo é o
# contorno canônico: fixar o dicionário torna a chamada determinística.
_SCHEMA = f"""
CREATE OR REPLACE FUNCTION lm_unaccent_imm(text) RETURNS text
  LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS
$$ SELECT public.unaccent('public.unaccent', $1) $$;

CREATE TABLE IF NOT EXISTS {_TABELA} (
    id text PRIMARY KEY, namespace text NOT NULL, content text NOT NULL,
    layer text NOT NULL, embedding bytea, metadata jsonb, importance real DEFAULT 0.5,
    tags jsonb, source_ids jsonb, created_at text, seq bigint,
    access_count integer DEFAULT 0,
    last_recalled_at text, surprise_score real DEFAULT 0.0
);
-- migração idempotente de tabela pré-existente (CREATE TABLE IF NOT EXISTS não acrescenta coluna)
ALTER TABLE {_TABELA} ADD COLUMN IF NOT EXISTS last_recalled_at text;
ALTER TABLE {_TABELA} ADD COLUMN IF NOT EXISTS surprise_score real DEFAULT 0.0;
ALTER TABLE {_TABELA} ADD COLUMN IF NOT EXISTS seq bigint;
ALTER TABLE {_TABELA} ADD COLUMN IF NOT EXISTS busca tsvector
  GENERATED ALWAYS AS (to_tsvector('simple', lm_unaccent_imm(content))) STORED;

CREATE INDEX IF NOT EXISTS idx_lmpg_ns_layer ON {_TABELA} (namespace, layer);
CREATE INDEX IF NOT EXISTS idx_lmpg_created  ON {_TABELA} (namespace, created_at DESC, seq DESC);
CREATE INDEX IF NOT EXISTS idx_lmpg_dia      ON {_TABELA} (left(created_at, 10));
CREATE INDEX IF NOT EXISTS idx_lmpg_busca    ON {_TABELA} USING gin (busca);
-- jsonb_path_ops é ~2-3x menor e mais rápido que jsonb_ops, e só suporta `@>`,
-- que é exatamente o operador que o filtro de metadata usa.
CREATE INDEX IF NOT EXISTS idx_lmpg_meta     ON {_TABELA} USING gin (metadata jsonb_path_ops);
-- índices parciais nas chaves que as facetas filtram com IS NOT NULL. Sem eles cada
-- voto de faceta era varredura do namespace inteiro (mesma lição do sqlite).
CREATE INDEX IF NOT EXISTS idx_lmpg_sessao   ON {_TABELA} (namespace, (metadata->>'session')) WHERE metadata->>'session' IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_lmpg_dim      ON {_TABELA} (namespace, (metadata->>'dimension')) WHERE metadata->>'dimension' IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_lmpg_canal    ON {_TABELA} (namespace, (metadata->>'channel'))   WHERE metadata->>'channel' IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_lmpg_projeto  ON {_TABELA} (namespace, (metadata->>'project'))   WHERE metadata->>'project' IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_lmpg_squad    ON {_TABELA} (namespace, (metadata->>'squad'))     WHERE metadata->>'squad' IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_lmpg_fonte    ON {_TABELA} (namespace, (metadata->>'source'))    WHERE metadata->>'source' IS NOT NULL;
"""

# pgvector é OPCIONAL e o código tem que subir sem ele. Com a extensão, a busca deixa
# de ser "amostre 5.000 candidatos e ranqueie em Python" e vira "peça ao banco os K
# vizinhos mais próximos entre as 141 mil". A janela de candidatos existia só porque o
# ranqueamento acontecia fora do banco; com pgvector a pergunta "quantos amostrar"
# simplesmente deixa de existir.
_SCHEMA_VEC = """
ALTER TABLE {tabela} ADD COLUMN IF NOT EXISTS vec vector({dims});
CREATE INDEX IF NOT EXISTS idx_lmpg_vec ON {tabela}
  USING hnsw (vec vector_cosine_ops) WITH (m = 16, ef_construction = 64);
"""

# projeção completa, num lugar só: acrescentar coluna muda esta string e o _row_to_memory
_COLS = ("id,namespace,content,layer,embedding,metadata,importance,tags,"
         "source_ids,created_at,seq,access_count,last_recalled_at,surprise_score")
# variante sem o vetor: o bytea de ~1,5 KB por linha nem sai do disco. É o que
# alimenta enumeração e agregação (sessões, dimensões, analytics), que nunca
# calculam semelhança.
_COLS_SEM_EMB = ("id,namespace,content,layer,NULL::bytea AS embedding,metadata,importance,tags,"
                 "source_ids,created_at,seq,access_count,last_recalled_at,surprise_score")

_CHAVES_FACETA = ("channel", "project", "squad", "skill", "source")


def _bytes(v):
    """psycopg devolve bytea como memoryview; o codec espera bytes."""
    if isinstance(v, memoryview):
        return v.tobytes()
    return v


class PostgresStore(Store):
    name = "postgres"

    def __init__(self, dsn: Optional[str] = None, max_candidates: int = 5000,
                 min_size: int = 1, max_size: Optional[int] = None,
                 fts_limit: int = 3000):
        try:
            import psycopg  # noqa: F401
            from psycopg_pool import ConnectionPool
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "psycopg/psycopg-pool ausentes. Rode: "
                "pip install 'psycopg[binary]>=3.3.0,<4' psycopg-pool") from e
        self.max_candidates = max_candidates
        self._fts_limit = fts_limit
        self._last_read_at = None   # contrapressão: o dream cede quando há recall ativo
        # `path` NÃO é onde os dados moram (moram no Postgres). É onde ficam os
        # ARQUIVOS-SATÉLITE que o produto sempre guardou ao lado do banco: o diário de
        # sonhos e os nomes de sessão.
        #
        # `dreaming._journal_path()` e `web/server._session_names_path()` procuram
        # `store.path` e, sem ele, devolvem None EM SILÊNCIO: o diário de 187 ciclos
        # some da tela e as rodadas novas deixam de ser gravadas, sem erro nenhum. Foi
        # exatamente o que aconteceu no corte para Postgres, e só apareceu porque o
        # Arquiteto reparou que "Sonhos não está mais funcionando".
        #
        # Apontar para o mesmo LM_DB de sempre faz os satélites continuarem no lugar
        # de sempre, e o histórico que já existe volta a ser encontrado.
        self.path = os.environ.get("LM_DB") or os.path.join(
            os.path.expanduser("~"), "logicaos", ".pm2", "logica_mind.db")
        self.dims = int(os.environ.get("LM_VEC_DIMS", "384") or 384)
        self.k_vetorial = int(os.environ.get("LM_K_VETORIAL", "100") or 100)
        self.k_lexical = int(os.environ.get("LM_K_LEXICAL", "300") or 300)
        self.k_recente = int(os.environ.get("LM_K_RECENTE", "1000") or 1000)
        dsn = dsn or os.environ.get("LM_PG_DSN_MEM") or os.environ.get("POSTGRES_DSN", "")
        if max_size is None:
            max_size = int(os.environ.get("LM_PG_POOL_MEM", "6"))
        # teto ABAIXO do pool HTTP (32 workers) de propósito: quando estoura, a
        # requisição falha rápido em vez de enfileirar 32 threads dentro do banco.
        # `hnsw.ef_search` é o TETO de quantos nós o índice explora, e o padrão 40
        # significa que pedir os 100 vizinhos mais próximos devolve 40. Medido no
        # EXPLAIN: `Limit (rows=100) (actual rows=40)`. Sem isto, o k_vetorial acima
        # de 40 é ficção: o número está no código e o índice não entrega.
        self.ef_search = int(os.environ.get("LM_HNSW_EF", "0") or 0) or max(64, self.k_vetorial * 2)

        def _preparar(con):
            try:
                con.execute(f"SET hnsw.ef_search = {int(self.ef_search)}")
            except Exception:
                pass   # sem pgvector a variável não existe, e isso não é erro

        self._pool = ConnectionPool(
            dsn, min_size=min_size, max_size=max_size, timeout=5.0,
            kwargs={"autocommit": True}, configure=_preparar, open=True,
        )
        # K por caminho, AFINADO POR MEDIÇÃO contra 141 mil memórias reais, não
        # escolhido no chute. Seis proporções testadas; esta foi a única com cosseno
        # médio do topo POSITIVO em relação ao SQLite (+0,0037) e ainda 3,6x mais
        # rápida (106 ms contra 386 ms).
        #
        # Por que o vetorial é o MENOR dos três: pedir os 200 vizinhos mais próximos
        # de verdade traz muito ruído de conversa. O MiniLM dá cosseno alto (0,51) para
        # português genérico curto — "abri aqui, tá normal né?" aparece como vizinho de
        # qualquer coisa. A janela de recência do SQLite funcionava como filtro
        # acidental contra isso, e aqui esse filtro virou explícito.
        with self._pool.connection() as con:
            con.execute(_SCHEMA)
            self.tem_vetor = self._preparar_vetor(con)

    def _preparar_vetor(self, con) -> bool:
        """Liga o caminho pgvector se a extensão existir. NUNCA levanta: um appliance
        sem a extensão tem que subir com a memória funcionando, no caminho antigo, em
        vez de entrar em laço de reinício. E a extensão some sozinha se alguém rodar
        `brew upgrade postgresql@16` — o keg é substituído e o `vector.so` vai junto.
        Por isso a checagem é no boot, toda vez, e não uma suposição."""
        if os.environ.get("LM_PGVECTOR", "1").lower() in ("0", "false", "no"):
            return False
        try:
            r = con.execute("SELECT 1 FROM pg_extension WHERE extname='vector'").fetchone()
            if not r:
                return False
            con.execute(_SCHEMA_VEC.format(tabela=_TABELA, dims=self.dims))
            return True
        except Exception as e:   # pragma: no cover
            import sys as _s
            print(f"[postgres] pgvector indisponível, usando ranqueamento em processo: {e}",
                  file=_s.stderr)
            return False

    def _cand_pgvector(self, namespace, layers, metadata_filter, query_embedding,
                       query_text, with_embeddings=False) -> list:
        """Três fontes, unidas: os K vizinhos mais próximos DE VERDADE (não de uma
        amostra), os K melhores casamentos lexicais do corpus inteiro, e os K mais
        recentes.

        A SIMILARIDADE VEM PRONTA DO BANCO, e isto foi a maior otimização medida.
        Antes: buscar 1.335 linhas COM o embedding (1.536 bytes cada) dava 3,5 MB pela
        rede por recall — 132 ms — e depois 65 ms recalculando em Python um cosseno
        que o Postgres já tinha calculado para ordenar. Os três índices que ACHAM os
        candidatos custam 5,3 ms somados; o resto era transporte e retrabalho.
        Agora vem `1 - (vec <=> consulta)` como um número de 8 bytes, e o embedding
        não sai do disco. Devolve [(Memory, similaridade_ou_None)].
        """
        cols = _COLS_SEM_EMB
        where = "namespace=%s"
        wp: list = [namespace]
        if layers:
            where += " AND layer = ANY(%s)"
            wp.append([l.value for l in layers])
        where += self._where_meta(metadata_filter, wp)

        partes, params = [], []
        vetor = "[" + ",".join(f"{float(x):.7g}" for x in query_embedding) + "]"
        partes.append(f"(SELECT id FROM {_TABELA} WHERE {where} AND vec IS NOT NULL "
                      "ORDER BY vec <=> %s::vector LIMIT %s)")
        params += wp + [vetor, self.k_vetorial]
        toks = [t for t in list(_tokset(query_text))[:12]] if query_text else []
        if toks:
            tsq = " | ".join(toks)
            partes.append(f"(SELECT id FROM {_TABELA} WHERE {where} AND busca @@ to_tsquery('simple', %s) "
                          "ORDER BY ts_rank_cd(busca, to_tsquery('simple', %s)) DESC LIMIT %s)")
            params += wp + [tsq, tsq, self.k_lexical]
        partes.append(f"(SELECT id FROM {_TABELA} WHERE {where} "
                      "ORDER BY created_at DESC, seq DESC NULLS LAST LIMIT %s)")
        params += wp + [self.k_recente]

        # `sim` só existe onde há vetor; onde não há, vem NULL e o BM25 assume,
        # exatamente como o rank() da base faz.
        sql = (f"SELECT {cols}, CASE WHEN vec IS NULL THEN NULL "
               f"ELSE 1 - (vec <=> %s::vector) END AS sim "
               f"FROM {_TABELA} WHERE {where} AND id IN ("
               + " UNION ".join(partes) + ")")
        linhas = self._q(sql, [vetor] + wp + params)
        return [(self._row_to_memory(r[:-1], False), r[-1]) for r in linhas]

    # ---- (de)serialização --------------------------------------------------
    @staticmethod
    def _row_to_memory(r, with_embeddings: bool = True) -> Memory:
        (id_, ns, content, layer, embedding, metadata, importance, tags,
         source_ids, created_at, seq, access_count, last_recalled_at, surprise_score) = r
        emb = None
        if with_embeddings and embedding is not None:
            emb = _unpack_embedding(_bytes(embedding))
        m = Memory(
            id=id_, namespace=ns, content=content, layer=MemoryLayer(layer),
            embedding=emb, metadata=metadata or {}, importance=importance if importance is not None else 0.5,
            tags=tags or [], source_ids=source_ids or [], created_at=created_at or "",
            access_count=access_count or 0,
            last_recalled_at=last_recalled_at,
            surprise_score=float(surprise_score or 0.0),
        )
        if seq is not None:
            m.seq = seq
        return m

    def _q(self, sql, params=None, fetch="all"):
        with self._pool.connection() as con, con.cursor() as cur:
            cur.execute(sql, params or [])
            if fetch == "all":
                return cur.fetchall()
            if fetch == "one":
                return cur.fetchone()
            return cur.rowcount

    # ---- API do Store ------------------------------------------------------
    def add(self, memories: List[Memory]) -> None:
        if not memories:
            return
        def _vec(e):
            if not e or not getattr(self, "tem_vetor", False) or len(e) != self.dims:
                return None
            return "[" + ",".join(f"{float(x):.7g}" for x in e) + "]"

        linhas = [
            (m.id, m.namespace, m.content, m.layer.value,
             _pack_embedding(m.embedding), _vec(m.embedding),
             json.dumps(m.metadata), m.importance, json.dumps(m.tags),
             json.dumps(m.source_ids), m.created_at, getattr(m, "seq", None),
             m.access_count, getattr(m, "last_recalled_at", None),
             getattr(m, "surprise_score", 0.0))
            for m in memories
        ]
        with self._pool.connection() as con, con.cursor() as cur:
            cur.executemany(
                f"INSERT INTO {_TABELA} (id,namespace,content,layer,embedding,vec,metadata,"
                "importance,tags,source_ids,created_at,seq,access_count,last_recalled_at,surprise_score) "
                "VALUES (%s,%s,%s,%s,%s,%s::vector,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (id) DO UPDATE SET content=excluded.content, layer=excluded.layer, "
                "embedding=excluded.embedding, vec=excluded.vec, metadata=excluded.metadata, "
                "importance=excluded.importance, "
                "tags=excluded.tags, source_ids=excluded.source_ids, seq=excluded.seq, "
                "access_count=excluded.access_count, last_recalled_at=excluded.last_recalled_at, "
                "surprise_score=excluded.surprise_score",
                linhas,
            )

    @staticmethod
    def _where_meta(metadata_filter, params: list) -> str:
        """Contenção jsonb tipada (trata bool/número/nulo certo, ao contrário de ->> texto)."""
        sql = ""
        if not metadata_filter:
            return sql
        for k, v in metadata_filter.items():
            if isinstance(v, (list, tuple, set)):
                vals = list(v)
                if not vals:
                    return sql + " AND FALSE"
                sql += " AND (" + " OR ".join(["metadata @> %s::jsonb"] * len(vals)) + ")"
                params.extend(json.dumps({k: item}) for item in vals)
            else:
                sql += " AND metadata @> %s::jsonb"
                params.append(json.dumps({k: v}))
        return sql

    def _candidates(self, namespace, layers, metadata_filter=None,
                    with_embeddings: bool = True, query_text: str = None) -> List[Memory]:
        cols = _COLS if with_embeddings else _COLS_SEM_EMB
        where = "namespace=%s"
        wp: list = [namespace]
        if layers:
            where += " AND layer = ANY(%s)"
            wp.append([l.value for l in layers])
        where += self._where_meta(metadata_filter, wp)

        # JANELA DE RECÊNCIA ∪ CASAMENTO LEXICAL DO CORPUS INTEIRO.
        # A união é o ponto: o ranqueamento semântico decide por cima, a busca
        # textual só ALARGA o conjunto de candidatos, para que memória antiga com a
        # palavra exata volte a ser alcançável.
        toks = [t for t in list(_tokset(query_text))[:12]] if query_text else []
        if toks:
            tsq = " | ".join(toks)
            sql = (f"SELECT {cols} FROM {_TABELA} WHERE {where} AND (id IN ("
                   f"  SELECT id FROM {_TABELA} WHERE {where} "
                   "  ORDER BY created_at DESC, seq DESC NULLS LAST LIMIT %s"
                   f") OR id IN ("
                   f"  SELECT id FROM {_TABELA} WHERE {where} AND busca @@ to_tsquery('simple', %s) "
                   "  ORDER BY ts_rank_cd(busca, to_tsquery('simple', %s)) DESC LIMIT %s"
                   "))")
            params = wp + wp + [self.max_candidates] + wp + [tsq, tsq, self._fts_limit]
        else:
            sql = (f"SELECT {cols} FROM {_TABELA} WHERE {where} "
                   "ORDER BY created_at DESC, seq DESC NULLS LAST LIMIT %s")
            params = wp + [self.max_candidates]
        return [self._row_to_memory(r, with_embeddings) for r in self._q(sql, params)]

    def search(self, namespace, query_embedding, query_text, layers=None, limit=20,
               metadata_filter=None) -> List[SearchResult]:
        import time as _t
        self._last_read_at = _t.monotonic()
        usa_vetor = (self.tem_vetor and query_embedding
                     and len(query_embedding) == self.dims)
        if usa_vetor:
            try:
                pares = self._cand_pgvector(namespace, layers, metadata_filter,
                                            query_embedding, query_text)
                return self._ranquear_com_sim(pares, query_text, limit, metadata_filter)
            except Exception as e:   # degrada, não quebra
                import sys as _s
                print(f"[postgres] busca vetorial falhou, caindo no caminho antigo: {e}",
                      file=_s.stderr)
        cands = self._candidates(namespace, layers, metadata_filter, query_text=query_text)
        return rank(apply_filter(cands, metadata_filter), query_embedding, query_text, limit)

    @staticmethod
    def _ranquear_com_sim(pares, query_text, limit, metadata_filter=None) -> List[SearchResult]:
        """Mesma semântica do rank() da base, com o cosseno já vindo pronto.

        A regra que precisa ser idêntica: memória COM vetor pontua por cosseno,
        memória SEM vetor pontua por BM25 normalizado sobre o lote, e pontuação zero
        ou negativa não entra. Divergir daqui faria o Postgres ordenar diferente do
        SQLite por um motivo que ninguém acharia depois."""
        from .base import bm25_scores
        pares = [(m, s) for m, s in pares if matches_filter(m, metadata_filter)]
        if not pares:
            return []
        mems = [m for m, _ in pares]
        sims = [s for _, s in pares]
        lex = bm25_scores(query_text, [m.content for m in mems]) if any(s is None for s in sims) else None
        saida = []
        for i, m in enumerate(mems):
            s = sims[i] if sims[i] is not None else (lex[i] if lex is not None else 0.0)
            s = float(s)
            if s <= 0.0:
                continue
            saida.append(SearchResult(memory=m, score=s, components={"similarity": round(s, 4)}))
        saida.sort(key=lambda r: r.score, reverse=True)
        return saida[:limit]

    def get(self, namespace, memory_id) -> Optional[Memory]:
        r = self._q(f"SELECT {_COLS} FROM {_TABELA} WHERE namespace=%s AND id=%s",
                    (namespace, memory_id), fetch="one")
        return self._row_to_memory(r) if r else None

    def delete(self, namespace, memory_id) -> bool:
        return self._q(f"DELETE FROM {_TABELA} WHERE namespace=%s AND id=%s",
                       (namespace, memory_id), fetch="count") > 0

    def all(self, namespace, layers=None, with_embeddings=True) -> List[Memory]:
        # ENUMERAÇÃO SEM TETO, de propósito: all() alimenta o grafo, o exportador e as
        # agregações. A janela de max_candidates pertence só ao ranqueamento da BUSCA.
        # Com o teto, namespace com mais arestas que a janela perdia as mais antigas em
        # silêncio (medido no sqlite: 7.471 arestas, 2.471 invisíveis).
        cols = _COLS if with_embeddings else _COLS_SEM_EMB
        sql = f"SELECT {cols} FROM {_TABELA} WHERE namespace=%s"
        params: list = [namespace]
        if layers:
            sql += " AND layer = ANY(%s)"
            params.append([l.value for l in layers])
        sql += " ORDER BY created_at DESC, seq DESC NULLS LAST"
        return [self._row_to_memory(r, with_embeddings) for r in self._q(sql, params)]

    def namespaces(self) -> List[str]:
        return [r[0] for r in self._q(f"SELECT DISTINCT namespace FROM {_TABELA} ORDER BY namespace")]

    def count(self, namespace, layers=None) -> int:
        sql = f"SELECT COUNT(*) FROM {_TABELA} WHERE namespace=%s"
        params: list = [namespace]
        if layers:
            sql += " AND layer = ANY(%s)"
            params.append([l.value for l in layers])
        return self._q(sql, params, fetch="one")[0]

    def timerange(self, namespace: str, layers=None):
        sql = f"SELECT MIN(created_at), MAX(created_at) FROM {_TABELA} WHERE namespace=%s"
        params: list = [namespace]
        if layers:
            sql += " AND layer = ANY(%s)"
            params.append([l.value for l in layers])
        r = self._q(sql, params, fetch="one")
        return (r[0], r[1]) if r else (None, None)

    def delete_layers(self, namespace: str, layers=None) -> int:
        sql = f"DELETE FROM {_TABELA} WHERE namespace=%s"
        params: list = [namespace]
        if layers:
            sql += " AND layer = ANY(%s)"
            params.append([l.value for l in layers])
        return self._q(sql, params, fetch="count")

    def touch(self, namespace, ids) -> None:
        if not ids:
            return
        import datetime as _dt
        agora = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._q(f"UPDATE {_TABELA} SET access_count=access_count+1, last_recalled_at=%s "
                "WHERE namespace=%s AND id = ANY(%s)", (agora, namespace, list(ids)), fetch="count")

    def bump_importance(self, namespace: str, pairs) -> None:
        """Só UPDATE da importância, NÃO toca no embedding. O add() gravaria
        embedding=NULL quando None, e isso é perda de dado no reforço do dream."""
        if not pairs:
            return
        with self._pool.connection() as con, con.cursor() as cur:
            cur.executemany(
                f"UPDATE {_TABELA} SET importance=%s WHERE namespace=%s AND id=%s",
                [(float(imp), namespace, mid) for (mid, imp) in pairs])

    def set_embeddings(self, namespace: str, pairs) -> int:
        """Substituição em lote de embeddings — combustível do reembed quando o
        embedder troca de dimensão."""
        def _vec(e):
            if not e or not getattr(self, "tem_vetor", False) or len(e) != self.dims:
                return None
            return "[" + ",".join(f"{float(x):.7g}" for x in e) + "]"
        linhas = [(_pack_embedding(v), _vec(v), namespace, mid) for mid, v in pairs]
        if not linhas:
            return 0
        with self._pool.connection() as con, con.cursor() as cur:
            cur.executemany(f"UPDATE {_TABELA} SET embedding=%s, vec=%s::vector "
                            "WHERE namespace=%s AND id=%s", linhas)
        return len(linhas)

    def change_token(self, namespace=None) -> str:
        """Marca barata que muda quando o dado muda — alimenta cache de leitura.
        Sem namespace usa as estatísticas da tabela (O(1)); com namespace, conta.
        O equivalente do `PRAGMA data_version` do sqlite aqui é n_tup_*."""
        if namespace:
            r = self._q(f"SELECT COUNT(*), COALESCE(MAX(created_at),'') FROM {_TABELA} "
                        "WHERE namespace=%s", (namespace,), fetch="one")
            return f"{r[0]}:{r[1]}"
        r = self._q("SELECT COALESCE(n_tup_ins,0)+COALESCE(n_tup_upd,0)+COALESCE(n_tup_del,0) "
                    "FROM pg_stat_all_tables WHERE relname=%s", (_TABELA,), fetch="one")
        return f"{(r[0] if r else 0)}"

    def bucket_counts(self):
        """Contagem por namespace e camada numa consulta só — barra lateral e stats
        sem materializar milhares de objetos Memory."""
        out: dict = {}
        for ns, layer, n in self._q(f"SELECT namespace, layer, COUNT(*) FROM {_TABELA} "
                                    "GROUP BY namespace, layer"):
            out.setdefault(ns, {})[layer] = n
        return out

    def day_counts(self, namespace=None, exclude_layers=None):
        """Contagem por dia e camada numa consulta só — mapa de calor do calendário
        sem materializar linha."""
        sql = f"SELECT left(created_at,10) d, layer, COUNT(*) FROM {_TABELA} WHERE created_at <> ''"
        params: list = []
        if namespace:
            sql += " AND namespace=%s"
            params.append(namespace)
        if exclude_layers:
            sql += " AND NOT (layer = ANY(%s))"
            params.append([str(l) for l in exclude_layers])
        sql += " GROUP BY d, layer"
        out: dict = {}
        for d, layer, n in self._q(sql, params):
            e = out.setdefault(d, {"total": 0, "episodic": 0, "semantic": 0, "graph": 0, "user": 0})
            e[layer] = e.get(layer, 0) + n
            e["total"] += n
        return out

    def day(self, namespace=None, date=None, layers=None, with_embeddings=False):
        """Toda memória criada num dia UTC. O filtro de data vive no SQL, então NÃO é
        cortado pela janela de 5.000 candidatos. namespace=None varre globalmente."""
        cols = _COLS if with_embeddings else _COLS_SEM_EMB
        sql = f"SELECT {cols} FROM {_TABELA} WHERE left(created_at,10)=%s"
        params: list = [date]
        if namespace:
            sql += " AND namespace=%s"
            params.append(namespace)
        if layers:
            sql += " AND layer = ANY(%s)"
            params.append([l.value for l in layers])
        sql += " ORDER BY created_at DESC, seq DESC NULLS LAST"
        return [self._row_to_memory(r, with_embeddings) for r in self._q(sql, params)]

    def dimension_counts(self, namespace=None):
        """({dimensão: {count, cats}}, sem_categoria) agregado no SQL, SEM o teto da
        janela — com o teto, a grade do Perfil lia quase vazia."""
        sql = (f"SELECT metadata->>'dimension', metadata->>'category', COUNT(*) FROM {_TABELA}")
        params: list = []
        if namespace:
            sql += " WHERE namespace=%s"
            params.append(namespace)
        sql += " GROUP BY 1, 2"
        agg: dict = {}
        sem_categoria = 0
        for d, c, n in self._q(sql, params):
            if not d:
                sem_categoria += n
                continue
            e = agg.setdefault(d, {"count": 0, "cats": {}})
            e["count"] += n
            if c:
                e["cats"][c] = e["cats"].get(c, 0) + n
        return agg, sem_categoria

    def dimensioned(self, namespace=None):
        """[(conteúdo, dimensão)] de toda memória categorizada que não é aresta —
        sem teto, para o mapa entidade→dimensão enxergar o corpus inteiro."""
        sql = (f"SELECT content, metadata->>'dimension' FROM {_TABELA} "
               "WHERE metadata->>'dimension' IS NOT NULL "
               "AND NOT (COALESCE(tags,'[]'::jsonb) @> '[\"edge\"]'::jsonb) "
               "AND NOT (COALESCE(tags,'[]'::jsonb) @> '[\"alias\"]'::jsonb)")
        params: list = []
        if namespace:
            sql += " AND namespace=%s"
            params.append(namespace)
        return [(c, d) for c, d in self._q(sql, params) if c and d]

    def filter_memories(self, namespace=None, layers=None, dimension=None, category=None,
                        session=None, limit=200, offset=0, with_embeddings=False,
                        metadata_filter=None):
        """Memórias filtradas por metadata no SQL, mais novas primeiro, SEM o teto da
        janela — clicar numa dimensão precisa achar a memória antiga, não devolver []."""
        cols = _COLS if with_embeddings else _COLS_SEM_EMB
        sql = f"SELECT {cols} FROM {_TABELA} WHERE TRUE"
        params: list = []
        if namespace:
            sql += " AND namespace=%s"
            params.append(namespace)
        if layers:
            sql += " AND layer = ANY(%s)"
            params.append([l.value for l in layers])
        for chave, valor in (("dimension", dimension), ("category", category), ("session", session)):
            if valor:
                sql += f" AND metadata->>'{chave}' = %s"
                params.append(valor)
        sql += self._where_meta(metadata_filter, params)
        sql += " ORDER BY created_at DESC, seq DESC NULLS LAST LIMIT %s OFFSET %s"
        params += [int(limit), int(offset)]
        return [self._row_to_memory(r, with_embeddings) for r in self._q(sql, params)]

    def mentions(self, namespace, name, limit=0, with_embeddings=False):
        """Pré-filtro rápido de menções a `name`, para o caminho de entidade não
        carregar e tokenizar o namespace inteiro a cada passagem do mouse. Devolve um
        SUPERCONJUNTO; quem chama roda a comparação exata em cima deste conjunto
        pequeno, então a correção não muda. namespace=None busca globalmente."""
        if not name or not name.strip():
            return []
        toks = list(_tokset(name)) or [name.strip().lower()]
        cols = _COLS if with_embeddings else _COLS_SEM_EMB
        sql = f"SELECT {cols} FROM {_TABELA} WHERE TRUE"
        params: list = []
        if namespace:
            sql += " AND namespace=%s"
            params.append(namespace)
        clausula = " AND ".join(["content ILIKE %s"] * len(toks))
        sql += f" AND (({clausula}) OR metadata::text ILIKE %s)"
        params += [f"%{t}%" for t in toks]
        params.append(f"%{name}%")
        sql += " ORDER BY created_at DESC, seq DESC NULLS LAST"
        if limit:
            sql += " LIMIT %s"
            params.append(int(limit))
        return [self._row_to_memory(r, with_embeddings) for r in self._q(sql, params)]

    def tagged(self, namespace=None, key="channel"):
        """(conteúdo, valor) das memórias que carregam metadata[chave] — combustível
        do voto de faceta por entidade. Só chaves da lista branca, porque a chave é
        interpolada no caminho jsonb."""
        if key not in _CHAVES_FACETA:
            return []
        sql = (f"SELECT content, metadata->>'{key}' FROM {_TABELA} "
               f"WHERE metadata->>'{key}' IS NOT NULL AND content IS NOT NULL")
        params: list = []
        if namespace:
            sql += " AND namespace=%s"
            params.append(namespace)
        return [(c, v) for c, v in self._q(sql, params) if c and v]

    def page(self, namespace=None, layers=None, limit=100, offset=0):
        """Uma página limitada, mais novas primeiro — LIMIT/OFFSET no SQL para a lista
        materializar ~100 linhas em vez de todas."""
        sql = f"SELECT {_COLS} FROM {_TABELA}"
        params: list = []
        onde = []
        if namespace:
            onde.append("namespace=%s")
            params.append(namespace)
        if layers:
            onde.append("layer = ANY(%s)")
            params.append([l.value for l in layers])
        if onde:
            sql += " WHERE " + " AND ".join(onde)
        sql += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params += [int(limit), int(offset)]
        return [self._row_to_memory(r) for r in self._q(sql, params)]

    def session_stats(self, namespace: Optional[str] = None,
                      limit: Optional[int] = None, offset: int = 0) -> List[dict]:
        """Resumo por sessão calculado NO SQL — o endpoint de sessões não pode
        carregar o store inteiro no Python só para agrupar (dezenas de milhares de
        linhas por namespace travavam o processo e disparavam o laço de reinício da
        sonda de saúde). Mesmo formato do fallback da base."""
        nscl = "AND namespace = %s" if namespace is not None else ""
        nsp: list = [namespace] if namespace is not None else []
        sql = (
            "SELECT namespace, sid, cnt, first_at, last_at, first_content, first_source FROM ("
            "  SELECT namespace,"
            "         metadata->>'session' AS sid,"
            "         content AS first_content,"
            "         metadata->>'source' AS first_source,"
            "         COUNT(*)        OVER w AS cnt,"
            "         MIN(created_at) OVER w AS first_at,"
            "         MAX(created_at) OVER w AS last_at,"
            "         ROW_NUMBER()    OVER (PARTITION BY namespace, metadata->>'session'"
            "                               ORDER BY created_at ASC, seq ASC NULLS FIRST) AS rn"
            f"  FROM {_TABELA}"
            f"  WHERE metadata->>'session' IS NOT NULL {nscl}"
            "  WINDOW w AS (PARTITION BY namespace, metadata->>'session')"
            ") s WHERE rn = 1 ORDER BY last_at DESC"
        )
        params = list(nsp)
        if limit is not None:
            sql += " LIMIT %s OFFSET %s"
            params += [int(limit), int(offset)]
        out: List[dict] = []
        indice: dict = {}
        for ns, sid, cnt, first_at, last_at, first_content, first_source in self._q(sql, params):
            e = {"id": sid, "namespace": ns, "count": cnt, "first": first_at, "last": last_at,
                 "first_content": ((first_content or "").strip()[:60]) or None,
                 "source": first_source, "record": None}
            out.append(e)
            indice[(ns, sid)] = e
        if out:
            rec_sql = (f"SELECT namespace, metadata->>'session', metadata FROM {_TABELA} "
                       f"WHERE metadata->>'record' IS NOT NULL {nscl} ORDER BY created_at ASC")
            for ns, sid, md in self._q(rec_sql, nsp):
                e = indice.get((ns, sid))
                if not e:
                    continue
                md = md or {}
                e["record"] = {"title": md.get("title"), "status": md.get("status"),
                               "participants": md.get("participants") or [],
                               "metrics": md.get("metrics") or {}, "links": md.get("links") or {}}
        return out

    # ---- diagnóstico -------------------------------------------------------
    def pool_stats(self) -> dict:
        """O que o /api/health profundo mostra. O health raso é arquivo estático e
        ficou verde durante o colapso medido de 3.803 threads: sem número de pool,
        não há como saber que degradou antes do HTTP 000."""
        s = self._pool.get_stats()
        return {"em_uso": s.get("pool_size", 0) - s.get("pool_available", 0),
                "disponivel": s.get("pool_available", 0),
                "max": self._pool.max_size,
                "esperando": s.get("requests_waiting", 0)}

    def close(self) -> None:
        self._pool.close()
