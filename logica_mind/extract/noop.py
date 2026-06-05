"""No-LLM extractor: store the text as a single fact, as-is.

This is the default. It keeps `remember()` fully functional without an LLM —
near-duplicate suppression still happens later in the core via embedding cosine.
"""
from __future__ import annotations

from typing import List

from ..types import Memory
from .base import Extractor, Fact, ExtractOp


class NoopExtractor(Extractor):
    name = "noop"

    def extract(self, text: str, existing: List[Memory]) -> List[Fact]:
        text = (text or "").strip()
        if not text:
            return []
        return [Fact(content=text, op=ExtractOp.ADD)]
