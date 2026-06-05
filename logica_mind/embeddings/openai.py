"""OpenAI embedder (optional).

Requires `pip install logica-mind[openai]` and an OPENAI_API_KEY env var.
Supports the `dimensions` parameter so you can pin output size (handy for
matching an existing vector column, e.g. 1024).
"""
from __future__ import annotations

import os
from typing import List, Optional

from .base import Embedder


class OpenAIEmbedder(Embedder):
    name = "openai"

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        dimensions: Optional[int] = None,
        api_key: Optional[str] = None,
    ):
        self.model = model
        self._requested_dim = dimensions
        self._dim = dimensions or 1536
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self._client = None

    def _ensure_client(self):
        if self._client is not None:
            return
        if not self._api_key:
            raise RuntimeError(
                "OpenAIEmbedder needs OPENAI_API_KEY (env var or api_key=...)."
            )
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as e:  # pragma: no cover - import guard
            raise RuntimeError(
                "openai not installed. Run: pip install 'logica-mind[openai]'"
            ) from e
        self._client = OpenAI(api_key=self._api_key)

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts: List[str]) -> List[List[float]]:
        self._ensure_client()
        kwargs = {"model": self.model, "input": texts}
        if self._requested_dim:
            kwargs["dimensions"] = self._requested_dim
        resp = self._client.embeddings.create(**kwargs)
        vecs = [d.embedding for d in resp.data]
        if vecs:
            self._dim = len(vecs[0])
        return [list(v) for v in vecs]
