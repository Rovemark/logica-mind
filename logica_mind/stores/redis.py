"""Redis store (optional: `pip install redis`).

Each memory is a JSON value at `lm:{namespace}:{id}`; a per-namespace set indexes
ids and a global set tracks namespaces. Search loads a namespace and ranks
in-process — best for small/fast working sets, not large-scale vector search.
"""
from __future__ import annotations

import json
import sys
from typing import List, Optional

from ..types import Memory, SearchResult, now_iso
from .base import Store, rank, apply_filter


class RedisStore(Store):
    name = "redis"

    def __init__(self, url: Optional[str] = None, prefix: str = "lm"):
        try:
            import redis  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("redis not installed. Run: pip install redis") from e
        import os
        self.prefix = prefix
        self._r = redis.Redis.from_url(url or os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
                                       decode_responses=True)

    def _key(self, ns, mid):
        return f"{self.prefix}:{ns}:{mid}"

    def _ns_set(self, ns):
        return f"{self.prefix}:ns:{ns}"

    def _ns_index(self):
        return f"{self.prefix}:namespaces"

    def add(self, memories: List[Memory]) -> None:
        pipe = self._r.pipeline()
        for m in memories:
            pipe.set(self._key(m.namespace, m.id), json.dumps(m.to_dict()))
            pipe.sadd(self._ns_set(m.namespace), m.id)
            pipe.sadd(self._ns_index(), m.namespace)
        pipe.execute()

    def _all_raw(self, namespace) -> List[Memory]:
        ids = list(self._r.smembers(self._ns_set(namespace)))
        if not ids:
            return []
        vals = self._r.mget([self._key(namespace, i) for i in ids])
        out, orphans = [], []
        for i, v in zip(ids, vals):
            if not v:
                orphans.append(i)                       # indexed id with no value
                continue
            try:
                out.append(Memory.from_dict(json.loads(v)))
            except Exception as e:
                print(f"[logica-mind] redis: skipping unreadable {self._key(namespace, i)}: {e}", file=sys.stderr)
                orphans.append(i)
        if orphans:
            self._r.srem(self._ns_set(namespace), *orphans)   # keep the index consistent
        return out

    def _candidates(self, namespace, layers) -> List[Memory]:
        mems = self._all_raw(namespace)
        if layers:
            wanted = {l for l in layers}
            mems = [m for m in mems if m.layer in wanted]
        return mems

    def search(self, namespace, query_embedding, query_text, layers=None, limit=20, metadata_filter=None) -> List[SearchResult]:
        cands = apply_filter(self._candidates(namespace, layers), metadata_filter)
        return rank(cands, query_embedding, query_text, limit)

    def get(self, namespace, memory_id) -> Optional[Memory]:
        v = self._r.get(self._key(namespace, memory_id))
        return Memory.from_dict(json.loads(v)) if v else None

    def delete(self, namespace, memory_id) -> bool:
        n = self._r.delete(self._key(namespace, memory_id))
        self._r.srem(self._ns_set(namespace), memory_id)
        return n > 0

    def all(self, namespace, layers=None, with_embeddings=True) -> List[Memory]:
        return self._candidates(namespace, layers)

    def namespaces(self) -> List[str]:
        return sorted(self._r.smembers(self._ns_index()))

    def touch(self, namespace, ids) -> None:
        stamp = now_iso()
        for mid in ids:
            m = self.get(namespace, mid)
            if m:
                m.access_count += 1
                m.last_recalled_at = stamp
                self._r.set(self._key(namespace, mid), json.dumps(m.to_dict()))
