"""Voyage AI embedder (optional).

Requires `pip install logica-mind[voyage]` and a VOYAGE_API_KEY env var.
Lazy-imports voyageai so the core stays dependency-free.

Supports the features that matter for retrieval quality:
- `input_type` query vs document (queries and documents are encoded differently)
- `output_dimension` (Matryoshka — trade size for quality: 256/512/1024/2048)
- transparent retry with exponential backoff on rate limits / transient errors

`output_dtype` is currently restricted to "float": the rest of the pipeline
(pure-Python cosine, the dimension guard, the pgvector column) assumes float
vectors. int8/binary quantization needs explicit de-quantization and a fixed
logical dimension — it's on the roadmap, not active.
"""
from __future__ import annotations

import os
import time
from typing import List, Optional

from .base import Embedder

# default dims per Voyage model (used before the first live call resolves it)
_MODEL_DIMS = {
    "voyage-4": 1024, "voyage-4-large": 1024, "voyage-4-lite": 1024, "voyage-4-nano": 512,
    "voyage-3": 1024, "voyage-3-large": 1024, "voyage-3-lite": 512,
    "voyage-finance-2": 1024, "voyage-law-2": 1024, "voyage-code-3": 1024,
    "voyage-multilingual-2": 1024,
}


class VoyageEmbedder(Embedder):
    name = "voyage"

    def __init__(
        self,
        model: str = "voyage-3-lite",
        api_key: Optional[str] = None,
        output_dimension: Optional[int] = None,
        output_dtype: str = "float",
        max_retries: int = 4,
        base_backoff: float = 2.0,
        context_model: str = "voyage-context-3",
    ):
        if output_dtype != "float":
            raise ValueError(
                f"output_dtype={output_dtype!r} is not supported yet: the pipeline "
                f"(pure-Python cosine, dimension guard, pgvector column) assumes "
                f"float vectors. Quantized int8/binary output would corrupt the "
                f"logical dimension and similarity. Use 'float'."
            )
        self.model = model
        self.context_model = context_model
        self.output_dimension = output_dimension
        self.output_dtype = output_dtype
        self.max_retries = max_retries
        self.base_backoff = base_backoff
        self._api_key = api_key or os.environ.get("VOYAGE_API_KEY")
        self._dim = output_dimension or _MODEL_DIMS.get(model, 1024)
        self._client = None

    def _ensure_client(self):
        if self._client is not None:
            return
        if not self._api_key:
            raise RuntimeError(
                "VoyageEmbedder needs VOYAGE_API_KEY (env var or api_key=...)."
            )
        try:
            import voyageai  # type: ignore
        except ImportError as e:  # pragma: no cover - import guard
            raise RuntimeError(
                "voyageai not installed. Run: pip install 'logica-mind[voyage]'"
            ) from e
        self._client = voyageai.Client(api_key=self._api_key)

    @property
    def dim(self) -> int:
        return self._dim

    def _embed(self, texts: List[str], input_type: str) -> List[List[float]]:
        self._ensure_client()
        kwargs = {"model": self.model, "input_type": input_type}
        if self.output_dimension:
            kwargs["output_dimension"] = self.output_dimension
        if self.output_dtype and self.output_dtype != "float":
            kwargs["output_dtype"] = self.output_dtype

        last_err = None
        for attempt in range(self.max_retries):
            try:
                resp = self._client.embed(texts, **kwargs)
                vecs = [list(v) for v in resp.embeddings]
                if vecs and len(vecs[0]) != self._dim:
                    self._dim = len(vecs[0])
                return vecs
            except Exception as e:  # rate limit / transient → backoff and retry
                last_err = e
                if attempt == self.max_retries - 1:
                    break
                # exponential backoff with light jitter (deterministic-ish)
                delay = self.base_backoff * (2 ** attempt)
                time.sleep(min(delay, 30.0))
        raise RuntimeError(f"VoyageEmbedder failed after {self.max_retries} attempts: {last_err}")

    def embed(self, texts: List[str]) -> List[List[float]]:
        return self._embed(texts, input_type="document")

    def embed_query(self, text: str) -> List[float]:
        return self._embed([text], input_type="query")[0]

    def embed_contextualized(self, chunks: List[str], input_type: str = "document") -> List[List[float]]:
        """voyage-context-3: embed the chunks of ONE document together, so each
        chunk's vector reflects its surrounding context (e.g. 'he raised it to
        $4M' keeps its referents). Returns one vector per chunk. Falls back to the
        independent-chunk path if the SDK lacks contextualized_embed."""
        self._ensure_client()
        chunks = list(chunks)
        if not chunks:
            return []
        fn = getattr(self._client, "contextualized_embed", None)
        if fn is None:                                   # older SDK → no context model
            return self._embed(chunks, input_type=input_type)
        last_err = None
        for attempt in range(self.max_retries):
            try:
                resp = fn(inputs=[chunks], model=self.context_model, input_type=input_type)
                vecs = [list(v) for v in resp.results[0].embeddings]
                if vecs and len(vecs[0]) != self._dim:
                    self._dim = len(vecs[0])
                return vecs
            except Exception as e:
                last_err = e
                if attempt == self.max_retries - 1:
                    break
                time.sleep(min(self.base_backoff * (2 ** attempt), 30.0))
        raise RuntimeError(f"VoyageEmbedder.embed_contextualized failed after {self.max_retries}: {last_err}")
