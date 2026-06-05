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
from .base import Store, rank, apply_filter

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

    def __init__(self, path: str = "logica_mind.db", max_candidates: int = 5000):
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
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self._conn.row_factory = sqlite3.Row
        if path not in (":memory:", ""):
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=30000")
            self._conn.execute("PRAGMA synchronous=NORMAL")
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

    # ---- (de)serialization -------------------------------------------------
    @staticmethod
    def _row_to_memory(row: sqlite3.Row) -> Memory:
        keys = row.keys()
        m = Memory(
            id=row["id"],
            namespace=row["namespace"],
            content=row["content"],
            layer=MemoryLayer(row["layer"]),
            embedding=json.loads(row["embedding"]) if row["embedding"] else None,
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
                    metadata_filter: Optional[dict] = None) -> List[Memory]:
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
        cur = self._conn.execute(sql, params)
        return [self._row_to_memory(r) for r in cur.fetchall()]

    @_locked
    def search(self, namespace, query_embedding, query_text, layers=None, limit=20, metadata_filter=None) -> List[SearchResult]:
        # SQL already scoped by metadata_filter; apply_filter is a cheap safety net
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
    def all(self, namespace, layers=None) -> List[Memory]:
        return self._candidates(namespace, layers)

    @_locked
    def namespaces(self) -> List[str]:
        cur = self._conn.execute("SELECT DISTINCT namespace FROM memories ORDER BY namespace")
        return [r["namespace"] for r in cur.fetchall()]

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
    def count(self, namespace, layers=None) -> int:
        sql = "SELECT COUNT(*) AS n FROM memories WHERE namespace = ?"
        params: list = [namespace]
        if layers:
            placeholders = ",".join("?" for _ in layers)
            sql += f" AND layer IN ({placeholders})"
            params += [l.value for l in layers]
        return self._conn.execute(sql, params).fetchone()["n"]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
