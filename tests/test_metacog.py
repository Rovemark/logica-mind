"""Metacognition tests — run with: pytest. Offline."""
from logica_mind.stores import InMemoryStore
from logica_mind.continuity import SelfModel, Metacog


def fleet():
    store = InMemoryStore()
    SelfModel(store, "luna").save({"skills": {"copy": 0.9, "ads": 0.6}})
    SelfModel(store, "dev").save({"skills": {"python": 0.85, "infra": 0.5}})
    SelfModel(store, "rex").save({"skills": {"copy": 0.4},
                                  "beliefs": [{"text": "vendas exige follow-up", "confidence": 0.8}]})
    return store


def test_assess_known_vs_unknown():
    mc = Metacog(fleet())
    assert mc.assess("luna", "copy")["known"] is True
    assert mc.assess("dev", "copy")["known"] is False     # dev has no copy skill


def test_who_knows_ranks_and_thresholds():
    mc = Metacog(fleet())
    who = mc.who_knows("copy")
    assert who[0]["agent"] == "luna"                       # 0.9 is the strongest
    assert all(w["agent"] != "rex" for w in who)           # rex copy 0.4 < 0.6 bar


def test_route_to_when_incompetent():
    r = Metacog(fleet()).route("dev", "copy")
    assert r["known"] is False and r["route_to"] == "luna"


def test_route_none_when_competent():
    assert Metacog(fleet()).route("luna", "copy")["route_to"] is None


def test_belief_floor_for_unknown_skill():
    mc = Metacog(fleet())
    # rex has no "vendas" skill but a belief mentioning it → small non-zero floor
    a = mc.assess("rex", "vendas")
    assert 0 < a["competence"] < 0.6 and a["known"] is False


def test_skips_world_and_self_model_internal_namespaces():
    store = fleet()
    from logica_mind.continuity import WorldInsights
    WorldInsights(store).publish("luna", "x", confidence=0.9)
    who = Metacog(store).who_knows("copy")
    assert all(not w["agent"].startswith("__") for w in who)


def test_marker_levels():
    mc = Metacog(fleet())
    assert mc.assess("luna", "copy")["marker"] == "alta"
    assert mc.assess("dev", "copy")["marker"] == "baixa"
