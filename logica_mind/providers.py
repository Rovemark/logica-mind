"""Provider auto-detection and a snapshot of the active stack.

Two jobs:
  1. Zero-config wiring — if a provider is already in the environment (e.g.
     ``OPENAI_API_KEY``), pick it up automatically so extraction, conflict
     resolution and richer embeddings just turn on, no code change.
  2. Power the dashboard's Integrations panel — report what's active and what's
     available to enable (LLMs, embedders, rerankers, and every store backend,
     including the redundant Multi-store and the human-readable Obsidian vault).

Detection is best-effort and never raises: a missing package or key simply reads
as "not available".
"""
from __future__ import annotations

import importlib.util
import os
from typing import Any, Dict, List, Optional


def _has(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except Exception:
        return False


def _claude_bin() -> str:
    return os.environ.get("LOGICA_MIND_CLAUDE_BIN", "claude")


def _claude_cli_present() -> bool:
    import shutil
    return shutil.which(_claude_bin()) is not None


def _build_llm(provider: str) -> Optional[Any]:
    """Construct one provider if its prerequisites are present, else None. Never raises."""
    env = os.environ
    try:
        if provider == "anthropic" and env.get("ANTHROPIC_API_KEY") and _has("anthropic"):
            from .llm.anthropic import AnthropicLLM
            return AnthropicLLM()
        if provider == "openai" and env.get("OPENAI_API_KEY") and _has("openai"):
            from .llm.openai import OpenAILLM
            return OpenAILLM()
        if provider == "claude-cli" and _claude_cli_present():
            from .llm.claude_cli import ClaudeCLILLM
            llm = ClaudeCLILLM(binary=_claude_bin())
            return llm if llm.available else None
    except Exception:
        return None
    return None


# API keys are explicit intent → auto-used. The local Claude CLI is detected and
# surfaced, but only ENABLED on request (LOGICA_MIND_LLM=claude-cli): merely
# having Claude Code installed shouldn't silently change a library's behavior or
# spawn subprocesses. This keeps `LogicaMind()` deterministic by default.
_LLM_AUTO_ORDER = ["anthropic", "openai"]
_LLM_ALL = ["anthropic", "openai", "claude-cli"]


def auto_llm() -> Optional[Any]:
    """The best LLM to use on this machine, or None.

    With ``LOGICA_MIND_LLM`` set (``anthropic`` / ``openai`` / ``claude-cli``),
    that provider is used. Otherwise auto-detects from explicit API keys only
    (Anthropic → OpenAI). When a provider is active, a single ``remember()``
    decomposes a message into atomic facts, categorizes them across life/work
    dimensions, and reconciles them in place."""
    forced = os.environ.get("LOGICA_MIND_LLM", "").strip().lower()
    order = [forced] if forced in _LLM_ALL else _LLM_AUTO_ORDER
    for provider in order:
        llm = _build_llm(provider)
        if llm is not None and getattr(llm, "available", True):
            return llm
    return None


def auto_embedder() -> Optional[Any]:
    """A hosted embedder from the environment (Voyage preferred, then OpenAI), or
    None to fall back to the offline hashing embedder. Only used for fresh stores
    by callers that opt in — switching embedders changes vector dimensionality."""
    try:
        if os.environ.get("VOYAGE_API_KEY") and _has("voyageai"):
            from .embeddings.voyage import VoyageEmbedder
            return VoyageEmbedder()
        if os.environ.get("OPENAI_API_KEY") and _has("openai"):
            from .embeddings.openai import OpenAIEmbedder
            return OpenAIEmbedder()
    except Exception:
        pass
    return None


def detect() -> Dict[str, List[Dict[str, Any]]]:
    """A structured catalog of every integration — what's detected in the
    environment and whether its package is installed. Pure inspection."""
    env = os.environ
    llm = [
        {"id": "anthropic", "label": "Anthropic · Claude", "model": "claude-haiku-4-5",
         "env": "ANTHROPIC_API_KEY", "detected": bool(env.get("ANTHROPIC_API_KEY")), "installed": _has("anthropic")},
        {"id": "openai", "label": "OpenAI", "model": "gpt-4o-mini",
         "env": "OPENAI_API_KEY", "detected": bool(env.get("OPENAI_API_KEY")), "installed": _has("openai")},
        {"id": "claude-cli", "label": "Claude CLI · local", "model": "your Claude Code, no API key",
         "env": None, "detected": _claude_cli_present(), "installed": _claude_cli_present()},
    ]
    embedders = [
        {"id": "voyage", "label": "Voyage", "model": "voyage-3-lite",
         "env": "VOYAGE_API_KEY", "detected": bool(env.get("VOYAGE_API_KEY")), "installed": _has("voyageai")},
        {"id": "openai", "label": "OpenAI", "model": "text-embedding-3-small",
         "env": "OPENAI_API_KEY", "detected": bool(env.get("OPENAI_API_KEY")), "installed": _has("openai")},
        {"id": "local", "label": "Local · sentence-transformers", "model": "all-MiniLM-L6-v2",
         "env": None, "detected": _has("sentence_transformers"), "installed": _has("sentence_transformers")},
        {"id": "hashing", "label": "Hashing · offline", "model": "256-dim, no keys",
         "env": None, "detected": True, "installed": True},
    ]
    rerankers = [
        {"id": "voyage-rerank", "label": "Voyage rerank", "env": "VOYAGE_API_KEY",
         "detected": bool(env.get("VOYAGE_API_KEY")), "installed": _has("voyageai")},
        {"id": "mmr", "label": "MMR · diversity", "env": None, "detected": True, "installed": True},
        {"id": "rrf", "label": "Reciprocal-rank fusion", "env": None, "detected": True, "installed": True},
        {"id": "node-distance", "label": "Graph node-distance", "env": None, "detected": True, "installed": True},
    ]
    stores = [
        {"id": "sqlite", "label": "SQLite", "blurb": "Local file. The zero-config default.",
         "env": None, "detected": True, "installed": True},
        {"id": "obsidian", "label": "Obsidian vault", "blurb": "Plain-markdown notes in a folder — human-readable, git-friendly, yours forever.",
         "env": None, "detected": True, "installed": True},
        {"id": "postgres", "label": "Postgres", "blurb": "Production SQL with pgvector.",
         "env": "POSTGRES_DSN", "detected": bool(env.get("POSTGRES_DSN")), "installed": _has("psycopg")},
        {"id": "redis", "label": "Redis", "blurb": "Fast in-memory backend.",
         "env": "REDIS_URL", "detected": bool(env.get("REDIS_URL")), "installed": _has("redis")},
        {"id": "supabase", "label": "Supabase", "blurb": "Hosted Postgres over REST — no driver needed.",
         "env": "SUPABASE_URL", "detected": bool(env.get("SUPABASE_URL")), "installed": True},
        {"id": "memory", "label": "In-memory", "blurb": "Ephemeral — for tests and scratch work.",
         "env": None, "detected": True, "installed": True},
        {"id": "multi", "label": "Multi-store · redundant", "blurb": "Mirror writes across several backends; reads merge. Redundancy and portability in one.",
         "env": None, "detected": True, "installed": True},
    ]
    return {"llm": llm, "embedders": embedders, "rerankers": rerankers, "stores": stores}
