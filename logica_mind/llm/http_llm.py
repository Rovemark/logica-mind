"""Zero-dependency HTTP LLM clients for local and self-hosted models.

These need no SDK — just urllib — so the library can talk to whatever the user
already runs: an open-source model behind an OpenAI-compatible server (Ollama,
LM Studio, llama.cpp, vLLM, MLX) or any Anthropic Messages-compatible gateway
(a self-hosted proxy). Auto-detection lives in ``providers.py``; these are the
transports it wires up.
"""
from __future__ import annotations

import json
import os
import socket
import urllib.request
from typing import Optional
from urllib.parse import urlparse

from .base import LLM


def _port_open(url: str, timeout: float = 0.6) -> bool:
    try:
        p = urlparse(url)
        host = p.hostname or "127.0.0.1"
        port = p.port or (443 if p.scheme == "https" else 80)
        socket.create_connection((host, port), timeout=timeout).close()
        return True
    except Exception:
        return False


class OpenAICompatLLM(LLM):
    """Any OpenAI chat-completions endpoint (Ollama, LM Studio, llama.cpp, vLLM,
    MLX, or OpenAI itself). Zero-dep: posts to ``{base_url}/chat/completions``."""
    name = "openai-compat"

    def __init__(self, base_url: str, model: str, api_key: str = "", timeout: int = 90):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.available = _port_open(self.base_url)

    def complete(self, prompt: str, system: Optional[str] = None) -> str:
        msgs = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]
        body = json.dumps({"model": self.model, "messages": msgs, "temperature": 0}).encode()
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(f"{self.base_url}/chat/completions", data=body,
                                     headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            j = json.load(r)
        return (j["choices"][0]["message"]["content"] or "").strip()


class AnthropicCompatLLM(LLM):
    """Any Anthropic Messages-compatible endpoint (a self-hosted or proxy gateway).
    Zero-dep: posts the Anthropic ``/messages`` shape with ``x-api-key``."""
    name = "anthropic-compat"

    def __init__(self, base_url: str, model: str, api_key: str = "", timeout: int = 90):
        # accept either the full /messages URL or a host root
        self.url = base_url if base_url.rstrip("/").endswith("/messages") else base_url.rstrip("/") + "/v1/messages"
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.available = _port_open(self.url)

    def complete(self, prompt: str, system: Optional[str] = None) -> str:
        body = {"model": self.model, "max_tokens": 1024, "temperature": 0,
                "messages": [{"role": "user", "content": prompt}]}
        if system:
            body["system"] = system
        headers = {"content-type": "application/json", "anthropic-version": "2023-06-01"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(),
                                     headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            j = json.load(r)
        return "".join(p.get("text", "") for p in (j.get("content") or [])
                       if isinstance(p, dict) and p.get("type") == "text").strip()


# Common local OpenAI-compatible servers, probed in order when nothing is
# configured explicitly. (host, default-model). `mlx_lm.server` is OpenAI-
# compatible, so MLX models served that way are picked up here too.
LOCAL_OPENAI_ENDPOINTS = [
    ("http://127.0.0.1:11434/v1", "llama3.1"),    # Ollama
    ("http://127.0.0.1:1234/v1", "local-model"),  # LM Studio
    ("http://127.0.0.1:8080/v1", "local-model"),  # llama.cpp / vLLM / MLX (30B slot)
    ("http://127.0.0.1:8081/v1", "local-model"),  # MLX (4B slot)
    ("http://127.0.0.1:8000/v1", "local-model"),  # vLLM default
]


def detect_local_openai(timeout: float = 0.5) -> Optional[OpenAICompatLLM]:
    """Probe well-known local OpenAI-compatible servers and return the first that
    answers with at least one model. No config needed — if you have Ollama or LM
    Studio running, memory consolidation just turns on."""
    base = os.environ.get("LOGICA_MIND_LLM_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
    candidates = [(base, os.environ.get("LOGICA_MIND_LLM_MODEL", "local-model"))] if base else LOCAL_OPENAI_ENDPOINTS
    for url, default_model in candidates:
        if not url or not _port_open(url, timeout):
            continue
        model = os.environ.get("LOGICA_MIND_LLM_MODEL", default_model)
        try:                                       # ask the server which model it actually serves
            with urllib.request.urlopen(f"{url.rstrip('/')}/models", timeout=timeout) as r:
                data = json.load(r).get("data") or []
            if data and not os.environ.get("LOGICA_MIND_LLM_MODEL"):
                model = data[0].get("id", model)
        except Exception:
            if not base:        # an unprobeable well-known port is not a confident hit
                continue
        key = os.environ.get("LOGICA_MIND_LLM_KEY") or os.environ.get("OPENAI_API_KEY", "")
        llm = OpenAICompatLLM(url, model, api_key=key)
        if llm.available:
            return llm
    return None
