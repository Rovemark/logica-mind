"""Core data types shared across Logica Mind.

These are intentionally plain dataclasses with no third-party dependencies so the
whole library can run on the standard library alone.
"""
from __future__ import annotations

import datetime as _dt
import itertools
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional

# process-monotonic sequence — a stable tiebreak for same-second created_at, so
# ordering survives whole-second timestamp collisions independent of store order
_seq_counter = itertools.count()


class MemoryLayer(str, Enum):
    """The four kinds of memory Logica Mind manages.

    EPISODIC  raw turns/events, as they happened (conversation log).
    SEMANTIC  distilled, de-duplicated facts ("the user prefers X").
    GRAPH     entity/relationship edges, each valid over a time range.
    USER      the evolving, dialectic model of who the user is.
    """

    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    GRAPH = "graph"
    USER = "user"


def _new_id() -> str:
    return uuid.uuid4().hex


def now_iso() -> str:
    # whole-second 'Z' form (one consistent format for all rows). Same-second
    # ordering is resolved by the SQLite `rowid DESC` tiebreak, not the string.
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Memory:
    """A single unit of memory.

    `embedding` is optional: a memory can be stored text-only and still be found
    via lexical search, then back-filled with a vector later.
    """

    content: str
    namespace: str = "default"
    layer: MemoryLayer = MemoryLayer.SEMANTIC
    id: str = field(default_factory=_new_id)
    embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    importance: float = 0.5
    tags: List[str] = field(default_factory=list)
    source_ids: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)
    # process-monotonic insertion order; the authoritative tiebreak when many
    # memories share a whole-second created_at (e.g. a burst of conversation turns)
    seq: int = field(default_factory=lambda: next(_seq_counter))
    # populated when a recall touches it; used for usage-based ranking
    access_count: int = 0
    # Ebbinghaus decay: when this memory was last recalled (None = never)
    last_recalled_at: Optional[str] = None
    # surprise_score > 0 means this belief contradicted a prior high-confidence one;
    # score = old_importance × cosine_distance(old_vec, new_vec)
    surprise_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["layer"] = self.layer.value
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Memory":
        d = dict(d)
        layer = d.get("layer", MemoryLayer.SEMANTIC)
        d["layer"] = MemoryLayer(layer) if not isinstance(layer, MemoryLayer) else layer
        # tolerate extra/missing keys across versions
        allowed = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in allowed})


@dataclass
class SearchResult:
    """A memory plus the score that surfaced it from a recall()."""

    memory: Memory
    score: float
    # optional breakdown for debugging / UI ("similarity", "recency", ...)
    components: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score,
            "components": self.components,
            "memory": self.memory.to_dict(),
        }
