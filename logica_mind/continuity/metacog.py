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
    # When two candidates are within this competence band, prefer the *operational*
    # agent (a department head) over a *clone-persona*. Real routing should reach the
    # team that owns the domain, not a mentor/persona that merely shares a generic tag
    # (the seed gives clones broad tags at ~0.65 — slightly above a head's 0.6 generic
    # fallback — so without this tiebreak a clone out-ranks the head on the SAME domain).
    _TYPE_TIEBREAK = 0.12
    # entity types that are routable but should *yield* to operational agents on a tie.
    _PERSONA_TYPES = frozenset({"clone", "persona", "mentor"})

    def __init__(self, store, *, clock=None, min_competence: float = 0.6) -> None:
        self.store = store
        self._now = clock or now_iso
        self.min_competence = min_competence

    # type of an entity, as recorded in its self-model (seeded). Two carriers, in
    # order: (1) a first-class ``type`` field (if a future SelfModel schema keeps it),
    # (2) a ``__type:<t>`` *sentinel skill* — the only field the current SelfModel merge
    # actually persists (it drops unknown top-level keys), so the seed encodes the type
    # there. Fail-soft: no carrier → neutral "agent" (no demotion), so a legacy/un-seeded
    # fleet that predates the field is never *regressed*.
    @staticmethod
    def _entity_type(model: Dict[str, Any]) -> str:
        t = model.get("type")
        if t:
            return str(t).lower().strip()
        for k in (model.get("skills") or {}):
            ks = str(k).lower()
            if ks.startswith("__type:"):
                return ks.split(":", 1)[1].strip() or "agent"
        return "agent"

    # rank key: competence, but a persona/clone is demoted by a small band so an
    # operational agent within that band wins the tie. A clearly-more-competent clone
    # (gap > band) still wins — we only break *near-ties*, never override real expertise.
    @classmethod
    def _rank_competence(cls, competence: float, etype: str) -> float:
        if etype in cls._PERSONA_TYPES:
            return round(competence - cls._TYPE_TIEBREAK, 3)
        return competence

    # ── scoring ───────────────────────────────────────────────────────────────
    @staticmethod
    def _competence(model: Dict[str, Any], domain: str) -> float:
        domain_l = (domain or "").lower().strip()
        if not domain_l:
            return 0.0
        best = 0.0
        for k, v in (model.get("skills") or {}).items():
            kl = str(k).lower()
            if kl.startswith("__"):   # sentinel/meta keys (e.g. __type:clone) are not domains
                continue
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
    def _match_count(model: Dict[str, Any], domain: str) -> int:
        """How many distinct (non-sentinel) skills match the domain — depth of expertise.

        Used only as a small near-tie breaker in :meth:`who_knows` (a head with 4 legal
        skills beats one with a single lgpd skill); never changes the public competence.
        """
        domain_l = (domain or "").lower().strip()
        if not domain_l:
            return 0
        n = 0
        for k in (model.get("skills") or {}):
            kl = str(k).lower()
            if kl.startswith("__"):
                continue
            if kl == domain_l or kl in domain_l or domain_l in kl:
                n += 1
        return n

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
                etype = self._entity_type(model)
                # public `competence` stays the TRUE score (contract unchanged); the
                # private `_rank` carries the type-aware tiebreak + a tiny depth bonus
                # (more matching skills wins a near-tie) used only to sort.
                depth = min(0.08, 0.02 * max(0, self._match_count(model, domain) - 1))
                out.append({"agent": ns, "competence": c,
                            "_rank": round(self._rank_competence(c, etype) + depth, 3)})
        # sort by the type-aware rank, then by true competence, then name (stable).
        out.sort(key=lambda x: (x["_rank"], x["competence"], x["agent"]), reverse=True)
        for r in out:
            r.pop("_rank", None)
        return out[:limit]

    def route(self, agent: str, domain: str) -> Dict[str, Any]:
        a = self.assess(agent, domain)
        if a["known"]:
            return {**a, "route_to": None, "candidates": []}
        others = self.who_knows(domain, exclude=[agent])
        return {**a, "route_to": others[0]["agent"] if others else None, "candidates": others}
