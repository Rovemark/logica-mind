"""Offline, dependency-free embedder.

Uses the hashing trick: tokens are hashed into a fixed-dim vector with TF
weighting, then L2-normalized. This is *lexical*, not deep-semantic — but it is
deterministic, needs no API key, and makes the whole library work (and its tests
pass) out of the box. Swap in `VoyageEmbedder` / `OpenAIEmbedder` for real
semantic similarity.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import List

from .base import Embedder
from .._vector import l2_normalize

_TOKEN_RE = re.compile(r"[a-zà-ÿ0-9]{2,}", re.IGNORECASE)

# very small stopword set (en + pt) just to reduce noise
_STOP = {
    "the", "a", "an", "of", "to", "in", "is", "and", "or", "for", "on", "with",
    "que", "de", "da", "do", "e", "o", "a", "os", "as", "um", "uma", "para",
    "com", "no", "na", "em", "se", "por",
}


def _tokens(text: str) -> List[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text) if t.lower() not in _STOP]


class HashingEmbedder(Embedder):
    name = "hashing"

    def __init__(self, dim: int = 256, char_ngrams: int = 3):
        self._dim = dim
        self._n = char_ngrams

    @property
    def dim(self) -> int:
        return self._dim

    def _bucket(self, token: str) -> int:
        h = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        return int.from_bytes(h, "big") % self._dim

    def _features(self, text: str):
        """Word tokens (weight 1.0) + character n-grams (weight 0.5).

        The subword features let near-words match — "answer" vs "answers",
        "Portugues" vs "Portuguese" — which makes offline recall far more useful
        than plain bag-of-words."""
        feats = Counter()
        for tok in _tokens(text):
            feats["w:" + tok] += 1.0
            padded = "#" + tok + "#"
            for i in range(len(padded) - self._n + 1):
                feats["c:" + padded[i : i + self._n]] += 0.5
        return feats

    def embed(self, texts: List[str]) -> List[List[float]]:
        out: List[List[float]] = []
        for text in texts:
            vec = [0.0] * self._dim
            # non-negative weights → cosine behaves like TF similarity: ~0 for
            # unrelated text, higher as shared words/subwords increase
            for feat, weight in self._features(text).items():
                vec[self._bucket(feat)] += weight
            out.append(l2_normalize(vec))
        return out
