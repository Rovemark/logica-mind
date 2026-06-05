"""OpenAI chat LLM (optional). Requires `logica-mind[openai]` + OPENAI_API_KEY."""
from __future__ import annotations

import os
from typing import Optional

from .base import LLM


class OpenAILLM(LLM):
    name = "openai"

    def __init__(self, model: str = "gpt-4o-mini", api_key: Optional[str] = None, temperature: float = 0.2):
        self.model = model
        self.temperature = temperature
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self._client = None

    def _ensure(self):
        if self._client is not None:
            return
        if not self._api_key:
            raise RuntimeError("OpenAILLM needs OPENAI_API_KEY (env var or api_key=...).")
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("openai not installed. Run: pip install 'logica-mind[openai]'") from e
        self._client = OpenAI(api_key=self._api_key)

    def complete(self, prompt: str, system: Optional[str] = None) -> str:
        self._ensure()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = self._client.chat.completions.create(
            model=self.model, messages=messages, temperature=self.temperature
        )
        return resp.choices[0].message.content or ""
