"""Use a locally-installed Claude CLI (Claude Code) as the LLM — zero API key.

If the `claude` binary is on PATH, Logica Mind can drive it non-interactively
(`claude -p`) for fact extraction and the dialectic user model. Perfect for a
machine that already has Claude Code: no API key, no extra install, no per-token
bill — the model you're already signed into becomes the memory's brain.
"""
from __future__ import annotations

import shutil
import subprocess
from typing import Optional

from .base import LLM


class ClaudeCLILLM(LLM):
    name = "claude-cli"

    def __init__(self, binary: str = "claude", timeout: int = 120, extra_args: Optional[list] = None):
        self.binary = binary
        self.timeout = timeout
        self.extra_args = list(extra_args or [])
        self._path = shutil.which(binary)
        self.available = self._path is not None

    def complete(self, prompt: str, system: Optional[str] = None) -> str:
        if not self._path:
            raise RuntimeError("claude CLI not found on PATH (install Claude Code or pass binary=…).")
        text = (system + "\n\n" + prompt) if system else prompt
        try:
            res = subprocess.run(
                [self._path, "-p", *self.extra_args, text],
                capture_output=True, text=True, timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"claude CLI timed out after {self.timeout}s") from e
        if res.returncode != 0:
            raise RuntimeError(f"claude CLI failed ({res.returncode}): {(res.stderr or '')[:200]}")
        return (res.stdout or "").strip()
