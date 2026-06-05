"""Temporal knowledge-graph primitives."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from ..types import now_iso


def _to_dt(ts: Optional[str]):
    """Parse an ISO timestamp ('Z', offset or fractional) to a UTC datetime, or
    None if unparseable. Lets point-in-time comparisons work regardless of the
    backend's timestamp form (SQLite 'Z' vs Supabase '+00:00')."""
    if not ts:
        return None
    try:
        s = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


@dataclass
class Edge:
    """A time-bounded relationship: (subject) --predicate--> (object).

    `valid_from` / `valid_to` express *when the fact was true*. An edge with
    `valid_to is None` is currently valid; when a contradicting edge arrives, the
    old one is "closed" by setting its `valid_to`.
    """

    subject: str
    predicate: str
    object: str
    fact: str = ""                       # natural-language statement of the edge
    valid_from: str = field(default_factory=now_iso)
    valid_to: Optional[str] = None       # None = still valid
    confidence: float = 1.0              # fact rating in [0, 1]
    subject_type: str = ""               # optional typed ontology (e.g. "Person")
    object_type: str = ""                # e.g. "Organization"
    source_ids: List[str] = field(default_factory=list)  # provenance: episode ids
    id: str = ""

    def __post_init__(self):
        # clamp confidence on every construction path (direct ingest, extractor,
        # deserialization) so an out-of-range value can't leak into ranking
        try:
            c = float(self.confidence)
        except (TypeError, ValueError):
            c = 1.0
        self.confidence = max(0.0, min(1.0, c))

    @property
    def is_valid(self) -> bool:
        return self.valid_to is None

    def valid_at(self, ts: str) -> bool:
        """Whether this fact was true at timestamp `ts`. Compares as real UTC
        instants (handles 'Z', offset and fractional forms); falls back to a
        lexical compare only if a timestamp can't be parsed."""
        q, vf = _to_dt(ts), _to_dt(self.valid_from)
        if q is None or vf is None:
            if ts < self.valid_from:
                return False
            return self.valid_to is None or ts < self.valid_to
        if q < vf:
            return False
        if self.valid_to is None:
            return True
        vt = _to_dt(self.valid_to)
        return vt is None or q < vt

    def key(self) -> str:
        """Identity of the relationship slot (ignores the object/value)."""
        return f"{self.subject.lower()}|{self.predicate.lower()}"

    def label(self) -> str:
        return self.fact or f"{self.subject} {self.predicate} {self.object}"
