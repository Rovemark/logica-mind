"""Voyage reranker (rerank-2 / rerank-2-lite) — cross-encoder relevance.

A cross-encoder reads each (query, document) pair jointly, so it judges relevance
far more accurately than comparing independent embeddings. This is the highest-
quality reranking option. Requires `logica-mind[voyage]` + VOYAGE_API_KEY.
"""
from __future__ import annotations

import sys

import os
import time
from typing import List, Optional

from ..types import SearchResult
from .base import Reranker


class VoyageReranker(Reranker):
    name = "voyage-rerank"

    def __init__(
        self,
        model: str = "rerank-2-lite",
        api_key: Optional[str] = None,
        max_retries: int = 4,
        base_backoff: float = 2.0,
    ):
        self.model = model
        self.max_retries = max_retries
        self.base_backoff = base_backoff
        self._api_key = api_key or os.environ.get("VOYAGE_API_KEY")
        self._client = None

    def _ensure(self):
        if self._client is not None:
            return
        if not self._api_key:
            raise RuntimeError("VoyageReranker needs VOYAGE_API_KEY (env var or api_key=...).")
        try:
            import voyageai  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("voyageai not installed. Run: pip install 'logica-mind[voyage]'") from e
        self._client = voyageai.Client(api_key=self._api_key)

    def rerank(self, query, results, top_k, query_embedding=None) -> List[SearchResult]:
        if not results:
            return []
        try:
            self._ensure()
        except RuntimeError as e:
            # no key / lib → don't crash recall, keep the incoming order
            print(f"[logica-mind] VoyageReranker disabled ({e})", file=sys.stderr)
            return results[:top_k]

        docs = [r.memory.content for r in results]
        last = None
        for attempt in range(self.max_retries):
            try:
                resp = self._client.rerank(query, docs, model=self.model, top_k=top_k)
                out: List[SearchResult] = []
                for item in resp.results:
                    r = results[item.index]
                    r.score = float(item.relevance_score)
                    r.components = dict(r.components or {})
                    r.components["rerank"] = round(float(item.relevance_score), 4)
                    out.append(r)
                return out
            except Exception as e:
                last = e
                if attempt == self.max_retries - 1:
                    break
                time.sleep(min(self.base_backoff * (2 ** attempt), 30.0))
        print(f"[logica-mind] VoyageReranker failed, keeping prior order ({last})", file=sys.stderr)
        return results[:top_k]
