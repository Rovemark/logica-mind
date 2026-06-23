"""Debate with consequence — disagreement that actually changes the minds in it.

A debate is only real if it has stakes. :class:`Debate` takes the positions a set
of agents held on a question plus the verdict, and applies **epistemic
consequence** to their self-models:

* the **winner** records a win, reinforces the stance it argued, and its *mastery*
  drive ticks up — and it **takes risk**: the winning stance is promoted to the
  shared cortex (company-wide), where reality can later refute it in public.
* the **losers** record the loss, *weaken* the stance they argued, and their
  *coherence* drive ticks up (motivated to realign).

To avoid the classic failure where consensus rewards the most verbose/sycophantic
voice, the winning stance is promoted **only** with a clear confidence margin AND
after an injected skepticism check (``skeptic_passed``). Dependency-injected
(``store``); imports nothing outside the engine.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..types import now_iso
from .self_model import SelfModel
from .world_insights import WorldInsights

_PROMOTE_MIN_CONFIDENCE = 0.6


class Debate:
    def __init__(self, store, *, clock=None) -> None:
        self.store = store
        self._now = clock or now_iso
        self.world = WorldInsights(store, clock=clock)

    def resolve(self, question: str, positions: List[Dict[str, Any]], *,
                winner: str, skeptic_passed: bool = True,
                dept: Optional[str] = None) -> Dict[str, Any]:
        """Apply the consequences of a resolved debate. ``positions`` is a list of
        ``{agent, stance, confidence}``; ``winner`` is the agent that prevailed."""
        positions = positions or []
        q = (question or "")[:60]
        win_pos = next((p for p in positions if p.get("agent") == winner), None)
        result: Dict[str, Any] = {"question": question, "winner": winner,
                                  "consequences": [], "promoted": False}

        for p in positions:
            agent = p.get("agent")
            if not agent:
                continue
            sm = SelfModel(self.store, agent)
            if agent == winner:
                patch = {
                    "recent": {"wins": [f"venceu debate: {q}"]},
                    "beliefs": [{"text": p.get("stance", ""),
                                 "confidence": min(0.9, float(p.get("confidence", 0.6)) + 0.1)}],
                    "drives": {"mastery": 0.85},
                }
            else:
                patch = {
                    "recent": {"errors": [f"perdeu debate: {q}"]},
                    "beliefs": [{"text": p.get("stance", ""),
                                 "confidence": max(0.1, float(p.get("confidence", 0.5)) - 0.2)}],
                    "drives": {"coherence": 0.8},
                }
            try:
                sm.save(patch)
                result["consequences"].append({"agent": agent, "outcome": "win" if agent == winner else "loss"})
            except Exception as e:  # a guard veto or CAS conflict must not abort the debate
                result["consequences"].append({"agent": agent, "outcome": "error", "why": str(e)[:80]})

        # "winner takes risk": promote the stance company-wide — but only with a
        # clear margin + skepticism, so the loudest voice doesn't auto-win.
        if win_pos:
            win_conf = float(win_pos.get("confidence", 0))
            others = [float(p.get("confidence", 0)) for p in positions if p.get("agent") != winner]
            margin_ok = win_conf >= _PROMOTE_MIN_CONFIDENCE and (not others or win_conf > max(others))
            if margin_ok and skeptic_passed:
                self.world.publish(winner, win_pos.get("stance", ""),
                                   confidence=min(0.9, win_conf), visibility="company", dept=dept)
                result["promoted"] = True
        return result
