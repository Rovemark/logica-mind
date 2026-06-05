"""LLM interface — powers extraction and the dialectic user model.

The core never requires an LLM: the default `NullLLM` makes the higher layers
fall back to non-LLM behavior. Provide a real one to unlock automatic extraction
and dialectic user modeling.
"""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any, Optional


class LLM(ABC):
    name: str = "llm"
    available: bool = True

    @abstractmethod
    def complete(self, prompt: str, system: Optional[str] = None) -> str:
        ...

    def complete_json(self, prompt: str, system: Optional[str] = None) -> Any:
        """Complete and best-effort parse a JSON object/array from the reply."""
        raw = self.complete(prompt, system=system)
        return extract_json(raw)


class NullLLM(LLM):
    """No-op LLM. Signals callers to use their non-LLM fallback path."""

    name = "null"
    available = False

    def complete(self, prompt: str, system: Optional[str] = None) -> str:
        return ""

    def complete_json(self, prompt: str, system: Optional[str] = None) -> Any:
        return None


def extract_json(text: str) -> Any:
    """Pull the first JSON object/array out of an LLM reply, or None."""
    if not text:
        return None
    text = text.strip()
    # strip ```json fences
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # fall back to the first {...} or [...] span
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if 0 <= start < end:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    return None
