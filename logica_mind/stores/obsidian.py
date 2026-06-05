"""Obsidian (markdown vault) store.

Each memory becomes a human-readable `.md` file with YAML-ish frontmatter, under
`<vault>/<namespace>/<layer>/<id>.md`. Great as an audit trail or a second store
behind a fast one (see MultiStore). Search is lexical here — pair it with a
vector-capable store for semantic recall, or rely on the core's embedder when the
file is also mirrored to SQLite/Supabase.
"""
from __future__ import annotations

import json
import os
import re
from typing import List, Optional

from ..types import Memory, MemoryLayer, SearchResult, now_iso
from .base import Store, rank, apply_filter

_FM = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


def _expand(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _parse_list(value: str) -> List[str]:
    value = value.strip().strip("[]")
    return [v.strip().strip("'\"") for v in value.split(",") if v.strip()]


def _fm_scalar(v) -> str:
    """A single-line frontmatter-safe scalar. A newline (or a stray '---') in a
    title/name/status — reachable via POST /api/record or a pasted line break —
    would otherwise inject a second `metadata:`/`---` and corrupt the file:
    the non-greedy frontmatter regex closes early and _load's last-write-wins
    loop hijacks the record. Collapse all whitespace runs to single spaces."""
    return " ".join(str(v).split())


def _session_frontmatter(metadata: dict) -> List[str]:
    """Presentational frontmatter lines for a structured session record so an
    Obsidian vault shows it as rich Properties — generic (no framework terms):
    type/session_id/title/status, participant names, each metric, each link.
    All values are newline-flattened; the JSON `metadata:` line stays the
    round-trip source of truth, so these are display-only and lossless."""
    if not metadata.get("record"):
        return []
    out = ["type: session"]
    if metadata.get("session"):
        out.append(f"session_id: {_fm_scalar(metadata['session'])}")
    if metadata.get("title"):
        out.append(f"title: {_fm_scalar(metadata['title'])}")
    if metadata.get("status"):
        out.append(f"status: {_fm_scalar(metadata['status'])}")
    parts = metadata.get("participants") or []
    names = [_fm_scalar(p.get("name")) for p in parts if isinstance(p, dict) and p.get("name")]
    if names:
        out.append(f"participants: [{', '.join(names)}]")
    for k, v in (metadata.get("metrics") or {}).items():
        out.append(f"metric_{_fm_scalar(k)}: {_fm_scalar(v)}")
    for k, v in (metadata.get("links") or {}).items():
        out.append(f"link_{_fm_scalar(k)}: {_fm_scalar(v)}")
    return out


class ObsidianStore(Store):
    name = "obsidian"

    def __init__(self, vault: str = "~/logica-mind-vault"):
        self.vault = _expand(vault)
        os.makedirs(self.vault, exist_ok=True)

    def _path(self, m: Memory) -> str:
        d = os.path.join(self.vault, m.namespace, m.layer.value)
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, f"{m.id}.md")

    def _render(self, m: Memory) -> str:
        tags = ", ".join(m.tags)
        fm = [
            "---",
            f"id: {m.id}",
            f"namespace: {m.namespace}",
            f"layer: {m.layer.value}",
            f"importance: {m.importance}",
            f"tags: [{tags}]",
            f"source_ids: [{', '.join(m.source_ids)}]",
            f"metadata: {json.dumps(m.metadata or {})}",
            f"created_at: {m.created_at or now_iso()}",
            f"access_count: {m.access_count}",
            f"last_recalled_at: {m.last_recalled_at or ''}",
            f"surprise_score: {getattr(m, 'surprise_score', 0.0)}",
        ]
        # rich, human-readable frontmatter for a structured session record — these
        # are presentational (Obsidian Properties panel); the JSON `metadata` line
        # above stays the round-trip source of truth, so _load is unaffected.
        fm += _session_frontmatter(m.metadata or {})
        fm += ["---", "", m.content, ""]
        return "\n".join(fm)

    def add(self, memories: List[Memory]) -> None:
        for m in memories:
            with open(self._path(m), "w", encoding="utf-8") as f:
                f.write(self._render(m))

    @staticmethod
    def _load(path: str) -> Optional[Memory]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError:
            return None
        match = _FM.match(text)
        if not match:
            return None
        meta_block, content = match.group(1), match.group(2).strip()
        meta = {}
        for line in meta_block.splitlines():
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
        try:
            metadata = json.loads(meta.get("metadata", "{}") or "{}")
        except (ValueError, TypeError):
            metadata = {}
        try:
            return Memory(
                id=meta.get("id", ""),
                namespace=meta.get("namespace", "default"),
                content=content,
                layer=MemoryLayer(meta.get("layer", "semantic")),
                importance=float(meta.get("importance", 0.5) or 0.5),
                tags=_parse_list(meta.get("tags", "")),
                source_ids=_parse_list(meta.get("source_ids", "")),
                metadata=metadata,
                created_at=meta.get("created_at", ""),
                access_count=int(meta.get("access_count", 0) or 0),
                last_recalled_at=meta.get("last_recalled_at") or None,
                surprise_score=float(meta.get("surprise_score", 0.0) or 0.0),
            )
        except (ValueError, KeyError):
            return None

    def _candidates(self, namespace: str, layers: Optional[List[MemoryLayer]]) -> List[Memory]:
        base = os.path.join(self.vault, namespace)
        if not os.path.isdir(base):
            return []
        wanted = {l.value for l in layers} if layers else None
        out: List[Memory] = []
        for layer_dir in os.listdir(base):
            if wanted and layer_dir not in wanted:
                continue
            d = os.path.join(base, layer_dir)
            if not os.path.isdir(d):
                continue
            for fn in os.listdir(d):
                if fn.endswith(".md"):
                    m = self._load(os.path.join(d, fn))
                    if m:
                        out.append(m)
        return out

    def search(self, namespace, query_embedding, query_text, layers=None, limit=20, metadata_filter=None) -> List[SearchResult]:
        # markdown store is lexical; ignore embedding
        cands = apply_filter(self._candidates(namespace, layers), metadata_filter)
        return rank(cands, None, query_text, limit)

    def get(self, namespace: str, memory_id: str) -> Optional[Memory]:
        for m in self._candidates(namespace, None):
            if m.id == memory_id:
                return m
        return None

    def delete(self, namespace: str, memory_id: str) -> bool:
        base = os.path.join(self.vault, namespace)
        if not os.path.isdir(base):
            return False
        for layer_dir in os.listdir(base):
            p = os.path.join(base, layer_dir, f"{memory_id}.md")
            if os.path.isfile(p):
                os.remove(p)
                return True
        return False

    def all(self, namespace, layers=None) -> List[Memory]:
        return self._candidates(namespace, layers)

    def touch(self, namespace: str, ids: List[str]) -> None:
        stamp = now_iso()
        for mid in ids:
            m = self.get(namespace, mid)
            if m:
                m.access_count += 1
                m.last_recalled_at = stamp
                with open(self._path(m), "w", encoding="utf-8") as f:
                    f.write(self._render(m))

    def namespaces(self) -> List[str]:
        if not os.path.isdir(self.vault):
            return []
        return sorted(
            d for d in os.listdir(self.vault)
            if os.path.isdir(os.path.join(self.vault, d))
        )
