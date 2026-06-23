"""Heartbeat — the cognitive cycle that turns *memory you query* into *a mind*.

A background beat that runs on its own (no user turn required) and walks an agent
through seven steps, orchestrating organs the engine already has (recall, the
``Dreamer``, the temporal graph via ``context``, the LLM) plus the
:class:`SelfModel` from Phase -1:

1. **perceive**   — recent memories since the last beat (``mind.recall``)
2. **consolidate**— distil episodic → semantic (``mind.dream`` — the engine's REM)
3. **connect**    — assemble a context block from memory + temporal graph
4. **hypothesize**— generate *falsifiable* predictions (LLM, with a ``check_after``)
5. **self-correct**— confront due hypotheses with reality, mark confirmed/refuted
6. **rewrite**    — fold the lessons back into the self-model (it *becomes*)
7. **emerge**     — surface anything worth acting on via an injected ``notifier``

Principles: **fail-soft** (no LLM / no memory → the beat still runs the steps it
can and never raises), **falsifiable** (every hypothesis carries a check time),
**no forgetting** (the self-model merge is EMA + full version history), and
**dependency-injected** (it drives a ``LogicaMind`` and an optional ``notifier``
callback — it imports nothing outside the engine).

Quickstart::

    from logica_mind import LogicaMind
    from logica_mind.continuity import Heartbeat
    mind = LogicaMind(namespace="astro", llm=my_llm)
    report = Heartbeat(mind, notifier=print).beat()
"""
from __future__ import annotations

import datetime as _dt
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..types import Memory, MemoryLayer, now_iso
from .guard import SelfRewriteBlocked
from .self_model import SelfModel

_HYP_SYSTEM = "Você raciocina de forma cética e concreta. Nada de vaguidão."
_JUDGE_SYSTEM = "Você é um juiz cético. Sem evidência clara, o veredito é 'open'."


