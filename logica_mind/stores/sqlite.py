"""SQLite store — the zero-dependency default.

Persistent, single-file, stdlib `sqlite3`. Embeddings are stored as JSON and
ranked in-process (vector cosine when present, lexical overlap otherwise), so it
works whether or not an embedder is configured. For large/shared deployments use
`SupabaseStore` (pgvector) instead.

One `sqlite3.Connection` is shared across threads (the dashboard runs under a
ThreadingHTTPServer — one thread per request). `check_same_thread=False` allows
that, but concurrent statements would still interleave cursors on the single
connection, so every public method runs under `self._lock` (execute AND fetch
together). The lock is an RLock so internal calls (search→_candidates) re-enter
safely.
"""
from __future__ import annotations

import functools
import json
import os
import sqlite3
import threading
from typing import List, Optional

from ..types import Memory, MemoryLayer, SearchResult
from .base import Store, rank, apply_filter, _tokset

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id          TEXT PRIMARY KEY,
    namespace   TEXT NOT NULL,
    content     TEXT NOT NULL,
    layer       TEXT NOT NULL,
    embedding   TEXT,
    metadata    TEXT,
    importance  REAL DEFAULT 0.5,
    tags        TEXT,
    source_ids  TEXT,
    created_at  TEXT,
    seq              INTEGER,
    access_count     INTEGER DEFAULT 0,
    last_recalled_at TEXT,
    surprise_score   REAL DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS idx_mem_ns_layer ON memories (namespace, layer);
