"""Heartbeat tests — run with: pytest. Offline (InMemoryStore + fakes).

Covers the cycle's guarantees: it pulses with no LLM (fail-soft), it generates
falsifiable hypotheses and folds high-confidence ones into the self-model, it
self-corrects due hypotheses and surfaces refutations to a notifier, and a flaky
LLM never breaks the beat.
"""
from logica_mind.stores import InMemoryStore
from logica_mind.types import SearchResult
from logica_mind.continuity import Heartbeat, SelfModel


class NoLLM:
    available = False
    def complete(self, prompt, system=None): return ""
    def complete_json(self, prompt, system=None): return None


class FakeLLM:
    available = True
    name = "fake"

    def __init__(self, hyps=None, verdict="confirmed", raise_on_json=False):
        self.hyps = hyps if hyps is not None else [
            {"text": "usuário quer foto real", "confidence": 0.9},
            {"text": "funil precisa de antes/depois", "confidence": 0.6},
        ]
        self.verdict = verdict
        self.raise_on_json = raise_on_json

    def complete(self, prompt, system=None): return ""

    def complete_json(self, prompt, system=None):
        if self.raise_on_json:
            raise RuntimeError("LLM down")
        if "verdict" in prompt:                       # the judge prompt
            return {"verdict": self.verdict, "why": "evidência X", "confidence": 0.8}
        if "HIPÓTESES FALSIFICÁVEIS" in prompt:        # the hypothesize prompt
            return self.hyps
        return None


class FakeMind:
    """Minimal stand-in for LogicaMind: just what Heartbeat drives."""

    def __init__(self, store, namespace, llm):
        self.store = store
        self.namespace = namespace
        self.llm = llm
        self.embedder = None
        self.dreamed = False

    def recall(self, query, limit=8, **kw):
        return [SearchResult(memory=m, score=1.0) for m in self.store.all(self.namespace)[:limit]]

    def dream(self, **kw):
        self.dreamed = True

    def context(self, query, **kw):
        return "contexto de teste"


def mk(llm, ns="astro"):
    return FakeMind(InMemoryStore(), ns, llm)


def test_beat_pulses_without_llm():
    mind = mk(NoLLM())
    rep = Heartbeat(mind).beat()
    assert rep["llm"] is False
    assert rep["hypotheses"] == 0 and rep["corrected"] == 0
    assert rep["steps"]["consolidate"] == "ok" and mind.dreamed     # the beat still ran
    assert "ms" in rep                                              # no exception, full report


def test_beat_generates_hypotheses_and_writes_selfmodel():
    mind = mk(FakeLLM())
    # large check window → created hypotheses are NOT due in this same beat
    rep = Heartbeat(mind, check_after_seconds=3600).beat()
    assert rep["hypotheses"] == 2 and rep["corrected"] == 0
    sm = SelfModel(mind.store, "astro").load()
    texts = [b["text"] for b in sm["beliefs"]]
    assert any("foto real" in t for t in texts)                    # the 0.9 hyp became a belief
    assert not any("antes/depois" in t for t in texts)             # the 0.6 hyp did NOT (below 0.7)


def test_self_correct_resolves_and_surfaces():
    notes = []
    mind = mk(FakeLLM(verdict="refuted"))
    # check_after=0 → the hypotheses created this beat are immediately due
    rep = Heartbeat(mind, check_after_seconds=0, notifier=notes.append).beat()
    assert rep["hypotheses"] == 2
    assert rep["corrected"] == 2 and rep["surfaced"] == 2
    assert len(notes) == 1 and "refutada" in notes[0]
    sm = SelfModel(mind.store, "astro").load()
    assert any("auto-corrigiu" in w for w in sm["recent"]["wins"])  # the lesson was folded in


def test_fail_soft_on_llm_error():
    mind = mk(FakeLLM(raise_on_json=True))
    rep = Heartbeat(mind).beat()                                    # must not raise
    assert rep["llm"] is True and rep["hypotheses"] == 0            # degraded, but pulsed
    assert rep["steps"]["consolidate"] == "ok"
