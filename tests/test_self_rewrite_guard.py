"""Self-rewrite guard tests — run with: pytest. Offline.

The constitutional brake: classify changes (green/yellow/red), let an injected
guard veto, record the zone, and detect slow drift.
"""
from logica_mind.stores import InMemoryStore
from logica_mind.continuity import SelfModel, classify_self_change, zone_guard, SelfRewriteBlocked


def mk(guard=None, ns="astro"):
    return SelfModel(InMemoryStore(), ns, guard=guard)


def test_classify_green():
    prev = {"identity": "X", "direction": "d", "skills": {"copy": 0.5},
            "drives": {"coherence": 0.5, "legacy": 0.5}, "beliefs": []}
    nxt = {"identity": "X", "direction": "d", "skills": {"copy": 0.55},
           "drives": {"coherence": 0.5, "legacy": 0.5}, "beliefs": []}
    assert classify_self_change(prev, nxt)["zone"] == "green"


def test_classify_yellow_new_belief_and_direction():
    prev = {"identity": "X", "direction": "d", "drives": {}, "beliefs": []}
    nxt = {"identity": "X", "direction": "novo rumo", "drives": {},
           "beliefs": [{"text": "b1", "confidence": 0.8}]}
    d = classify_self_change(prev, nxt)
    assert d["zone"] == "yellow"
    assert any("direção" in r for r in d["reasons"])
    assert any("crença" in r for r in d["reasons"])


def test_classify_red_identity_change():
    prev = {"identity": "Sou o Astro", "beliefs": []}
    nxt = {"identity": "Sou outro", "beliefs": []}
    assert classify_self_change(prev, nxt)["zone"] == "red"


def test_guard_blocks_red_identity_rewrite():
    sm = mk(guard=zone_guard(block_zones=("red",)))
    sm.save({"identity": "Sou o Astro"})              # v1: identity from empty → not red
    raised = False
    try:
        sm.save({"identity": "Sou outro agente"})    # changing non-empty identity → red → veto
    except SelfRewriteBlocked as e:
        raised = True
        assert e.decision["zone"] == "red"
    assert raised
    assert sm.load()["identity"] == "Sou o Astro"    # unchanged, chain intact


def test_guard_allows_green_and_yellow():
    sm = mk(guard=zone_guard(block_zones=("red",)))
    sm.save({"skills": {"copy": 0.8}})                              # green
    sm.save({"beliefs": [{"text": "b1", "confidence": 0.9}]})       # yellow → allowed
    assert sm.load()["version"] == 2


def test_zone_recorded_in_version_metadata():
    store = InMemoryStore()
    sm = SelfModel(store, "astro")                    # no guard → red allowed but recorded
    sm.save({"identity": "Sou o Astro"})             # v1 (green)
    sm.save({"identity": "Mudei"})                    # v2 (red)
    m = store.get("astro", "self-model::astro::v2")
    assert (m.metadata or {}).get("zone") == "red"


def test_detect_drift():
    sm = mk()
    for c in (0.9, 0.5, 0.2, 0.1, 0.05):             # erode coherence over versions
        sm.save({"drives": {"coherence": c}})
    drift = sm.detect_drift(window=6, threshold=0.15)
    assert drift["drifting"] is True
    assert "coherence" in drift["eroded"]
