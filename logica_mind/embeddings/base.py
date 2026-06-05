"""Embedder interface.

An embedder turns text into a fixed-length vector. The only hard requirement is
that `embed` returns one vector per input text, all of length `dim`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List


class Embedder(ABC):
    name: str = "embedder"

    @property
    @abstractmethod
    def dim(self) -> int:
        """Dimensionality of the vectors this embedder produces."""

    @abstractmethod
    def embed(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of texts (treated as documents to be stored)."""

    def embed_one(self, text: str) -> List[float]:
        return self.embed([text])[0]

    def embed_query(self, text: str) -> List[float]:
        """Embed a search query. Models that distinguish query vs document
        encoding (e.g. Voyage `input_type`) override this; others fall back to
        the document path, which is harmless."""
        return self.embed_one(text)
