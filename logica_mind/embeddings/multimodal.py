"""Multimodal embedder — text + images in one vector space (Voyage / Zep-style).

Requires `logica-mind[voyage]` + VOYAGE_API_KEY. `embed(texts)` works like any
text embedder (so it drops into the normal pipeline); `embed_multimodal(inputs)`
takes a list of documents where each document is a list of content parts. Per the
voyageai `multimodal_embed` SDK contract, those parts must be plain text `str`
and/or `PIL.Image.Image` objects (e.g. `[["a caption", pil_image]]`) — NOT
OpenAI-style `{"type":"image_url",...}` dicts, which the list form rejects. To
embed an image from a URL/base64, load it into a `PIL.Image` first.
"""
from __future__ import annotations

import os
from typing import Any, List, Optional

from .base import Embedder


class VoyageMultimodalEmbedder(Embedder):
    name = "voyage-multimodal"

    def __init__(self, model: str = "voyage-multimodal-3", api_key: Optional[str] = None):
        self.model = model
        self._api_key = api_key or os.environ.get("VOYAGE_API_KEY")
        self._dim = 1024
        self._client = None

    def _ensure(self):
        if self._client is not None:
            return
        if not self._api_key:
            raise RuntimeError("VoyageMultimodalEmbedder needs VOYAGE_API_KEY.")
        try:
            import voyageai  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("voyageai not installed. Run: pip install 'logica-mind[voyage]'") from e
        self._client = voyageai.Client(api_key=self._api_key)

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts: List[str]) -> List[List[float]]:
        # text-only path: each input is a single text "document"
        return self.embed_multimodal([[t] for t in texts])

    def embed_multimodal(self, inputs: List[List[Any]], input_type: str = "document") -> List[List[float]]:
        """Each input is a list of content parts (text str and/or images)."""
        self._ensure()
        resp = self._client.multimodal_embed(inputs=inputs, model=self.model, input_type=input_type)
        vecs = [list(v) for v in resp.embeddings]
        if vecs and len(vecs[0]) != self._dim:
            self._dim = len(vecs[0])
        return vecs

    def embed_query(self, text: str) -> List[float]:
        return self.embed_multimodal([[text]], input_type="query")[0]
