"""MMR reranker — Maximal Marginal Relevance (offline, no API).

Balances relevance to the query against diversity among the chosen results, so
the top-k isn't three paraphrases of the same fact. Needs embeddings: the query
embedding plus each candidate's embedding. If those are missing it returns the
input order unchanged (safe no-op).

    score(d) = λ · sim(query, d) − (1 − λ) · max sim(d, already_selected)
"""
from __future__ import annotations

from typing import List

from ..types import SearchResult
from .._vector import cosine
from .base import Reranker


class MMRReranker(Reranker):
    name = "mmr"

    def __init__(self, lambda_: float = 0.7):
        self.lmbda = lambda_

    def rerank(self, query, results, top_k, query_embedding=None) -> List[SearchResult]:
        usable = [r for r in results if r.memory.embedding]
        if query_embedding is None or len(usable) < 2:
            return results[:top_k]

        rel = {id(r): max(0.0, cosine(query_embedding, r.memory.embedding)) for r in usable}
        selected: List[SearchResult] = []
        pool = list(usable)

        while pool and len(selected) < top_k:
            best, best_score = None, -1e9
            for r in pool:
                if selected:
                    div = max(
                        cosine(r.memory.embedding, s.memory.embedding) for s in selected
                    )
                else:
                    div = 0.0
                mmr = self.lmbda * rel[id(r)] - (1 - self.lmbda) * div
                if mmr > best_score:
                    best, best_score = r, mmr
            # the reranker owns .score (like Voyage does with relevance) so the
            # returned order is monotonic in .score and callers/UI stay consistent
            best.score = best_score
            best.components = dict(best.components or {})
            best.components["mmr"] = round(best_score, 4)
            best.components["relevance"] = round(rel[id(best)], 4)
            selected.append(best)
            pool.remove(best)

        # if any candidates had no embedding, append them after the diversified set
        if len(selected) < top_k:
            for r in results:
                if r not in selected:
                    selected.append(r)
                    if len(selected) >= top_k:
                        break
        return selected[:top_k]