class Heartbeat:
    """One agent's cognitive cycle, driven by a :class:`LogicaMind` instance."""

    def __init__(
        self,
        mind,
        *,
        notifier: Optional[Callable[[str], Any]] = None,
        clock: Optional[Callable[[], str]] = None,
        check_after_seconds: int = 6 * 3600,
        max_hypotheses: int = 3,
        max_corrections: int = 5,
        guard: Optional[Callable[..., bool]] = None,
    ) -> None:
        self.mind = mind
        self.ns = mind.namespace
        self.store = mind.store
        self.llm = getattr(mind, "llm", None)
        self.notifier = notifier
        self._now = clock or now_iso
        self.check_after_seconds = check_after_seconds
        self.max_hypotheses = max_hypotheses
        self.max_corrections = max_corrections
        self.self_model = SelfModel(
            mind.store, mind.namespace,
            llm=self.llm, embedder=getattr(mind, "embedder", None), clock=clock, guard=guard,
        )

    # ── helpers ───────────────────────────────────────────────────────────────
    def _llm_ok(self) -> bool:
        return bool(getattr(self.llm, "available", False))

    def _plus_seconds(self, iso: str, secs: int) -> str:
        try:
            base = _dt.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.timezone.utc)
        except (ValueError, TypeError):
            base = _dt.datetime.now(_dt.timezone.utc)
        return (base + _dt.timedelta(seconds=secs)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _ask_json(self, prompt: str, system: str) -> Any:
        if not self._llm_ok():
            return None
        try:
            return self.llm.complete_json(prompt, system=system)
        except Exception:
            return None  # fail-soft: a flaky LLM never breaks the beat

    # ── the cycle ─────────────────────────────────────────────────────────────
    def beat(self) -> Dict[str, Any]:
        t0 = time.monotonic()
        report: Dict[str, Any] = {
            "agent": self.ns, "at": self._now(), "steps": {},
            "hypotheses": 0, "corrected": 0, "surfaced": 0, "llm": self._llm_ok(),
        }

        # 1. PERCEIVE
        perceived: List[Any] = []
        try:
            perceived = self.mind.recall("novidades, mudanças e sinais recentes", limit=10) or []
        except Exception:
            pass
        report["steps"]["perceive"] = len(perceived)

        # 2. CONSOLIDATE (the engine's dreaming)
        try:
            self.mind.dream()
            report["steps"]["consolidate"] = "ok"
        except Exception:
            report["steps"]["consolidate"] = "skip"

        # 3. CONNECT (memory + temporal graph)
        context = ""
        try:
            context = self.mind.context(f"o que {self.ns} precisa saber pra agir bem agora") or ""
        except Exception:
            pass
        report["steps"]["connect"] = len(context)

        model = self.self_model.load()
        perceived_txt = "\n".join(
            "• " + ((getattr(r, "memory", None).content if getattr(r, "memory", None) else str(r)) or "")[:160]
            for r in perceived[:10]
        ) or "(sem novidades)"

        beliefs_patch: List[Dict[str, Any]] = []
        surfaced: List[str] = []

        if self._llm_ok():
            # 4. HYPOTHESIZE
            for h in self._hypothesize(model, context, perceived_txt)[: self.max_hypotheses]:
                self._store_hypothesis(h)
                report["hypotheses"] += 1
                if h.get("confidence", 0) >= 0.7:
                    beliefs_patch.append({"text": h["text"][:200], "confidence": h["confidence"]})
            # 5. SELF-CORRECT
            corrected, bp, surf = self._self_correct(context, perceived_txt)
            report["corrected"] = corrected
            beliefs_patch += bp
            surfaced += surf
        else:
            report["steps"]["hypothesize"] = "skip(no-llm)"

        # 6. REWRITE THE SELF-MODEL (it becomes)
        patch: Dict[str, Any] = {}
        if beliefs_patch:
            patch["beliefs"] = beliefs_patch
        if report["corrected"]:
            patch["recent"] = {"wins": [f"auto-corrigiu {report['corrected']} hipótese(s)"]}
        if patch:
            try:
                self.self_model.save(patch)
            except SelfRewriteBlocked as blocked:
                report["blocked"] = blocked.decision.get("zone")  # gate vetoed the rewrite

        # 7. EMERGE (proactive surface)
        report["surfaced"] = len(surfaced)
        if surfaced and self.notifier:
            try:
                self.notifier(f"🫀 [{self.ns}] " + " | ".join(surfaced))
            except Exception:
                pass

        report["ms"] = int((time.monotonic() - t0) * 1000)
        return report

    # ── step 4 ────────────────────────────────────────────────────────────────
    def _hypothesize(self, model: Dict[str, Any], context: str, perceived_txt: str) -> List[Dict[str, Any]]:
        prompt = (
            f"Você é o ciclo cognitivo do agente \"{self.ns}\".\n\n"
            f"QUEM ELE É HOJE:\n{self.self_model.format_for_prompt(model) or '(self-model vazio)'}\n\n"
            f"CONTEXTO (memória de longo prazo):\n{(context or '(vazio)')[:1200]}\n\n"
            f"NOVIDADES DESDE A ÚLTIMA BATIDA:\n{perceived_txt}\n\n"
            "Gere 1 a 3 HIPÓTESES FALSIFICÁVEIS sobre o mundo/usuário/trabalho — coisas que dá "
            "pra confirmar ou refutar depois. Cada uma com confiança 0..1. "
            'Responda SÓ um array JSON: [{"text":"...","confidence":0.0}]'
        )
        data = self._ask_json(prompt, _HYP_SYSTEM)
        out: List[Dict[str, Any]] = []
        if isinstance(data, list):
            for h in data:
                if isinstance(h, dict) and h.get("text"):
                    try:
                        conf = float(h.get("confidence", 0.5))
                    except (TypeError, ValueError):
                        conf = 0.5
                    out.append({"text": str(h["text"])[:280], "confidence": round(conf, 3)})
        return out

    def _store_hypothesis(self, h: Dict[str, Any]) -> None:
        hid = uuid.uuid4().hex[:8]
        now = self._now()
        m = Memory(
            content=h["text"], namespace=self.ns, layer=MemoryLayer.SEMANTIC,
            id=f"hyp::{self.ns}::{hid}", importance=h.get("confidence", 0.5),
            metadata={
                "continuity": "heartbeat", "kind": "hypothesis", "status": "open",
                "confidence": h.get("confidence", 0.5), "created_at": now,
                "check_after": self._plus_seconds(now, self.check_after_seconds),
            },
        )
        self.store.add([m])

    # ── step 5 ────────────────────────────────────────────────────────────────
    def _open_due_hypotheses(self) -> List[Memory]:
        now = self._now()
        out: List[Memory] = []
        for m in self.store.all(self.ns, layers=[MemoryLayer.SEMANTIC]):
            meta = m.metadata or {}
            if (meta.get("continuity") == "heartbeat" and meta.get("kind") == "hypothesis"
                    and meta.get("status") == "open" and (meta.get("check_after") or "") <= now):
                out.append(m)
        return out

    def _self_correct(self, context: str, perceived_txt: str) -> Tuple[int, List[Dict[str, Any]], List[str]]:
        corrected = 0
        beliefs_patch: List[Dict[str, Any]] = []
        surfaced: List[str] = []
        for m in self._open_due_hypotheses()[: self.max_corrections]:
            prompt = (
                f"HIPÓTESE (de {(m.metadata or {}).get('created_at')}): \"{m.content}\"\n\n"
                f"REALIDADE OBSERVADA AGORA:\n{perceived_txt}\n{(context or '')[:800]}\n\n"
                "A hipótese se confirmou, foi refutada, ou ainda não dá pra dizer? "
                'Responda SÓ JSON: {"verdict":"confirmed|refuted|open","why":"...","confidence":0.0}'
            )
            j = self._ask_json(prompt, _JUDGE_SYSTEM)
            if not isinstance(j, dict):
                continue
            verdict = j.get("verdict")
            if verdict in ("confirmed", "refuted"):
                meta = dict(m.metadata or {})
                meta["status"] = verdict
                meta["resolved_at"] = self._now()
                meta["why"] = str(j.get("why", ""))[:200]
                m.metadata = meta
                self.store.add([m])  # upsert (same id) — status persisted
                corrected += 1
                beliefs_patch.append({
                    "text": m.content[:200],
                    "confidence": 0.7 if verdict == "confirmed" else 0.2,
                })
                if verdict == "refuted":
                    surfaced.append(f"crença refutada: {m.content[:80]}")
        return corrected, beliefs_patch, surfaced


def beat_all(minds: List[Any], **kwargs) -> List[Dict[str, Any]]:
    """Run one beat for each mind (tiered fleets wire scheduling on top)."""
    out = []
    for mind in minds:
        try:
            out.append(Heartbeat(mind, **kwargs).beat())
        except Exception as e:  # pragma: no cover
            out.append({"agent": getattr(mind, "namespace", "?"), "error": str(e)})
    return out
