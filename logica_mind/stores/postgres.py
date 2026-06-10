"""Postgres store (optional: `pip install psycopg[binary]`).

A self-hosted SQL backend with the same interface as SQLiteStore. Embeddings are
stored as jsonb and ranked in-process (consistent with the other stores); point
SupabaseStore(use_rpc=True) at a pgvector-enabled DB for native acceleration.
"""
from __future__ import annotations

import json
from typing import List, Optional

from ..types import Memory, MemoryLayer, SearchResult
from .base import Store, rank, apply_filter

_SCHEMA = """
CREATE TABLE IF NOT EXISTS logica_mind_memory (
    id text PRIMARY KEY, namespace text NOT NULL, content text NOT NULL,
    layer text NOT NULL, embedding jsonb, metadata jsonb, importance real DEFAULT 0.5,
    tags jsonb, source_ids jsonb, created_at text, access_count integer DEFAULT 0,
    last_recalled_at text, surprise_score real DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS idx_lmpg_ns_layer ON logica_mind_memory (namespace, layer);
CREATE INDEX IF NOT EXISTS idx_lmpg_created ON logica_mind_memory (namespace, created_at DESC);
-- idempotent migration for pre-existing tables (CREATE TABLE IF NOT EXISTS won't add columns)
ALTER TABLE logica_mind_memory ADD COLUMN IF NOT EXISTS last_recalled_at text;
ALTER TABLE logica_mind_memory ADD COLUMN IF NOT EXISTS surprise_score real DEFAULT 0.0;
"""

# the full projection used by every read — kept in one place so adding a column
# only changes one string + _row_to_memory
_COLS = ("id,namespace,content,layer,embedding,metadata,importance,tags,"
         "source_ids,created_at,access_count,last_recalled_at,surprise_score")


class PostgresStore(Store):
    name = "postgres"

    def __init__(self, dsn: Optional[str] = None, max_candidates: int = 5000):
        try:
            import psycopg  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("psycopg not installed. Run: pip install 'psycopg[binary]'") from e
        import os
        self.max_candidates = max_candidates
        self._conn = psycopg.connect(dsn or os.environ.get("POSTGRES_DSN", ""), autocommit=True)
        self._conn.execute(_SCHEMA)

    @staticmethod
    def _row_to_memory(r) -> Memory:
        (id_, ns, content, layer, embedding, metadata, importance, tags,
         source_ids, created_at, access_count, last_recalled_at, surprise_score) = r
        return Memory(
            id=id_, namespace=ns, content=content, layer=MemoryLayer(layer),
            embedding=embedding, metadata=metadata or {}, importance=importance or 0.5,
            tags=tags or [], source_ids=source_ids or [], created_at=created_at or "",
            access_count=access_count or 0,
            last_recalled_at=last_recalled_at,
            surprise_score=float(surprise_score or 0.0),
        )

    def add(self, memories: List[Memory]) -> None:
        with self._conn.cursor() as cur:
            for m in memories:
                cur.execute(
                    "INSERT INTO logica_mind_memory (id,namespace,content,layer,embedding,metadata,"
                    "importance,tags,source_ids,created_at,access_count,last_recalled_at,surprise_score) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (id) DO UPDATE SET content=excluded.content, layer=excluded.layer, "
                    "embedding=excluded.embedding, metadata=excluded.metadata, importance=excluded.importance, "
                    "tags=excluded.tags, source_ids=excluded.source_ids, access_count=excluded.access_count, "
                    "last_recalled_at=excluded.last_recalled_at, surprise_score=excluded.surprise_score",
                    (m.id, m.namespace, m.content, m.layer.value,
                     json.dumps(m.embedding) if m.embedding is not None else None,
                     json.dumps(m.metadata), m.importance, json.dumps(m.tags),
                     json.dumps(m.source_ids), m.created_at, m.access_count,
                     getattr(m, "last_recalled_at", None), getattr(m, "surprise_score", 0.0)),
                )

    def _candidates(self, namespace, layers, metadata_filter=None) -> List[Memory]:
        sql = f"SELECT {_COLS} FROM logica_mind_memory WHERE namespace=%s"
        params: list = [namespace]
        if layers:
            sql += " AND layer = ANY(%s)"
            params.append([l.value for l in layers])
        if metadata_filter:
            # typed jsonb containment (handles bool/number/null correctly, unlike ->> text)
            for k, v in metadata_filter.items():
                if isinstance(v, (list, tuple, set)):
                    vals = list(v)
                    if not vals:
                        sql += " AND FALSE"
                        continue
                    sql += " AND (" + " OR ".join(["metadata @> %s::jsonb"] * len(vals)) + ")"
                    params.extend(json.dumps({k: item}) for item in vals)
                else:
                    sql += " AND metadata @> %s::jsonb"
                    params.append(json.dumps({k: v}))
        sql += " ORDER BY created_at DESC LIMIT %s"
        params.append(self.max_candidates)
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            return [self._row_to_memory(r) for r in cur.fetchall()]

    def search(self, namespace, query_embedding, query_text, layers=None, limit=20, metadata_filter=None) -> List[SearchResult]:
        cands = apply_filter(self._candidates(namespace, layers, metadata_filter), metadata_filter)
        return rank(cands, query_embedding, query_text, limit)

    def get(self, namespace, memory_id) -> Optional[Memory]:
        with self._conn.cursor() as cur:
            cur.execute(f"SELECT {_COLS} FROM logica_mind_memory WHERE namespace=%s AND id=%s", (namespace, memory_id))
            r = cur.fetchone()
        return self._row_to_memory(r) if r else None

    def delete(self, namespace, memory_id) -> bool:
        with self._conn.cursor() as cur:
            cur.execute("DELETE FROM logica_mind_memory WHERE namespace=%s AND id=%s", (namespace, memory_id))
            return cur.rowcount > 0

    def all(self, namespace, layers=None, with_embeddings=True) -> List[Memory]:
        return self._candidates(namespace, layers)

    def namespaces(self) -> List[str]:
        with self._conn.cursor() as cur:
            cur.execute("SELECT DISTINCT namespace FROM logica_mind_memory ORDER BY namespace")
            return [r[0] for r in cur.fetchall()]

    def touch(self, namespace, ids) -> None:
        if not ids:
            return
        import datetime as _dt
        now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE logica_mind_memory SET access_count=access_count+1, last_recalled_at=%s "
                "WHERE namespace=%s AND id = ANY(%s)",
                (now, namespace, list(ids)),
            )

    def close(self) -> None:
        self._conn.close()
