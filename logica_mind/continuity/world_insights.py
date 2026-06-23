"""World insights — the shared cortex of a fleet of agents.

The self-model is private (who *one* agent is). The world cortex is public: when
one agent learns something, the others can wake up knowing it. Insights live in a
single shared namespace; any agent publishes, any agent reads what's relevant.

* :meth:`publish` — an agent shares a learning (deduped per agent by content, with
  a confidence and a visibility: ``company`` / ``dept`` / ``private``).
* :meth:`top_for` — the best insights *another* agent should know (filtered by
  visibility + confidence, refuted ones excluded, newest/strongest first).
* :meth:`mark_refuted` — when a belief is later disproven, retire it so it stops
  spreading; refuted insights are pruned after a TTL.
* :meth:`format_for_prompt` — a ready block ("O QUE A EMPRESA APRENDEU"), with the
  text run through the engine's prompt-injection sanitizer, because an insight
  authored by another agent is *external content* to the one consuming it.

Dependency-injected (``store`` + optional ``embedder``/``clock``); imports nothing
outside the engine.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
from typing import List, Optional

from ..guard import sanitize
from ..types import Memory, MemoryLayer, now_iso

_VIS = {"company", "dept", "private"}


class WorldInsights:
    def __init__(
        self,
        store,
        *,
        namespace: str = "__world__",
        embedder: Optional[object] = None,
        clock=None,
        max_per_agent: int = 50,
        ttl_days: int = 30,
    ) -> None:
        self.store = store
        self.namespace = namespace
        self.embedder = embedder
        self._now = clock or now_iso
        self.max_per_agent = max_per_agent
        self.ttl_days = ttl_days

    # ── write ─────────────────────────────────────────────────────────────────
    def publish(self, agent: str, text: str, *, confidence: float = 0.7,
                visibility: str = "company", refuted: bool = False,
                dept: Optional[str] = None) -> Optional[Memory]:
        text = (text or "").strip()
        if not text:
            return None
        if visibility not in _VIS:
            visibility = "company"
        hid = hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]  # dedupe per agent
        m = Memory(
            content=text, namespace=self.namespace, layer=MemoryLayer.SEMANTIC,
            id=f"insight::{agent}::{hid}", importance=float(confidence),
            metadata={
                "continuity": "world-insights", "agent": agent,
                "confidence": round(float(confidence), 3), "visibility": visibility,
                "refuted": bool(refuted), "dept": dept, "created_at": self._now(),
            },
        )
        self.store.add([m])
        self._prune(agent)
        return m

    def mark_refuted(self, agent: str, text: str) -> bool:
        hid = hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()[:10]
        m = self.store.get(self.namespace, f"insight::{agent}::{hid}")
        if not m:
            return False
        meta = dict(m.metadata or {})
        meta["refuted"] = True
        meta["refuted_at"] = self._now()
        m.metadata = meta
        self.store.add([m])
        return True

    # ── read ──────────────────────────────────────────────────────────────────
    def _all(self) -> List[Memory]:
        return [m for m in self.store.all(self.namespace, layers=[MemoryLayer.SEMANTIC])
                if (m.metadata or {}).get("continuity") == "world-insights"]

    def top_for(self, agent: Optional[str] = None, dept: Optional[str] = None, *,
                limit: int = 8, min_confidence: float = 0.7,
                exclude_own: bool = True) -> List[Memory]:
        """The insights `agent` should know — visible, confident, not refuted."""
        out: List[Memory] = []
        for m in self._all():
            md = m.metadata or {}
            if md.get("refuted"):
                continue
            if float(md.get("confidence", 0)) < min_confidence:
                continue
            if md.get("visibility") == "private":
                continue
            if exclude_own and agent and md.get("agent") == agent:
                continue
            if md.get("visibility") == "dept" and md.get("dept") != dept:
                continue  # dept-scoped: only visible to a caller of the same dept
            out.append(m)
        out.sort(key=lambda m: (float((m.metadata or {}).get("confidence", 0)),
                                (m.metadata or {}).get("created_at", "")), reverse=True)
        return out[:limit]

    def format_for_prompt(self, agent: Optional[str] = None, dept: Optional[str] = None,
                          limit: int = 5) -> str:
        items = self.top_for(agent, dept, limit=limit)
        if not items:
            return ""
        lines = ["O QUE A EMPRESA APRENDEU (insights de outros agentes):"]
        for m in items:
            md = m.metadata or {}
            # an insight authored elsewhere is external content → sanitize before injecting
            lines.append(f"• [{md.get('agent')}] {sanitize(m.content)[:200]}")
        return "\n".join(lines)

    # ── housekeeping ──────────────────────────────────────────────────────────
    def _minus_days(self, days: int) -> str:
        return (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _prune(self, agent: Optional[str] = None) -> None:
        cutoff = self._minus_days(self.ttl_days)
        # 1) drop refuted insights past the TTL (stop spreading dead beliefs)
        for m in self._all():
            md = m.metadata or {}
            if md.get("refuted") and (md.get("created_at", "") < cutoff):
                self.store.delete(self.namespace, m.id)
        # 2) cap per agent (keep the newest max_per_agent)
        if agent:
            own = sorted([m for m in self._all() if (m.metadata or {}).get("agent") == agent],
                         key=lambda m: (m.metadata or {}).get("created_at", ""), reverse=True)
            for m in own[self.max_per_agent:]:
                self.store.delete(self.namespace, m.id)
