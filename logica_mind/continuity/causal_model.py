"""Causal model — a scaffold for "if I do X, what happens?" before acting.

Most agents act and find out. This lets an agent **simulate second-order effects**
first: it pulls what the temporal graph / memory knows about an action, runs one
cheap LLM step, and returns predicted effects with probabilities and a confidence.

**Honest scope (stated on purpose):** this is a *heuristic* simulator — graph
context + one reasoning step — **not a learned world-model**. It's meant to gate
risky (red-zone) actions with a sanity check, not to be trusted as ground truth.
Fail-soft: with no LLM it returns an empty, zero-confidence result instead of
guessing. Dependency-injected (drives a ``LogicaMind``).
"""
from __future__ import annotations

from typing import Any, Dict

from ..types import now_iso

_CAVEAT = "Simulação heurística (contexto do grafo + 1 passo de raciocínio) — NÃO é um world-model aprendido."
_SYSTEM = "Você é um simulador causal cético: efeitos de 2ª ordem, probabilidades honestas, sem hype."


class CausalModel:
    def __init__(self, mind, *, clock=None) -> None:
        self.mind = mind
        self.ns = mind.namespace
        self.llm = getattr(mind, "llm", None)
        self._now = clock or now_iso

    def _llm_ok(self) -> bool:
        return bool(getattr(self.llm, "available", False))

    def simulate(self, action: str, *, horizon: str = "30 dias") -> Dict[str, Any]:
        """Predict the second-order effects of ``action`` over ``horizon``."""
        result: Dict[str, Any] = {
            "action": action, "horizon": horizon, "effects": [],
            "confidence": 0.0, "reasoning": "", "caveat": _CAVEAT, "at": self._now(),
        }
        if not self._llm_ok():
            result["reasoning"] = "LLM indisponível — sem simulação (fail-soft)."
            return result

        context = ""
        try:
            context = self.mind.context(f"o que se relaciona a: {action}") or ""
        except Exception:
            pass

        prompt = (
            f"AÇÃO proposta: \"{action}\"\nHORIZONTE: {horizon}\n\n"
            f"CONTEXTO (grafo temporal / memória):\n{(context or '(vazio)')[:1200]}\n\n"
            "Preveja os EFEITOS DE 2ª ORDEM (não só o óbvio de 1ª ordem). Para cada efeito, "
            "dê uma probabilidade 0..1. Responda SÓ JSON: "
            '{"effects":[{"effect":"...","probability":0.0}],"confidence":0.0,"reasoning":"..."}'
        )
        try:
            j = self.llm.complete_json(prompt, system=_SYSTEM)
        except Exception:
            j = None

        if isinstance(j, dict):
            effects = []
            for e in (j.get("effects") or []):
                if isinstance(e, dict) and e.get("effect"):
                    try:
                        p = round(float(e.get("probability", 0.5)), 3)
                    except (TypeError, ValueError):
                        p = 0.5
                    effects.append({"effect": str(e["effect"])[:200], "probability": p})
            result["effects"] = effects
            try:
                result["confidence"] = round(float(j.get("confidence", 0.4)), 3)
            except (TypeError, ValueError):
                result["confidence"] = 0.4
            result["reasoning"] = str(j.get("reasoning", ""))[:500]
        return result
