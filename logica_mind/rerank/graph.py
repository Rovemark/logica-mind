"""Graph-aware rerankers (Zep-style).

NodeDistanceReranker  — lift memories that mention entities close (in the
                        knowledge graph) to entities named in the query.
EpisodeMentionReranker — lift memories that have been recalled often (a proxy for
                        episode-mention frequency).
"""
from __future__ import annotations

from typing import List

from ..types import SearchResult
from ..stores.base import _tokset, entity_tokset
from .base import Reranker


class NodeDistanceReranker(Reranker):
    name = "node-distance"

    def __init__(self, graph, max_hops: int = 2, weight: float = 0.2):
        self.graph = graph
        self.max_hops = max_hops
        self.weight = weight

    def rerank(self, query, results, top_k, query_embedding=None) -> List[SearchResult]:
        qtoks = _tokset(query)
        # gate entities the same way core's entity_boost does (no 'ai'/short/stopword)
        q_ents = [n for n in self.graph.entity_names()
                  if (et := entity_tokset(n)) and et <= qtoks]
        if not q_ents:
            return results[:top_k]

        # min graph distance of every reachable node from any query entity
        close = {}
        for qe in q_ents:
            for node, lvl in self.graph.bfs(qe, depth=self.max_hops)["levels"].items():
                close[node] = min(close.get(node, 99), lvl)

        for r in results:
            ctoks = _tokset(r.memory.content)
            dists = [close[n] for n in close if (et := entity_tokset(n)) and et <= ctoks]
            if dists:
                d = min(dists)
                r.score += self.weight / (1 + d)
                r.components = dict(r.components or {})
                r.components["graph_distance"] = d
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]


class EpisodeMentionReranker(Reranker):
    name = "episode-mention"

    def __init__(self, weight: float = 0.05, cap: int = 5):
        self.weight = weight
        self.cap = cap

    def rerank(self, query, results, top_k, query_embedding=None) -> List[SearchResult]:
        for r in results:
            mentions = min(self.cap, r.memory.access_count)
            if mentions:
                r.score += self.weight * mentions
                r.components = dict(r.components or {})
                r.components["mentions"] = mentions
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]
