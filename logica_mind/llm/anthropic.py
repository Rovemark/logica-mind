"""Anthropic (Claude) chat LLM. Requires `logica-mind[anthropic]` + ANTHROPIC_API_KEY."""
from __future__ import annotations

import os
from typing import Optional

from .base import LLM


class AnthropicLLM(LLM):
    name = "anthropic"

    def __init__(self, model: str = "claude-haiku-4-5", api_key: Optional[str] = None,
                 temperature: float = 0.2, max_tokens: int = 2048):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._client = None

    def _ensure(self):
        if self._client is not None:
            return
        if not self._api_key:
            raise RuntimeError("AnthropicLLM needs ANTHROPIC_API_KEY (env var or api_key=...).")
        try:
            from anthropic import Anthropic  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("anthropic not installed. Run: pip install 'logica-mind[anthropic]'") from e
        self._client = Anthropic(api_key=self._api_key)

    def complete(self, prompt: str, system: Optional[str] = None) -> str:
        self._ensure()
        kwargs = {
            "model": self.model, "max_tokens": self.max_tokens, "temperature": self.temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        resp = self._client.messages.create(**kwargs)
        return "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", None) == "text").strip()
