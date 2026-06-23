"""Self-model tests — run with: pytest

All offline: InMemoryStore, no API keys. Covers the Phase -1 guarantees:
versioning, EMA (evolve-not-jump), no-forgetting, hash-chain integrity,
tamper detection, restore, belief dedup/reweight and the prompt surface.
"""
import json

from logica_mind.stores import InMemoryStore
from logica_mind.continuity import SelfModel


def mk(ns="astro"):
    return SelfModel(InMemoryStore(), ns)


def test_save_load_and_version_increment():
    sm = mk()
    assert sm.load()["version"] == 0                      # fresh skeleton
    s1 = sm.save({"direction": "ângulos de oferta", "skills": {"copy": 0.8}})
    assert s1["version"] == 1
    s2 = sm.save({"skills": {"copy": 1.0}})
    assert s2["version"] == 2
    assert sm.load()["version"] == 2


def test_ema_evolves_not_jumps():
    sm = mk()
    sm.save({"skills": {"copy": 0.8}})                    # first → adopts 0.8
    assert sm.load()["skills"]["copy"] == 0.8
    sm.save({"skills": {"copy": 1.0}})                    # EMA: 0.8*0.7 + 1.0*0.3
    assert sm.load()["skills"]["copy"] == 0.86            # evolved, did NOT jump to 1.0


def test_no_forgetting_history_kept():
    sm = mk()
    for i in range(5):
        sm.save({"direction": f"d{i}"})
    assert [v["version"] for v in sm.versions()] == [1, 2, 3, 4, 5]


def test_hash_chain_valid():
    sm = mk()
    for i in range(4):
        sm.save({"direction": f"d{i}", "skills": {"x": 0.1 * i}})
    ok, n, why = sm.verify_chain()
    assert ok and n == 4, why


def test_tamper_is_detected():
    store = InMemoryStore()
    sm = SelfModel(store, "astro")
    sm.save({"direction": "original"})
    sm.save({"direction": "second"})
    # surgically alter v1's content in the store, keeping its old hash field
    m = store.get("astro", "self-model::astro::v1")
    bad = json.loads(m.content)
    bad["direction"] = "HACKED"
    m.content = json.dumps(bad, ensure_ascii=False)
    store.add([m])
    ok, ver, why = sm.verify_chain()
    assert not ok and "tamper" in why.lower()


def test_belief_dedup_and_reweight():
    sm = mk()
    sm.save({"beliefs": [{"text": "user wants real photos", "confidence": 0.9}]})
    sm.save({"beliefs": [{"text": "user wants real photos", "confidence": 0.5}]})
    same = [b for b in sm.load()["beliefs"] if b["text"] == "user wants real photos"]
    assert len(same) == 1                                 # dedup by text
    assert same[0]["confidence"] == round(0.9 * 0.7 + 0.5 * 0.3, 3)


def test_recent_append_and_cap():
    sm = mk()
    for i in range(20):
        sm.save({"recent": {"errors": [f"e{i}"]}})
    errors = sm.load()["recent"]["errors"]
    assert len(errors) == 12                              # HOT_RECENT cap
    assert errors[0] == "e19"                             # newest first


def test_restore_brings_back_old_state_as_new_version():
    sm = mk()
    sm.save({"direction": "first", "skills": {"copy": 0.9}})    # v1
    sm.save({"direction": "drifted", "skills": {"copy": 0.1}})  # v2
    restored = sm.restore(1)                                    # → v3 == v1's state
    assert restored["version"] == 3
    assert restored["restored_from"] == 1
    assert restored["direction"] == "first"
    assert restored["skills"]["copy"] == 0.9                    # verbatim, not blended
    ok, _, why = sm.verify_chain()
    assert ok, why                                             # chain stays linear & valid


def test_format_for_prompt():
    sm = mk()
    sm.save({"direction": "x", "skills": {"copy": 0.8},
             "beliefs": [{"text": "b1", "confidence": 0.9}]})
    out = sm.format_for_prompt()
    assert "EU (astro" in out and "copy" in out and "b1" in out
