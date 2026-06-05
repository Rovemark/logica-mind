"""Reciprocal Rank Fusion (RRF) reranker.

Combines multiple ranking signals (similarity, importance, recency) by summing
1 / (k + rank) across each — robust to scale differences between signals.
"""
from __future__ import annotations

from typing import List

from ..types import SearchResult
from .base import Reranker


class RRFReranker(Reranker):
    name = "rrf"

    def __init__(self, k: int = 60):
        self.k = k

    def rerank(self, query, results, top_k, query_embedding=None) -> List[SearchResult]:
        if not results:
            return []

        def rankmap(keyfn):
            # competition ranking: items with an equal key share the same rank (so
            # genuine ties get identical 1/(k+rank) contributions instead of being
            # split by upstream emission order, which would defeat rank fusion).
            order = sorted(range(len(results)), key=lambda i: keyfn(results[i]), reverse=True)
            ranks, prev_key, cur_rank = {}, None, 0
            for pos, idx in enumerate(order):
                kv = keyfn(results[idx])
                if pos == 0 or kv != prev_key:
                    cur_rank = pos
                ranks[idx] = cur_rank
                prev_key = kv
            return ranks

        sim = rankmap(lambda r: r.components.get("similarity", r.score))
        imp = rankmap(lambda r: r.memory.importance)
        rec = rankmap(lambda r: r.components.get("recency", 0.0))
        for i, r in enumerate(results):
            rrf = 1.0 / (self.k + sim[i] + 1) + 1.0 / (self.k + imp[i] + 1) + 1.0 / (self.k + rec[i] + 1)
            r.score = rrf
            r.components = dict(r.components or {})
            r.components["rrf"] = round(rrf, 6)
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]
