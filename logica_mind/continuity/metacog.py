"""Metacognition — an agent knowing what it does *not* know, and who does.

Real intelligence includes self-knowledge of its own edges. :class:`Metacog`
reads the fleet's self-models to answer three questions:

* :meth:`assess` — how competent is *this* agent in a domain? (a 0..1 score, a
  human marker, and whether it clears the bar)
* :meth:`who_knows` — which *other* agents are competent in a domain (ranked)
* :meth:`route` — if the agent is out of its depth, who should it defer to?

Competence is read from the self-model: a matching ``skill`` confidence, with a
small floor from beliefs that mention the domain. Dependency-injected (just a
``store``); imports nothing outside the engine. A host wires :meth:`route` into
its executor so a weak agent attaches a confidence marker and hands off — instead
of bluffing.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..types import now_iso
from .self_model import SelfModel


class Metacog:
    def __init__(self, store, *, clock=None, min_competence: float = 0.6) -> None:
        self.store = store
        self._now = clock or now_iso
        self.min_competence = min_competence

    # ── scoring ───────────────────────────────────────────────────────────────
    @staticmethod
    def _competence(model: Dict[str, Any], domain: str) -> float:
        domain_l = (domain or "").lower().strip()
        if not domain_l:
            return 0.0
        best = 0.0
        for k, v in (model.get("skills") or {}).items():
            kl = str(k).lower()
            if kl == domain_l or kl in domain_l or domain_l in kl:
                try:
                    best = max(best, float(v))
                except (TypeError, ValueError):
                    pass
        if best == 0.0:  # no direct skill — a small floor from on-topic beliefs
            mentions = sum(1 for b in (model.get("beliefs") or [])
                           if domain_l in str(b.get("text", "")).lower())
            if mentions:
                best = min(0.5, 0.2 + 0.1 * mentions)
        return round(best, 3)

    @staticmethod
    def _marker(c: float) -> str:
        return "alta" if c >= 0.7 else "média" if c >= 0.4 else "baixa"

    # ── api ───────────────────────────────────────────────────────────────────
    def assess(self, agent: str, domain: str) -> Dict[str, Any]:
        model = SelfModel(self.store, agent).load()
        c = self._competence(model, domain)
        return {"agent": agent, "domain": domain, "competence": c,
                "marker": self._marker(c), "known": c >= self.min_competence}

    def who_knows(self, domain: str, *, exclude: Optional[List[str]] = None,
                  limit: int = 5) -> List[Dict[str, Any]]:
        ex = set(exclude or [])
        out: List[Dict[str, Any]] = []
        for ns in self.store.namespaces():
            if ns in ex or ns.startswith("__"):
                continue
            model = SelfModel(self.store, ns).load()
            if int(model.get("version", 0)) <= 0:   # no self-model yet → not an agent we can vouch for
                continue
            c = self._competence(model, domain)
            if c >= self.min_competence:
                out.append({"agent": ns, "competence": c})
        out.sort(key=lambda x: x["competence"], reverse=True)
        return out[:limit]

    def route(self, agent: str, domain: str) -> Dict[str, Any]:
        a = self.assess(agent, domain)
        if a["known"]:
            return {**a, "route_to": None, "candidates": []}
        others = self.who_knows(domain, exclude=[agent])
        return {**a, "route_to": others[0]["agent"] if others else None, "candidates": others}
