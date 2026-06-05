"""Local embedder (optional: `pip install sentence-transformers`).

Real semantic embeddings with NO API key and NO network — runs a small
transformer on-device. Heavier than the hashing default, but gives true semantic
recall offline. Default model: all-MiniLM-L6-v2 (384 dims).
"""
from __future__ import annotations

from typing import List, Optional

from .base import Embedder


class LocalEmbedder(Embedder):
    name = "local"

    def __init__(self, model: str = "all-MiniLM-L6-v2", dim: Optional[int] = None):
        self.model_name = model
        self._dim = dim or 384
        self._model = None

    def _ensure(self):
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "sentence-transformers not installed. Run: pip install sentence-transformers"
            ) from e
        self._model = SentenceTransformer(self.model_name)
        try:
            self._dim = self._model.get_sentence_embedding_dimension()
        except Exception:
            pass

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts: List[str]) -> List[List[float]]:
        self._ensure()
        vecs = self._model.encode(list(texts), normalize_embeddings=True)
        return [list(map(float, v)) for v in vecs]
