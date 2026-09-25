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

    @staticmethod
    def _bigrams(text):
        t = "".join(c if c.isalnum() else " " for c in (text or "").lower())
        toks = "  " + " ".join(t.split()) + "  "
        return {toks[i:i + 2] for i in range(len(toks) - 1)}

    def _rerank_lexical(self, results, top_k):
        """Diversity without embeddings: penalize a candidate by its max bigram
        Jaccard overlap with what's already chosen — keeps the keyless/hashing
        path from returning three phrasings of the same fact."""
        grams = {id(r): self._bigrams(r.memory.content) for r in results}
        n = max(1, len(results) - 1)
        ranks = {id(r): i for i, r in enumerate(results)}      # input order = relevance proxy
        selected: List[SearchResult] = []
        pool = list(results)
        while pool and len(selected) < top_k:
            best, best_score = None, -1e9
            for r in pool:
                rel = 1.0 - ranks[id(r)] / n
                if selected:
                    g = grams[id(r)]
                    div = max(len(g & grams[id(s)]) / max(1, len(g | grams[id(s)])) for s in selected)
                else:
                    div = 0.0
                score = self.lmbda * rel - (1 - self.lmbda) * div
                if score > best_score:
                    best, best_score = r, score
            selected.append(best)
            pool.remove(best)
        return selected[:top_k]

    def rerank(self, query, results, top_k, query_embedding=None) -> List[SearchResult]:
        usable = [r for r in results if r.memory.embedding]
        # no query vector or too few embedded candidates → fall back to a lexical
        # (bigram-Jaccard) MMR instead of a plain passthrough, so the keyless path
        # still gets de-duplicated
        if query_embedding is None or len(usable) < 2:
            return self._rerank_lexical(results, top_k) if len(results) > 1 else results[:top_k]

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
