"""BatchedEmbedder — rate-limit-safe wrapper around any embedder.

Wrap a provider that bills/rate-limits per call (Voyage, OpenAI) to:
  - chunk large inputs into `batch_size` requests,
  - enforce a minimum interval between requests (simple cross-call throttle),
  - retry transient failures with exponential backoff.

    emb = BatchedEmbedder(VoyageEmbedder(), batch_size=128, min_interval=0.4)

Embedding one item at a time can trigger provider rate limits (e.g. Voyage 429 storms);
per call with no throttle melts under load — this is the cheap insurance.
"""
from __future__ import annotations

import time
from typing import List

from .base import Embedder


class BatchedEmbedder(Embedder):
    name = "batched"

    def __init__(
        self,
        inner: Embedder,
        batch_size: int = 128,
        min_interval: float = 0.0,
        max_retries: int = 4,
        base_backoff: float = 1.0,
    ):
        self.inner = inner
        self.batch_size = max(1, batch_size)
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.base_backoff = base_backoff
        self._last_call = 0.0

    @property
    def dim(self) -> int:
        return self.inner.dim

    def _throttle(self):
        if self.min_interval <= 0:
            return
        wait = self.min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        # NOTE: _last_call is stamped after the call succeeds (see _call), so the
        # interval is the gap between the END of one request and the START of the
        # next — robust even when a request takes longer than min_interval.

    def _call(self, fn, *args):
        last = None
        for attempt in range(self.max_retries):
            try:
                self._throttle()
                result = fn(*args)
                self._last_call = time.monotonic()  # stamp only on success
                return result
            except Exception as e:
                last = e
                if attempt == self.max_retries - 1:
                    break
                time.sleep(min(self.base_backoff * (2 ** attempt), 30.0))
        raise RuntimeError(f"BatchedEmbedder failed after {self.max_retries} attempts: {last}")

    def embed(self, texts: List[str]) -> List[List[float]]:
        out: List[List[float]] = []
        for i in range(0, len(texts), self.batch_size):
            chunk = texts[i : i + self.batch_size]
            out.extend(self._call(self.inner.embed, chunk))
        return out

    def embed_query(self, text: str) -> List[float]:
        return self._call(self.inner.embed_query, text)
