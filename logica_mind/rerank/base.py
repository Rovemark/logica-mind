"""Reranker interface — the final relevance pass over recall candidates.

A reranker takes the query and a candidate set (already retrieved) and reorders
them for relevance/diversity. This is the single biggest lever on recall quality:
embedding retrieval is recall-oriented and noisy; a cross-encoder reranker
(Voyage rerank-2) or a diversity reranker (MMR) sharpens the top results.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from ..types import SearchResult


class Reranker(ABC):
    name: str = "reranker"

    @abstractmethod
    def rerank(
        self,
        query: str,
        results: List[SearchResult],
        top_k: int,
        query_embedding: Optional[List[float]] = None,
    ) -> List[SearchResult]:
        """Reorder `results` for `query` and return the top_k."""
