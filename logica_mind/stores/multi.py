"""MultiStore — write to several backends, merge on read.

This is the "multi-armazém" switch: turn on SQLite + Obsidian + Supabase at once.
Writes fan out to every store. Reads query each store, merge by id, and keep the
best score. The first store is treated as primary for get()/delete() fast paths,
but delete() is attempted on all so nothing is orphaned.
"""
from __future__ import annotations

import sys

from typing import Dict, List, Optional

from ..types import Memory, SearchResult
from .base import Store


class MultiStore(Store):
    name = "multi"

    def __init__(self, stores: List[Store]):
        if not stores:
            raise ValueError("MultiStore needs at least one store.")
        self.stores = stores

    def add(self, memories: List[Memory]) -> None:
        for s in self.stores:
            try:
                s.add(memories)
            except Exception as e:  # one backend down shouldn't lose the write
                print(f"[logica-mind] MultiStore.add: {s.name} failed: {e}", file=sys.stderr)

    def search(self, namespace, query_embedding, query_text, layers=None, limit=20, metadata_filter=None) -> List[SearchResult]:
        merged: Dict[str, SearchResult] = {}
        emb_by_id: Dict[str, list] = {}
        for s in self.stores:
            try:
                for r in s.search(namespace, query_embedding, query_text, layers, limit, metadata_filter):
                    mid = r.memory.id
                    if r.memory.embedding and mid not in emb_by_id:
                        emb_by_id[mid] = r.memory.embedding
                    prev = merged.get(mid)
                    if prev is None or r.score > prev.score:
                        merged[mid] = r
            except Exception as e:
                print(f"[logica-mind] MultiStore.search: {s.name} failed: {e}", file=sys.stderr)
        results = sorted(merged.values(), key=lambda r: r.score, reverse=True)[:limit]

        # A winner can come from a vector-less store (e.g. Obsidian's lexical hit
        # outscoring the vector store). Back-fill its embedding so downstream
        # rerankers (MMR) don't silently drop it for lacking a vector.
        for r in results:
            if r.memory.embedding:
                continue
            emb = emb_by_id.get(r.memory.id)
            if emb is None:
                for s in self.stores:
                    try:
                        m = s.get(namespace, r.memory.id)
                    except Exception:
                        m = None
                    if m and m.embedding:
                        emb = m.embedding
                        break
            if emb:
                r.memory.embedding = emb
        return results

    def get(self, namespace: str, memory_id: str) -> Optional[Memory]:
        for s in self.stores:
            m = s.get(namespace, memory_id)
            if m:
                return m
        return None

    def delete(self, namespace: str, memory_id: str) -> bool:
        deleted = False
        for s in self.stores:
            try:
                deleted = s.delete(namespace, memory_id) or deleted
            except Exception as e:
                print(f"[logica-mind] MultiStore.delete: {s.name} failed: {e}", file=sys.stderr)
        return deleted

    def all(self, namespace, layers=None, with_embeddings=True) -> List[Memory]:
        seen: Dict[str, Memory] = {}
        for s in self.stores:
            try:
                rows = s.all(namespace, layers, with_embeddings=with_embeddings)
            except TypeError:
                rows = s.all(namespace, layers)   # store predates the kwarg
            for m in rows:
                seen.setdefault(m.id, m)
        return list(seen.values())

    def namespaces(self) -> List[str]:
        out = set()
        for s in self.stores:
            try:
                out.update(s.namespaces())
            except Exception:
                pass
        return sorted(out)

    def timerange(self, namespace, layers=None):
        # fold each child's cheap MIN/MAX instead of materializing rows via all()
        lo = hi = None
        for s in self.stores:
            try:
                a, b = s.timerange(namespace, layers)
            except Exception:
                continue
            if a and (lo is None or a < lo):
                lo = a
            if b and (hi is None or b > hi):
                hi = b
        return (lo, hi)

    def delete_layers(self, namespace, layers=None) -> int:
        # delete from every backend; report the max removed by any one of them
        # (they hold the same logical set, so summing would double-count)
        counts = []
        for s in self.stores:
            try:
                counts.append(s.delete_layers(namespace, layers))
            except Exception as e:
                print(f"[logica-mind] MultiStore.delete_layers: {s.name} failed: {e}", file=sys.stderr)
        return max(counts) if counts else 0

    def touch(self, namespace: str, ids: List[str]) -> None:
        # each child's touch is update-only, so this never inserts into a backend
        # that didn't already hold the memory (no write amplification / leakage)
        for s in self.stores:
            try:
                s.touch(namespace, ids)
            except Exception:
                pass

    # Fast read aggregations — delegate to the PRIMARY store that supports them
    # (the children hold the same logical set; summing would double-count). The
    # primary is SQLite, which answers these with one SQL query instead of
    # materializing rows in every backend.
    def bucket_counts(self):
        for s in self.stores:
            if hasattr(s, "bucket_counts"):
                return s.bucket_counts()
        out = {}
        for ns in self.namespaces():
            out[ns] = {m.layer.value: 0 for m in []}
        return out

    def day_counts(self, namespace=None, exclude_layers=None):
        for s in self.stores:
            if hasattr(s, "day_counts"):
                return s.day_counts(namespace, exclude_layers)
        return {}

    def day(self, namespace=None, date=None, layers=None, with_embeddings=False):
        for s in self.stores:
            if hasattr(s, "day"):
                return s.day(namespace, date, layers, with_embeddings)
        return [m for m in self.all(namespace, layers, with_embeddings)
                if (m.created_at or "").startswith(date or "")]

    def dimension_counts(self, namespace=None):
        for s in self.stores:
            if hasattr(s, "dimension_counts"):
                return s.dimension_counts(namespace)
        return {}, 0

    def filter_memories(self, namespace=None, layers=None, dimension=None, category=None,
                        session=None, limit=200, offset=0, with_embeddings=False):
        for s in self.stores:
            if hasattr(s, "filter_memories"):
                return s.filter_memories(namespace, layers, dimension, category,
                                         session, limit, offset, with_embeddings)
        return []

    def mentions(self, namespace, name, limit=0, with_embeddings=False):
        for s in self.stores:
            if hasattr(s, "mentions"):
                return s.mentions(namespace, name, limit=limit, with_embeddings=with_embeddings)
        return self.all(namespace, with_embeddings=with_embeddings)   # correct (slow) fallback

    def tagged(self, namespace=None, key="channel"):
        for s in self.stores:
            if hasattr(s, "tagged"):
                return s.tagged(namespace, key)
        return []

    def dimensioned(self, namespace=None):
        for s in self.stores:
            if hasattr(s, "dimensioned"):
                return s.dimensioned(namespace)
        return []

    def page(self, namespace, layers=None, limit=100, offset=0):
        for s in self.stores:
            if hasattr(s, "page"):
                return s.page(namespace, layers, limit, offset)
        return self.all(namespace, layers)[offset:offset + limit]

    def close(self) -> None:
        for s in self.stores:
            s.close()