CREATE INDEX IF NOT EXISTS idx_mem_created  ON memories (namespace, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_mem_session  ON memories (namespace, json_extract(metadata, '$.session'));
-- partial expression indexes: dimensioned()/tagged() filter on these JSON keys with
-- IS NOT NULL — without them every facet vote was a full namespace scan.
CREATE INDEX IF NOT EXISTS idx_mem_dim     ON memories (namespace, json_extract(metadata, '$.dimension')) WHERE json_extract(metadata, '$.dimension') IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_mem_channel ON memories (namespace, json_extract(metadata, '$.channel'))   WHERE json_extract(metadata, '$.channel') IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_mem_project ON memories (namespace, json_extract(metadata, '$.project'))   WHERE json_extract(metadata, '$.project') IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_mem_squad   ON memories (namespace, json_extract(metadata, '$.squad'))     WHERE json_extract(metadata, '$.squad') IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_mem_source  ON memories (namespace, json_extract(metadata, '$.source'))    WHERE json_extract(metadata, '$.source') IS NOT NULL;
"""


def _locked(fn):
    """Serialize a method against the shared connection (execute→fetch as one
    critical section) so concurrent HTTP threads can't interleave cursors."""
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return fn(self, *args, **kwargs)
    return wrapper


class SQLiteStore(Store):
    name = "sqlite"

    def __init__(self, path: str = "logica_mind.db", max_candidates: int = 5000,
                 encryption_key: Optional[str] = None):
        self.path = path
        self.max_candidates = max_candidates
        # reentrant so a locked public method can call another helper that locks
        self._lock = threading.RLock()
        if path not in (":memory:", "") and os.path.dirname(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
        # timeout + WAL + busy_timeout: each lifecycle hook is a separate process
        # opening the same shared db; WAL lets readers run during a writer and
        # busy_timeout makes concurrent writers wait-and-retry instead of dropping
        # the captured turn with 'database is locked'.
        if encryption_key:
            # at-rest encryption via SQLCipher (optional: pip install logica-mind[sqlcipher]).
            # Same dbapi as sqlite3; PRAGMA key must run before any other statement.
            try:
                import sqlcipher3 as _drv                      # type: ignore
            except ImportError as e:  # pragma: no cover
                raise RuntimeError(
                    "encryption_key set but sqlcipher3 is not installed. "
                    "Run: pip install logica-mind[sqlcipher]") from e
            self._conn = _drv.connect(path, check_same_thread=False, timeout=30)
            self._conn.row_factory = _drv.Row
            self._conn.execute("PRAGMA key = '%s'" % encryption_key.replace("'", "''"))
        else:
            self._conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
            self._conn.row_factory = sqlite3.Row
        if path not in (":memory:", ""):
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=30000")
            # Durabilidade real contra queda de energia: FULL faz fsync do WAL a cada commit
            # (NORMAL só no checkpoint → corrompeu no apagão de 19/06). fullfsync=ON força o
            # F_FULLFSYNC do macOS (APFS/HFS mentem no fsync() comum, não vão ao disco físico).
            self._conn.execute("PRAGMA fullfsync=ON")
            self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.executescript(_SCHEMA)
        # migrate pre-seq databases (CREATE TABLE IF NOT EXISTS won't add columns)
        for col, defn in [
            ("seq", "INTEGER"),
            ("last_recalled_at", "TEXT"),
            ("surprise_score", "REAL DEFAULT 0.0"),
        ]:
            try:
                self._conn.execute(f"ALTER TABLE memories ADD COLUMN {col} {defn}")
            except sqlite3.OperationalError:
                pass  # column already present
        self._conn.commit()

        # Conexão de LEITURA dedicada: reads (recall/search) NÃO podem esperar o lock de ESCRITA — o
        # dream cycle / captura escrevem em lotes longos segurando o RLock e o recall travava dezenas
        # de segundos. WAL já permite ler durante escrita no nível SQLite; aqui damos aos reads uma
        # conexão própria + lock próprio (uma conexão sqlite3 não é usável por 2 threads ao mesmo
        # tempo). Só no caso arquivo+sem-cripto; :memory: (db por-conexão) e SQLCipher reusam a principal.
        if path not in (":memory:", "") and not encryption_key:
            self._rlock = threading.Lock()
            self._rconn = sqlite3.connect(path, check_same_thread=False, timeout=30)
            self._rconn.row_factory = sqlite3.Row
            self._rconn.execute("PRAGMA busy_timeout=30000")
            self._rconn.execute("PRAGMA query_only=ON")   # read-only defensivo
        else:
            self._rlock = self._lock
            self._rconn = self._conn

    # ---- (de)serialization -------------------------------------------------
    @staticmethod
    def _row_to_memory(row: sqlite3.Row, with_embeddings: bool = True) -> Memory:
        keys = row.keys()
        m = Memory(
            id=row["id"],
            namespace=row["namespace"],
            content=row["content"],
            layer=MemoryLayer(row["layer"]),
            embedding=(json.loads(row["embedding"]) if with_embeddings and "embedding" in keys and row["embedding"] else None),
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            importance=row["importance"] if row["importance"] is not None else 0.5,
            tags=json.loads(row["tags"]) if row["tags"] else [],
            source_ids=json.loads(row["source_ids"]) if row["source_ids"] else [],
            created_at=row["created_at"],
            access_count=row["access_count"] or 0,
            last_recalled_at=row["last_recalled_at"] if "last_recalled_at" in keys else None,
            surprise_score=float(row["surprise_score"] or 0.0) if "surprise_score" in keys else 0.0,
        )
        sq = row["seq"] if "seq" in keys else None
        if sq is not None:
            m.seq = sq
        return m

    # ---- Store API ---------------------------------------------------------
    @_locked
    def add(self, memories: List[Memory]) -> None:
        rows = [
            (
                m.id, m.namespace, m.content, m.layer.value,
                json.dumps(m.embedding) if m.embedding is not None else None,
                json.dumps(m.metadata), m.importance,
                json.dumps(m.tags), json.dumps(m.source_ids),
                m.created_at, getattr(m, "seq", None), m.access_count,
                getattr(m, "last_recalled_at", None),
                getattr(m, "surprise_score", 0.0),
            )
            for m in memories
        ]
        self._conn.executemany(
            "INSERT OR REPLACE INTO memories "
            "(id, namespace, content, layer, embedding, metadata, importance, "
            " tags, source_ids, created_at, seq, access_count, "
            " last_recalled_at, surprise_score) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        self._conn.commit()

    def _candidates(self, namespace: str, layers: Optional[List[MemoryLayer]],
                    metadata_filter: Optional[dict] = None,
                    with_embeddings: bool = True) -> List[Memory]:
        sql = "SELECT * FROM memories WHERE namespace = ?"
        params: list = [namespace]
        if layers:
            placeholders = ",".join("?" for _ in layers)
            sql += f" AND layer IN ({placeholders})"
            params += [l.value for l in layers]
        # push metadata filter into SQL so it applies BEFORE the LIMIT window —
        # otherwise an older session's rows could fall outside the newest N
        if metadata_filter:
            for k, v in metadata_filter.items():
                if isinstance(v, (list, tuple, set)):
                    if not v:
                        sql += " AND 0"
                        continue
                    ph = ",".join("?" for _ in v)
                    sql += f" AND json_extract(metadata, '$.' || ?) IN ({ph})"
                    params.append(k)
                    params.extend(list(v))
                else:
                    sql += " AND json_extract(metadata, '$.' || ?) = ?"
                    params.append(k)
                    params.append(v)
        # seq (persisted, process-monotonic) then rowid break created_at ties by
        # true insertion order — created_at has only whole-second granularity, so a
        # prompt and its answer can share it
        sql += " ORDER BY created_at DESC, seq DESC, rowid DESC LIMIT ?"
        params.append(self.max_candidates)
        cur = self._rconn.execute(sql, params)   # conexão de LEITURA (chamado só pelo search, sob _rlock)
        return [self._row_to_memory(r, with_embeddings) for r in cur.fetchall()]

    def search(self, namespace, query_embedding, query_text, layers=None, limit=20, metadata_filter=None) -> List[SearchResult]:
        # SEM @_locked de propósito: a LEITURA roda na conexão dedicada (_rconn/_rlock), não no lock de
        # ESCRITA — assim o recall NÃO trava atrás do dream cycle/captura (que seguram o RLock de escrita).
        # SQL already scoped by metadata_filter; apply_filter is a cheap safety net.
        import time as _t
        self._last_read_at = _t.monotonic()   # backpressure: o dream cede quando há conversa/recall ativo
        with self._rlock:
            cands = apply_filter(self._candidates(namespace, layers, metadata_filter), metadata_filter)
        return rank(cands, query_embedding, query_text, limit)

    @_locked
    def get(self, namespace: str, memory_id: str) -> Optional[Memory]:
        cur = self._conn.execute(
            "SELECT * FROM memories WHERE namespace = ? AND id = ?", (namespace, memory_id)
        )
        row = cur.fetchone()
        return self._row_to_memory(row) if row else None

    @_locked
    def delete(self, namespace: str, memory_id: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM memories WHERE namespace = ? AND id = ?", (namespace, memory_id)
        )
        self._conn.commit()
        return cur.rowcount > 0

    @_locked
    def timerange(self, namespace: str, layers=None):
        sql = "SELECT MIN(created_at) AS lo, MAX(created_at) AS hi FROM memories WHERE namespace = ?"
        params: list = [namespace]
        if layers:
            placeholders = ",".join("?" for _ in layers)
            sql += f" AND layer IN ({placeholders})"
            params += [l.value for l in layers]
        row = self._conn.execute(sql, params).fetchone()
        return (row["lo"], row["hi"]) if row else (None, None)

    @_locked
    def delete_layers(self, namespace: str, layers=None) -> int:
        sql = "DELETE FROM memories WHERE namespace = ?"
        params: list = [namespace]
        if layers:
            placeholders = ",".join("?" for _ in layers)
            sql += f" AND layer IN ({placeholders})"
            params += [l.value for l in layers]
        cur = self._conn.execute(sql, params)
        self._conn.commit()
        return cur.rowcount

    @_locked
    def all(self, namespace, layers=None, with_embeddings=True) -> List[Memory]:
        # with_embeddings=False skips parsing the 384-float vector per row — a big
        # win for enumeration/aggregation endpoints (sessions, dimensions, analytics)
        # that only read content/metadata, never similarity.
        #
        # ENUMERATION IS UNCAPPED on purpose: all() feeds the graph (edges), the
        # exporter and aggregations — the max_candidates window belongs to SEARCH
        # ranking only. With the cap, a namespace holding more graph rows than the
        # window silently DROPPED its oldest edges from the graph/dimensions/
        # co-mentions (seen live: 7,471 edges, 2,471 invisible).
        sql = "SELECT * FROM memories WHERE namespace = ?"
        params: list = [namespace]
        if layers:
            placeholders = ",".join("?" for _ in layers)
            sql += f" AND layer IN ({placeholders})"
            params += [l.value for l in layers]
        sql += " ORDER BY created_at DESC, seq DESC, rowid DESC"
        cur = self._conn.execute(sql, params)
        return [self._row_to_memory(r, with_embeddings) for r in cur.fetchall()]

    @_locked
    def namespaces(self) -> List[str]:
        cur = self._conn.execute("SELECT DISTINCT namespace FROM memories ORDER BY namespace")
        return [r["namespace"] for r in cur.fetchall()]

    @_locked
    def session_stats(self, namespace: Optional[str] = None,
                      limit: Optional[int] = None, offset: int = 0) -> List[dict]:
        """Per-session rollup computed IN SQL — the sessions endpoint must never load
        the whole store into Python just to GROUP BY session (tens of thousands of
        rows × every namespace stalled the process and tripped the health-probe restart
        loop). Uses the (namespace, $.session) index. Same shape as the base fallback."""
        # window functions need SQLite ≥ 3.25; older engines take the portable path
        try:
            if tuple(int(x) for x in sqlite3.sqlite_version.split(".")[:2]) < (3, 25):
                return Store.session_stats(self, namespace, limit, offset)
        except Exception:
            return Store.session_stats(self, namespace, limit, offset)
        nsclause = "AND namespace = ?" if namespace is not None else ""
        ns_params: list = [namespace] if namespace is not None else []
        # one pass: COUNT/first/last per session + the EARLIEST row's content & source
        sql = (
            "SELECT namespace, sid, cnt, first_at, last_at, first_content, first_source FROM ("
            "  SELECT namespace,"
            "         json_extract(metadata,'$.session') AS sid,"
            "         content AS first_content,"
            "         json_extract(metadata,'$.source') AS first_source,"
            "         COUNT(*)        OVER w AS cnt,"
            "         MIN(created_at) OVER w AS first_at,"
            "         MAX(created_at) OVER w AS last_at,"
            "         ROW_NUMBER()    OVER (PARTITION BY namespace, json_extract(metadata,'$.session')"
            "                               ORDER BY created_at ASC, seq ASC, rowid ASC) AS rn"
            "  FROM memories"
            f"  WHERE json_extract(metadata,'$.session') IS NOT NULL {nsclause}"
            "  WINDOW w AS (PARTITION BY namespace, json_extract(metadata,'$.session'))"
            ") WHERE rn = 1 ORDER BY last_at DESC"
        )
        params = list(ns_params)
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params += [int(limit), int(offset)]
        out: List[dict] = []
        index: dict = {}
        for r in self._conn.execute(sql, params).fetchall():
            e = {"id": r["sid"], "namespace": r["namespace"], "count": r["cnt"],
                 "first": r["first_at"], "last": r["last_at"],
                 "first_content": ((r["first_content"] or "").strip()[:60]) or None,
                 "source": r["first_source"], "record": None}
            out.append(e)
            index[(r["namespace"], r["sid"])] = e
        # attach the most-recent structured session record (rare rows) to the page
        if out:
            rec_sql = ("SELECT namespace, json_extract(metadata,'$.session') sid, metadata "
                       "FROM memories WHERE json_extract(metadata,'$.record') IS NOT NULL "
                       f"{nsclause} ORDER BY created_at ASC")
            for rr in self._conn.execute(rec_sql, ns_params).fetchall():
                e = index.get((rr["namespace"], rr["sid"]))
                if not e:
                    continue
                try:
                    md = json.loads(rr["metadata"] or "{}")
                except Exception:
                    md = {}
                e["record"] = {"title": md.get("title"), "status": md.get("status"),
                               "participants": md.get("participants") or [],
                               "metrics": md.get("metrics") or {}, "links": md.get("links") or {}}
        return out

    @_locked
    def set_embeddings(self, namespace: str, pairs) -> int:
        """Bulk-replace embeddings: pairs = [(memory_id, embedding), …]. Fuel for
        reembed() — the dimension migration when the embedder changes."""
        rows = [(json.dumps(v) if v is not None else None, namespace, mid) for mid, v in pairs]
        self._conn.executemany(
            "UPDATE memories SET embedding = ? WHERE namespace = ? AND id = ?", rows)
        self._conn.commit()
        return len(rows)

    @_locked
    def change_token(self, namespace=None) -> str:
        """Cheap token that changes whenever the (namespace's) data changes — fuels
        read-side caches (graph_viz). COUNT catches deletes, MAX(rowid) catches
        inserts; in-place UPDATEs of old rows are rare enough that the dream cycle's
        rewrite pattern (insert+invalidate) still flips the token."""
        if namespace:
            r = self._conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(MAX(rowid),0) AS m FROM memories WHERE namespace = ?",
                (namespace,)).fetchone()
        else:
            r = self._conn.execute("SELECT COUNT(*) AS n, COALESCE(MAX(rowid),0) AS m FROM memories").fetchone()
        return f"{r['n']}:{r['m']}"

    @_locked
    def touch(self, namespace: str, ids: List[str]) -> None:
        if not ids:
            return
        import datetime as _dt
        now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        placeholders = ",".join("?" for _ in ids)
        # UPDATE existing rows only — never INSERT; also set last_recalled_at
        self._conn.execute(
            f"UPDATE memories SET access_count = access_count + 1, last_recalled_at = ? "
            f"WHERE namespace = ? AND id IN ({placeholders})",
            [now, namespace, *ids],
        )
        self._conn.commit()

    @_locked
    def bump_importance(self, namespace: str, pairs) -> None:
        """UPDATE-only da importância (NÃO toca embedding). Pro dream reforçar sem carregar/reescrever
        os vetores — o add() gravaria embedding=NULL quando None (= data-loss). Espelha touch()."""
        if not pairs:
            return
        self._conn.executemany(
            "UPDATE memories SET importance = ? WHERE namespace = ? AND id = ?",
            [(float(imp), namespace, mid) for (mid, imp) in pairs],
        )
        self._conn.commit()

    @_locked
    def count(self, namespace, layers=None) -> int:
        sql = "SELECT COUNT(*) AS n FROM memories WHERE namespace = ?"
        params: list = [namespace]
        if layers:
            placeholders = ",".join("?" for _ in layers)
            sql += f" AND layer IN ({placeholders})"
            params += [l.value for l in layers]
        return self._conn.execute(sql, params).fetchone()["n"]

    @_locked
    def bucket_counts(self):
        """All per-namespace, per-layer counts in ONE SQL query — no row/embedding
        materialization. Powers the sidebar + stats without loading thousands of
        Memory objects. Returns {namespace: {layer: n}}."""
        out: dict = {}
        for r in self._conn.execute(
                "SELECT namespace, layer, COUNT(*) AS n FROM memories GROUP BY namespace, layer"):
            out.setdefault(r["namespace"], {})[r["layer"]] = r["n"]
        return out

    @_locked
    def day_counts(self, namespace=None, exclude_layers=None):
        """Per-day, per-layer counts in ONE SQL query — powers the calendar heatmap
        without materializing rows. namespace None = every namespace; exclude_layers
        drops layers (e.g. 'graph') from the buckets. Returns {day: {total, <layer>}}."""
        sql = "SELECT substr(created_at,1,10) AS d, layer, COUNT(*) AS n FROM memories WHERE created_at <> ''"
        params: list = []
        if namespace:
            sql += " AND namespace = ?"
            params.append(namespace)
        if exclude_layers:
            ph = ",".join("?" for _ in exclude_layers)
            sql += f" AND layer NOT IN ({ph})"
            params += list(exclude_layers)
        sql += " GROUP BY d, layer"
        out: dict = {}
        for r in self._conn.execute(sql, params):
            e = out.setdefault(r["d"], {"total": 0, "episodic": 0, "semantic": 0, "graph": 0, "user": 0})
            e[r["layer"]] = e.get(r["layer"], 0) + r["n"]
            e["total"] += r["n"]
        return out

    @_locked
    def day(self, namespace=None, date=None, layers=None, with_embeddings=False):
        """Every memory created on a given UTC day (YYYY-MM-DD) — date filter is in
        SQL (substr(created_at,1,10)=?) so it is NOT capped by the _candidates 5000
        window. namespace=None scans GLOBALLY across all namespaces (__all__ view)."""
        sql = "SELECT * FROM memories WHERE substr(created_at,1,10) = ?"
        params: list = [date]
        if namespace:
            sql += " AND namespace = ?"
            params.append(namespace)
        if layers:
            ph = ",".join("?" for _ in layers)
            sql += f" AND layer IN ({ph})"
            params += [l.value for l in layers]
        sql += " ORDER BY created_at DESC, seq DESC, rowid DESC"
        cur = self._conn.execute(sql, params)
        return [self._row_to_memory(r, with_embeddings) for r in cur.fetchall()]

    @_locked
    def dimension_counts(self, namespace=None):
        """({dimension: {count, cats:{category:count}}}, uncategorized) aggregated in
        SQL — NOT capped by the 5000 _candidates window (store.all() missed most of
        the categorized corpus, so the Profile grid read near-empty)."""
        where = ""
        params: list = []
        if namespace:
            where = " WHERE namespace = ?"
            params.append(namespace)
        sql = ("SELECT json_extract(metadata,'$.dimension') d, "
               "json_extract(metadata,'$.category') c, count(*) n FROM memories"
               + where + " GROUP BY d, c")
        agg: dict = {}
        uncategorized = 0
        for d, c, n in self._conn.execute(sql, params).fetchall():
            if not d:
                uncategorized += n
                continue
            e = agg.setdefault(d, {"count": 0, "cats": {}})
            e["count"] += n
            if c:
                e["cats"][c] = e["cats"].get(c, 0) + n
        return agg, uncategorized

    def dimensioned(self, namespace=None):
        """[(content, dimension)] for every categorized (non-edge) memory — SQL,
        uncapped — so entity→dimension mapping sees the whole corpus."""
        sql = ("SELECT content, json_extract(metadata,'$.dimension') d FROM memories "
               "WHERE json_extract(metadata,'$.dimension') IS NOT NULL "
               "AND (tags IS NULL OR (tags NOT LIKE '%\"edge\"%' AND tags NOT LIKE '%\"alias\"%'))")
        params: list = []
        if namespace:
            sql += " AND namespace = ?"
            params.append(namespace)
        return [(c, d) for c, d in self._conn.execute(sql, params).fetchall() if c and d]

    def filter_memories(self, namespace=None, layers=None, dimension=None, category=None,
                        session=None, limit=200, offset=0, with_embeddings=False):
        """Memories filtered by metadata (dimension / category / session) in SQL —
        newest first, NOT capped by the 5000 candidate window (so clicking a
        dimension on the Profile finds its older categorized memories, not [])."""
        sql = "SELECT * FROM memories WHERE 1=1"
        params: list = []
        if namespace:
            sql += " AND namespace = ?"
            params.append(namespace)
        if layers:
            ph = ",".join("?" for _ in layers)
            sql += f" AND layer IN ({ph})"
            params += [l.value for l in layers]
        if dimension:
            sql += " AND json_extract(metadata,'$.dimension') = ?"
            params.append(dimension)
        if category:
            sql += " AND json_extract(metadata,'$.category') = ?"
            params.append(category)
        if session:
            sql += " AND json_extract(metadata,'$.session') = ?"
            params.append(session)
        sql += " ORDER BY created_at DESC, seq DESC, rowid DESC LIMIT ? OFFSET ?"
        params += [limit, offset]
        cur = self._conn.execute(sql, params)
        return [self._row_to_memory(r, with_embeddings) for r in cur.fetchall()]

    @_locked
    def mentions(self, namespace, name, limit=0, with_embeddings=False):
        """Candidate memories that may mention `name` — a fast SQL LIKE pre-filter so
        the entity-detail/hover path (/api/node) doesn't load+tokenise the WHOLE
        namespace (O(N) per hover). Returns a SUPERSET: every token of the name appears
        as a substring in content, OR the raw name appears in the metadata JSON (graph
        subject/object). The caller still runs the precise token match on this small
        set, so correctness is unchanged. namespace=None searches GLOBALLY (__all__)."""
        if not name or not name.strip():
            return []
        toks = list(_tokset(name)) or [name.strip().lower()]
        sql = "SELECT * FROM memories WHERE 1=1"
        params: list = []
        if namespace:
            sql += " AND namespace = ?"
            params.append(namespace)
        token_clause = " AND ".join("content LIKE ?" for _ in toks)
        sql += f" AND (({token_clause}) OR metadata LIKE ?)"
        params += [f"%{t}%" for t in toks]
        params.append(f"%{name}%")
        sql += " ORDER BY created_at DESC, seq DESC, rowid DESC"
        if limit:
            sql += " LIMIT ?"
            params.append(int(limit))
        cur = self._conn.execute(sql, params)
        return [self._row_to_memory(r, with_embeddings) for r in cur.fetchall()]

    @_locked
    def tagged(self, namespace=None, key="channel"):
        """(content, value) pairs for memories carrying metadata[key] — fuel for the
        per-entity facet voting (channel / project / squad / …): whatever tag the host
        application writes on its memories can colour & organize the graph. Whitelisted
        keys only (the key is interpolated into the json_extract path)."""
        if key not in ("channel", "project", "squad", "skill", "source"):
            return []
        sql = (f"SELECT content, json_extract(metadata,'$.{key}') v FROM memories "
               f"WHERE json_extract(metadata,'$.{key}') IS NOT NULL AND content IS NOT NULL")
        params: list = []
        if namespace:
            sql += " AND namespace = ?"
            params.append(namespace)
        return [(c, v) for c, v in self._conn.execute(sql, params).fetchall() if c and v]

    def page(self, namespace=None, layers=None, limit=100, offset=0):
        """A bounded page of memories (newest first) — LIMIT/OFFSET in SQL so a list
        view materializes ~100 rows instead of every row. namespace=None pages
        GLOBALLY across all namespaces (for the __all__ view)."""
        sql = "SELECT * FROM memories"
        params: list = []
        where = []
        if namespace:
            where.append("namespace = ?")
            params.append(namespace)
        if layers:
            ph = ",".join("?" for _ in layers)
            where.append(f"layer IN ({ph})")
            params += [l.value for l in layers]
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params += [int(limit), int(offset)]
        return [self._row_to_memory(r) for r in self._conn.execute(sql, params).fetchall()]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
