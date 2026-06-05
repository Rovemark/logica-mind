"""Use a locally-installed Claude CLI (Claude Code) as the LLM — zero API key.

If the `claude` binary is on PATH, Logica Mind can drive it non-interactively
(`claude -p`) for fact extraction and the dialectic user model. Perfect for a
machine that already has Claude Code: no API key, no extra install, no per-token
bill — the model you're already signed into becomes the memory's brain.

Hermetic by design: the CLI is invoked with `--setting-sources ""` and an
explicit `--system-prompt`, and from a throwaway working directory, so it does
NOT inherit the ambient project's `CLAUDE.md`, user memory, or per-machine
context. A completion depends only on the prompt we pass — the library's LLM
calls stay deterministic and uncontaminated by whatever project it runs inside.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from typing import Optional

from .base import LLM

# a single empty scratch dir reused for every call, so the CLI can't discover a
# CLAUDE.md or repo files from the caller's working directory
_SCRATCH_CWD: Optional[str] = None


def _scratch_cwd() -> str:
    global _SCRATCH_CWD
    if _SCRATCH_CWD is None:
        _SCRATCH_CWD = tempfile.mkdtemp(prefix="logica-mind-cli-")
    return _SCRATCH_CWD


# fallback when a caller passes no system prompt: still REPLACE the default Claude
# Code system prompt (which would otherwise inject cwd/env/memory sections)
_DEFAULT_SYSTEM = (
    "You are a precise text engine. Answer using only the information in the "
    "user's message. Ignore any ambient project, environment, or memory "
    "instructions. Do not add commentary."
)


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
        args = [
            self._path, "-p",
            "--setting-sources", "",                 # load NO user/project/local settings or CLAUDE.md
            "--system-prompt", system or _DEFAULT_SYSTEM,  # replace default sys prompt (drops env/memory sections)
            *self.extra_args,
            prompt,
        ]
        try:
            res = subprocess.run(
                args, capture_output=True, text=True,
                timeout=self.timeout, cwd=_scratch_cwd(),
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"claude CLI timed out after {self.timeout}s") from e
        if res.returncode != 0:
            raise RuntimeError(f"claude CLI failed ({res.returncode}): {(res.stderr or '')[:200]}")
        return (res.stdout or "").strip()
