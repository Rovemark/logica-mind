"""In-memory store — for tests and ephemeral sessions. No persistence."""
from __future__ import annotations

from typing import Dict, List, Optional

from ..types import Memory, MemoryLayer, SearchResult, now_iso
from .base import Store, rank, apply_filter


class InMemoryStore(Store):
    name = "memory"

    def __init__(self):
        # namespace -> {id -> Memory}
        self._data: Dict[str, Dict[str, Memory]] = {}

    def add(self, memories: List[Memory]) -> None:
        for m in memories:
            self._data.setdefault(m.namespace, {})[m.id] = m

    def _candidates(self, namespace: str, layers: Optional[List[MemoryLayer]]) -> List[Memory]:
        items = list(self._data.get(namespace, {}).values())
        if layers:
            wanted = set(layers)
            items = [m for m in items if m.layer in wanted]
        return items

    def search(self, namespace, query_embedding, query_text, layers=None, limit=20, metadata_filter=None) -> List[SearchResult]:
        cands = apply_filter(self._candidates(namespace, layers), metadata_filter)
        return rank(cands, query_embedding, query_text, limit)

    def get(self, namespace: str, memory_id: str) -> Optional[Memory]:
        return self._data.get(namespace, {}).get(memory_id)

    def delete(self, namespace: str, memory_id: str) -> bool:
        return self._data.get(namespace, {}).pop(memory_id, None) is not None

    def all(self, namespace, layers=None) -> List[Memory]:
        return self._candidates(namespace, layers)

    def namespaces(self) -> List[str]:
        return sorted(self._data.keys())

    def touch(self, namespace: str, ids: List[str]) -> None:
        ns = self._data.get(namespace, {})
        stamp = now_iso()
        for mid in ids:
            m = ns.get(mid)
            if m:
                m.access_count += 1
                m.last_recalled_at = stamp
