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


def _local_anthropic_gateway() -> Optional[Any]:
    """A self-hosted / proxy Anthropic Messages endpoint, if ANTHROPIC_BASE_URL
    points at one. Zero-dep — covers any local gateway without an SDK."""
    base = os.environ.get("ANTHROPIC_BASE_URL")
    if not base:
        return None
    from .llm.http_llm import AnthropicCompatLLM
    model = os.environ.get("LOGICA_MIND_LLM_MODEL", "claude-haiku-4-5-20251001")
    # a dedicated gateway key (so a deployment can point at a proxy without
    # clobbering ANTHROPIC_API_KEY, which the hosted SDK provider also reads)
    key = os.environ.get("LOGICA_MIND_GATEWAY_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")
    llm = AnthropicCompatLLM(base, model, api_key=key)
    return llm if llm.available else None


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
        if provider in ("local", "openai-compat", "ollama", "lmstudio", "mlx", "llamacpp"):
            from .llm.http_llm import detect_local_openai
            return detect_local_openai()
        if provider in ("anthropic-gateway", "gateway"):
            return _local_anthropic_gateway()
        if provider == "claude-cli" and _claude_cli_present():
            from .llm.claude_cli import ClaudeCLILLM
            llm = ClaudeCLILLM(binary=_claude_bin())
            return llm if llm.available else None
    except Exception:
        return None
    return None


# Every provider the picker can build. The AUTO order (below) is deliberately
# network-free unless you CONFIGURE a local/gateway endpoint — `LogicaMind()` must
# stay deterministic and never spawn subprocesses or probe ports just by being
# constructed. The dashboard's picker probes on demand instead.
_LLM_ALL = ["anthropic", "openai", "local", "ollama", "lmstudio", "mlx", "llamacpp",
            "anthropic-gateway", "gateway", "claude-cli"]


def _auto_order() -> "list[str]":
    order = ["anthropic", "openai"]                       # explicit keys = clear intent
    if (os.environ.get("LOGICA_MIND_LLM_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
            or os.environ.get("LOGICA_MIND_AUTODETECT_LOCAL", "").lower() in ("1", "true", "yes")):
        order.append("local")                            # opt-in local open-source probe
    if os.environ.get("ANTHROPIC_BASE_URL"):
        order.append("anthropic-gateway")                # configured gateway only
    return order


def auto_llm() -> Optional[Any]:
    """The best LLM to use, or None. Order: explicit hosted keys, then — only when
    configured — a local open-source model (Ollama / LM Studio / llama.cpp / vLLM /
    MLX) or a self-hosted Anthropic gateway. Force any provider (incl. the Claude
    CLI) with ``LOGICA_MIND_LLM``. Network-free unless you point it somewhere, so
    construction stays deterministic. When a provider is active, ``remember()`` and
    sleep-time consolidation distill raw turns into categorized, durable facts."""
    forced = os.environ.get("LOGICA_MIND_LLM", "").strip().lower()
    order = [forced] if forced in _LLM_ALL else _auto_order()
    for provider in order:
        llm = _build_llm(provider)
        if llm is not None and getattr(llm, "available", True):
            return llm
    return None


def build_llm_by_id(provider: str) -> Optional[Any]:
    """Construct a specific provider on demand (for the dashboard's LLM picker),
    bypassing the auto order. Returns the live LLM or None if unavailable."""
    return _build_llm((provider or "").strip().lower())


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
    try:                       # best-effort probe for a running local open-source LLM
        from .llm.http_llm import detect_local_openai
        _local_detected = detect_local_openai()
    except Exception:
        _local_detected = None
    llm = [
        {"id": "anthropic", "label": "Anthropic · Claude", "model": "claude-haiku-4-5",
         "env": "ANTHROPIC_API_KEY", "detected": bool(env.get("ANTHROPIC_API_KEY")), "installed": _has("anthropic")},
        {"id": "openai", "label": "OpenAI", "model": "gpt-4o-mini",
         "env": "OPENAI_API_KEY", "detected": bool(env.get("OPENAI_API_KEY")), "installed": _has("openai")},
        {"id": "claude-cli", "label": "Claude CLI · local", "model": "your Claude Code, no API key",
         "env": None, "detected": _claude_cli_present(), "installed": _claude_cli_present()},
        {"id": "local", "label": "Local · open-source LLM",
         "model": (getattr(_local_detected, "model", None) or "Ollama / LM Studio / llama.cpp / vLLM / MLX"),
         "env": "LOGICA_MIND_LLM_BASE_URL", "detected": bool(_local_detected), "installed": True},
        {"id": "anthropic-gateway", "label": "Anthropic gateway · self-hosted / proxy",
         "model": env.get("LOGICA_MIND_LLM_MODEL", "claude-haiku-4-5"),
         "env": "ANTHROPIC_BASE_URL", "detected": bool(env.get("ANTHROPIC_BASE_URL")), "installed": True},
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
