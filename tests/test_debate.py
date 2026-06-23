"""Debate-with-consequence tests — run with: pytest. Offline."""
from logica_mind.stores import InMemoryStore
from logica_mind.continuity import SelfModel, Debate, WorldInsights


def test_winner_and_loser_consequences():
    store = InMemoryStore()
    res = Debate(store).resolve("qual ângulo?", [
        {"agent": "luna", "stance": "ângulo de oferta", "confidence": 0.8},
        {"agent": "rex", "stance": "ângulo de preço", "confidence": 0.5},
    ], winner="luna")
    assert {c["agent"]: c["outcome"] for c in res["consequences"]} == {"luna": "win", "rex": "loss"}
    luna = SelfModel(store, "luna").load()
    rex = SelfModel(store, "rex").load()
    assert any("venceu" in w for w in luna["recent"]["wins"])
    assert any("perdeu" in e for e in rex["recent"]["errors"])


def test_winning_stance_promoted_with_margin():
    store = InMemoryStore()
    Debate(store).resolve("q", [
        {"agent": "luna", "stance": "X é melhor", "confidence": 0.85},
        {"agent": "rex", "stance": "Y", "confidence": 0.4},
    ], winner="luna")
    top = WorldInsights(store).top_for("dev")              # a third agent now knows
    assert any("X é melhor" in m.content for m in top)


def test_not_promoted_when_margin_thin():
    store = InMemoryStore()
    res = Debate(store).resolve("q", [
        {"agent": "luna", "stance": "X", "confidence": 0.55},
        {"agent": "rex", "stance": "Y", "confidence": 0.5},
    ], winner="luna")
    assert res["promoted"] is False                        # 0.55 below the promote bar


def test_not_promoted_when_skeptic_fails():
    store = InMemoryStore()
    res = Debate(store).resolve("q", [
        {"agent": "luna", "stance": "X", "confidence": 0.9},
        {"agent": "rex", "stance": "Y", "confidence": 0.3},
    ], winner="luna", skeptic_passed=False)
    assert res["promoted"] is False                        # skepticism vetoed promotion


def test_loser_belief_weakened():
    store = InMemoryStore()
    Debate(store).resolve("q", [
        {"agent": "luna", "stance": "certo", "confidence": 0.8},
        {"agent": "rex", "stance": "errado", "confidence": 0.7},
    ], winner="luna")
    rex = SelfModel(store, "rex").load()
    b = [x for x in rex["beliefs"] if x["text"] == "errado"]
    assert b and b[0]["confidence"] <= 0.5                 # 0.7 - 0.2
