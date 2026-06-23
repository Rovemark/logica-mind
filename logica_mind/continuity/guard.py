"""Self-rewrite guard — the constitutional brake on an agent editing *itself*.

An agent that can rewrite its own identity needs a brake, or a bad beat (or a
prompt injection that reaches the self-model) can quietly erase who it is. This
module classifies a proposed self-change into a **zone** and lets a host plug a
**policy** that may veto it — all in the kernel, dependency-free.

* :func:`classify_self_change` — pure function, ``prev`` vs ``proposed`` → zone:
    - **green**  routine nudges (small skill/drive moves, appended wins/errors)
    - **yellow** notable: a new belief, a direction change, coherence/legacy erosion
    - **red**    re-identification: changing a *non-empty* identity
* :func:`zone_guard` — a ready-made policy callable (blocks ``red`` by default).
* :class:`SelfRewriteBlocked` — raised by ``SelfModel.save`` when a guard vetoes.

The host (e.g. LogicaOS) injects its own guard to route ``yellow``/``red`` through
its governance/approval — the kernel ships a safe default and no coupling.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List

_ORDER = {"green": 0, "yellow": 1, "red": 2}


def _escalate(current: str, candidate: str) -> str:
    return candidate if _ORDER[candidate] > _ORDER[current] else current


def classify_self_change(prev: Dict[str, Any], proposed: Dict[str, Any]) -> Dict[str, Any]:
    """Classify a proposed self-model change. Returns ``{"zone", "reasons"}``."""
    prev = prev or {}
    proposed = proposed or {}
    zone = "green"
    reasons: List[str] = []

    # RED — re-identification: overwriting a non-empty identity with a different one
    p_id = (prev.get("identity") or "").strip()
    n_id = (proposed.get("identity") or "").strip()
    if p_id and n_id and n_id != p_id:
        zone = _escalate(zone, "red")
        reasons.append("mudança de identidade")

    # YELLOW — a change of declared direction
    if proposed.get("direction") and proposed.get("direction") != prev.get("direction"):
        zone = _escalate(zone, "yellow")
        reasons.append("mudança de direção")

    # YELLOW — erosion of the load-bearing drives (slow self-corruption signal)
    for d in ("coherence", "legacy"):
        p = (prev.get("drives") or {}).get(d)
        n = (proposed.get("drives") or {}).get(d)
        if isinstance(p, (int, float)) and isinstance(n, (int, float)) and n < p - 0.1:
            zone = _escalate(zone, "yellow")
            reasons.append(f"queda de {d} ({p}→{n})")

    # YELLOW — newly formed beliefs
    prev_texts = {b.get("text") for b in (prev.get("beliefs") or [])}
    new_beliefs = [b for b in (proposed.get("beliefs") or [])
                   if b.get("text") and b.get("text") not in prev_texts]
    if new_beliefs:
        zone = _escalate(zone, "yellow")
        reasons.append(f"{len(new_beliefs)} crença(s) nova(s)")

    return {"zone": zone, "reasons": reasons}


class SelfRewriteBlocked(Exception):
    """Raised when a guard vetoes a self-model change. Carries the ``decision``."""

    def __init__(self, decision: Dict[str, Any]) -> None:
        self.decision = decision
        zone = decision.get("zone")
        why = ", ".join(decision.get("reasons") or []) or "—"
        super().__init__(f"self-rewrite bloqueado (zona {zone}): {why}")


def zone_guard(block_zones=("red",), on_block: Callable[..., Any] = None) -> Callable[..., bool]:
    """A policy callable for ``SelfModel(guard=...)``: blocks the given zones.

    Returns ``guard(prev, proposed, decision) -> bool`` (True = allow). Default
    blocks only ``red`` (re-identification); pass ``("red","yellow")`` to be strict.
    ``on_block`` (optional) is called for the audit trail when a change is vetoed.
    """
    blocked = set(block_zones)

    def _guard(prev: Dict[str, Any], proposed: Dict[str, Any], decision: Dict[str, Any]) -> bool:
        if decision.get("zone") in blocked:
            if on_block:
                try:
                    on_block(prev, proposed, decision)
                except Exception:
                    pass
            return False
        return True

    return _guard
