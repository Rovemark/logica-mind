"""Tests for Wave 8 moats: Ebbinghaus decay, surprise score, contested beliefs,
dream journal persistence, and the new MCP tools.
"""
import json
import math
import os
import tempfile
import time

import pytest

from logica_mind import LogicaMind
from logica_mind.stores.sqlite import SQLiteStore
from logica_mind.types import Memory, MemoryLayer, now_iso
from logica_mind.dreaming import save_dream, load_dreams, DreamReport


# ── helpers ──────────────────────────────────────────────────────────────────

def fresh_mind(path=":memory:") -> LogicaMind:
    return LogicaMind(namespace="test", store=SQLiteStore(path))


# ── last_recalled_at / touch ──────────────────────────────────────────────────

class TestLastRecalledAt:
    def test_touch_sets_last_recalled_at(self):
        mind = fresh_mind()
        mind.remember("The sky is blue", extract=False)
        mems_before = mind.store.all("test")
        assert len(mems_before) == 1
        assert mems_before[0].last_recalled_at is None

        mind.recall("sky")
        mems_after = mind.store.all("test")
        assert mems_after[0].last_recalled_at is not None

    def test_last_recalled_at_is_iso_string(self):
        mind = fresh_mind()
        mind.remember("Ocean is salty", extract=False)
        mind.recall("ocean")
        m = mind.store.all("test")[0]
        # Should be parseable ISO datetime ending in Z
        assert m.last_recalled_at.endswith("Z")

    def test_last_recalled_at_roundtrips_sqlite(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        try:
            mind = fresh_mind(path)
            mind.remember("Persistent fact", extract=False)
            mind.recall("persistent")
            # re-open store and verify column persisted
            mind2 = fresh_mind(path)
            m = mind2.store.all("test")[0]
            assert m.last_recalled_at is not None
        finally:
            os.unlink(path)


# ── surprise_score ────────────────────────────────────────────────────────────

class TestSurpriseScore:
    def test_no_supersede_no_surprise(self):
        mind = fresh_mind()
        created = mind.remember("Maya likes coffee", extract=False)
        assert created[0].surprise_score == 0.0

    def test_surprise_score_stored_in_db(self):
        """A memory that supersedes another should carry a surprise_score >= 0."""
        mind = fresh_mind()
        m1 = mind.remember("Maya likes coffee", extract=False, importance=0.8)[0]
        # manually supersede: create a new memory that references the old one
        from logica_mind.types import Memory
        m2 = Memory(
            content="Maya likes tea",
            namespace="test",
            layer=MemoryLayer.SEMANTIC,
            importance=0.8,
            metadata={"supersedes": m1.id},
            surprise_score=0.42,
        )
        mind.store.add([m2])
        stored = mind.store.get("test", m2.id)
        assert stored is not None
        assert abs(stored.surprise_score - 0.42) < 0.01

    def test_surprise_events_returns_only_positive_scores(self):
        mind = fresh_mind()
        # zero surprise
        mind.remember("Sky is blue", extract=False)
        # inject a surprised memory
        from logica_mind.types import Memory
        m = Memory(content="Sky is actually green", namespace="test",
                   layer=MemoryLayer.SEMANTIC, importance=0.7, surprise_score=0.55)
        mind.store.add([m])
        events = mind.surprise_events()
        assert all(e["surprise_score"] > 0 for e in events)
        assert any("green" in e["content"] for e in events)


# ── forget_curve ──────────────────────────────────────────────────────────────

class TestForgetCurve:
    def test_returns_list(self):
        mind = fresh_mind()
        mind.remember("A durable fact", extract=False)
        curve = mind.forget_curve()
        assert isinstance(curve, list)
        assert len(curve) == 1

    def test_fields_present(self):
        mind = fresh_mind()
        mind.remember("Important thing", extract=False)
        curve = mind.forget_curve()
        entry = curve[0]
        for field in ("id", "content", "current_retention", "projected_strength_7d", "days_since_recall"):
            assert field in entry, f"Missing field: {field}"

    def test_retention_between_0_and_1(self):
        mind = fresh_mind()
        mind.remember("Fact A", extract=False)
        mind.remember("Fact B", extract=False)
        for entry in mind.forget_curve():
            assert 0.0 <= entry["current_retention"] <= 1.0

    def test_halflife_affects_retention(self):
        mind = fresh_mind()
        mind.remember("Decaying fact", extract=False)
        curve_long = mind.forget_curve(days_halflife=365)[0]
        curve_short = mind.forget_curve(days_halflife=1)[0]
        # longer halflife → higher retention for newly created memories
        assert curve_long["current_retention"] >= curve_short["current_retention"]

    def test_apply_decays_importance(self):
        mind = fresh_mind()
        mind.remember("Rare fact", extract=False, importance=0.9)
        m_before = mind.store.all("test")[0]
        original_imp = m_before.importance
        # apply with a very short halflife to force decay
        mind.forget_curve(days_halflife=0.001, apply=True)
        m_after = mind.store.all("test")[0]
        assert m_after.importance <= original_imp

    def test_skips_graph_and_user_layers(self):
        mind = fresh_mind()
        from logica_mind.types import Memory
        mind.store.add([Memory(content="Graph edge", namespace="test", layer=MemoryLayer.GRAPH)])
        mind.store.add([Memory(content="User obs", namespace="test", layer=MemoryLayer.USER)])
        mind.remember("Semantic fact", extract=False)
        curve = mind.forget_curve()
        layers = {e["layer"] for e in curve}
        assert MemoryLayer.GRAPH.value not in layers
        assert MemoryLayer.USER.value not in layers


# ── contested_beliefs ─────────────────────────────────────────────────────────

class TestContestedBeliefs:
    def test_no_supersede_no_contested(self):
        mind = fresh_mind()
        mind.remember("Maya is tall", extract=False, importance=0.9)
        assert mind.contested_beliefs() == []

    def test_low_confidence_not_contested(self):
        mind = fresh_mind()
        m1 = mind.remember("X is true", extract=False, importance=0.3)[0]
        from logica_mind.types import Memory
        m2 = Memory(content="X is false", namespace="test", layer=MemoryLayer.SEMANTIC,
                    importance=0.8, metadata={"supersedes": m1.id})
        mind.store.add([m2])
        # threshold 0.65: m1 importance 0.3 < threshold → not contested
        result = mind.contested_beliefs(confidence_threshold=0.65)
        assert result == []

    def test_both_high_confidence_is_contested(self):
        mind = fresh_mind()
        m1 = mind.remember("Revenue is 100k", extract=False, importance=0.9)[0]
        from logica_mind.types import Memory
        m2 = Memory(content="Revenue is 200k", namespace="test", layer=MemoryLayer.SEMANTIC,
                    importance=0.85, metadata={"supersedes": m1.id})
        mind.store.add([m2])
        result = mind.contested_beliefs(confidence_threshold=0.65)
        assert len(result) == 1
        assert "current" in result[0]
        assert "superseded" in result[0]
        assert result[0]["confidence_new"] >= 0.65
        assert result[0]["confidence_old"] >= 0.65


# ── dream journal ─────────────────────────────────────────────────────────────

class TestDreamJournal:
    def test_save_and_load_dream(self):
        with tempfile.TemporaryDirectory() as d:
            db_path = os.path.join(d, "test.db")
            store = SQLiteStore(db_path)
            report = DreamReport(episodic_processed=5, distilled=3, reinforced=2,
                                  forgotten=1, namespace="test")
            save_dream(report, store)
            loaded = load_dreams(store)
            assert len(loaded) == 1
            assert loaded[0]["distilled"] == 3
            assert loaded[0]["namespace"] == "test"

    def test_namespace_filter(self):
        with tempfile.TemporaryDirectory() as d:
            db_path = os.path.join(d, "test.db")
            store = SQLiteStore(db_path)
            save_dream(DreamReport(namespace="research", distilled=5), store)
            save_dream(DreamReport(namespace="marketing", distilled=2), store)
            research_only = load_dreams(store, namespace="research")
            assert all(r["namespace"] == "research" for r in research_only)
            assert len(research_only) == 1

    def test_capped_at_200(self):
        with tempfile.TemporaryDirectory() as d:
            db_path = os.path.join(d, "test.db")
            store = SQLiteStore(db_path)
            for _ in range(210):
                save_dream(DreamReport(namespace="test"), store)
            loaded = load_dreams(store, limit=300)
            assert len(loaded) <= 200

    def test_in_memory_store_no_file(self):
        store = SQLiteStore(":memory:")
        report = DreamReport(namespace="test")
        # should not raise, just silently skip
        save_dream(report, store)
        loaded = load_dreams(store)
        assert loaded == []

    def test_dream_report_timestamp(self):
        r = DreamReport()
        assert r.timestamp.endswith("Z")
        # parseable
        from datetime import datetime
        datetime.fromisoformat(r.timestamp.replace("Z", "+00:00"))


# ── MCP tool definitions present ─────────────────────────────────────────────

class TestMCPTools:
    def test_new_tools_in_tool_list(self):
        from logica_mind.mcp_server import TOOLS
        names = {t["name"] for t in TOOLS}
        for expected in ("lm_forget_about", "lm_forget_curve",
                         "lm_contested_beliefs", "lm_surprise_events", "lm_dream"):
            assert expected in names, f"Missing MCP tool: {expected}"

    def test_lm_dream_dispatch(self):
        mind = fresh_mind()
        from logica_mind.mcp_server import MCPServer
        srv = MCPServer(mind)
        result = srv._dispatch("lm_dream", {})
        assert "distilled" in result
        assert "forgotten" in result

    def test_lm_forget_curve_dispatch(self):
        mind = fresh_mind()
        mind.remember("A fact worth forgetting", extract=False)
        from logica_mind.mcp_server import MCPServer
        srv = MCPServer(mind)
        result = srv._dispatch("lm_forget_curve", {"limit": 10})
        assert isinstance(result, list)

    def test_lm_contested_dispatch(self):
        # seed a genuine contested belief through the real UPDATE path so the
        # MCP seam returns actual data, not just an empty list
        mind = fresh_mind()
        [old] = mind.remember("Capital is 100k.", extract=False, importance=0.9)
        mind.extractor = _UpdatingExtractor(old.id, "Capital is 500k instead.")
        mind.remember("update")
        from logica_mind.mcp_server import MCPServer
        result = MCPServer(mind)._dispatch("lm_contested_beliefs", {})
        assert isinstance(result, list) and len(result) >= 1
        assert "100k" in result[0]["superseded"]["content"]

    def test_lm_surprise_events_dispatch(self):
        mind = fresh_mind()
        [old] = mind.remember("Plan is A.", extract=False, importance=0.9)
        mind.extractor = _UpdatingExtractor(old.id, "Plan is totally Z now.")
        mind.remember("update")
        from logica_mind.mcp_server import MCPServer
        result = MCPServer(mind)._dispatch("lm_surprise_events", {})
        assert isinstance(result, list) and len(result) >= 1
        assert all(e["surprise_score"] > 0 for e in result)

    def test_lm_forget_about_dispatch(self):
        mind = fresh_mind()
        mind.remember("Maya is a founder", extract=False)
        from logica_mind.mcp_server import MCPServer
        srv = MCPServer(mind)
        result = srv._dispatch("lm_forget_about", {"entity": "Maya"})
        assert "deleted" in result
        assert result["deleted"] >= 0


# ── M5/M2: surprise_score + contested_beliefs through the REAL remember() path ──

from logica_mind.extract import Extractor, Fact, ExtractOp


class _UpdatingExtractor(Extractor):
    """Emits an UPDATE that supersedes a known target_id — drives the real path
    that production hits (vs hand-injecting surprise_score/supersedes)."""
    def __init__(self, target_id, new_content):
        self.target_id = target_id
        self.new_content = new_content

    def extract(self, text, existing):
        return [Fact(content=self.new_content, op=ExtractOp.UPDATE, target_id=self.target_id, importance=0.85)]


class TestRealUpdatePath:
    def test_surprise_score_computed_on_real_update(self):
        from logica_mind._vector import cosine
        mind = fresh_mind()
        [old] = mind.remember("Revenue this year is 100k.", extract=False, importance=0.9)
        new_text = "Revenue this year is 900k — a totally different figure."
        mind.extractor = _UpdatingExtractor(old.id, new_text)
        [new] = mind.remember("New data came in.")
        # surprise_score must equal old.importance × cosine_distance (not a constant,
        # not the raw importance) — pin the actual formula so a regression is caught
        expected = round(0.9 * max(0.0, 1.0 - cosine(new.embedding, old.embedding)), 4)
        assert new.surprise_score == expected
        assert 0.0 < new.surprise_score < 0.9      # genuinely between no-op and raw-importance
        # and it's persisted so surprise_events surfaces it
        events = mind.surprise_events()
        assert any(e["content"].startswith("Revenue this year is 900k") for e in events)

    def test_contested_beliefs_real_update_path(self):
        """The regression: old row is hard-deleted on UPDATE, so contested_beliefs
        must read the superseded snapshot from metadata — this failed before."""
        mind = fresh_mind()
        [old] = mind.remember("The deploy target is AWS.", extract=False, importance=0.9)
        mind.extractor = _UpdatingExtractor(old.id, "The deploy target is GCP instead.")
        mind.remember("Switched clouds.")
        # the old row is gone from the store...
        assert mind.store.get(mind.namespace, old.id) is None
        # ...but contested_beliefs still surfaces the conflict via the snapshot
        contested = mind.contested_beliefs(confidence_threshold=0.65)
        assert len(contested) == 1
        assert "AWS" in contested[0]["superseded"]["content"]
        assert "GCP" in contested[0]["current"]["content"]
        assert contested[0]["confidence_old"] >= 0.65
        assert contested[0]["confidence_new"] >= 0.65

    def test_superseded_snapshot_persisted_in_metadata(self):
        mind = fresh_mind()
        [old] = mind.remember("Pricing is $9/mo.", extract=False, importance=0.8)
        mind.extractor = _UpdatingExtractor(old.id, "Pricing is $19/mo now.")
        [new] = mind.remember("Price change.")
        snap = (new.metadata or {}).get("superseded_belief")
        assert snap is not None
        assert "9/mo" in snap["content"]
        assert snap["importance"] >= 0.65


# ── M4: forget_curve(apply=True) genuinely decays an OLD memory in a real DB ────

class TestForgetCurveApply:
    def test_apply_strictly_decays_old_memory_and_persists(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "fc.db")
            mind = LogicaMind(namespace="t", store=SQLiteStore(path))
            [m] = mind.remember("An old belief.", extract=False, importance=0.9)
            # backdate it ~100 days so retention is well below 1.0
            import datetime as _dt
            old_iso = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=100)).strftime("%Y-%m-%dT%H:%M:%SZ")
            m.created_at = old_iso
            mind.store.add([m])
            before = mind.store.get("t", m.id).importance
            # apply decay with a short halflife → strict decrease
            mind.forget_curve(days_halflife=30, apply=True)
            after_mem = mind.store.get("t", m.id)
            assert after_mem.importance < before          # STRICT, not <=
            # reopen the DB and confirm the decay persisted
            mind2 = LogicaMind(namespace="t", store=SQLiteStore(path))
            assert mind2.store.get("t", m.id).importance < before

    def test_apply_false_does_not_mutate(self):
        mind = fresh_mind()
        [m] = mind.remember("A belief.", extract=False, importance=0.9)
        mind.forget_curve(days_halflife=1, apply=False)
        assert mind.store.get(mind.namespace, m.id).importance == 0.9

    def test_apply_matches_ebbinghaus_arithmetic(self):
        """Pin the decay math itself (the strict-decrease test lands on the 0.05
        floor, blind to the formula). With halflife=200 the result sits strictly
        between the floor and the original, so the exponential is actually tested."""
        import math, datetime as _dt
        mind = fresh_mind()
        [m] = mind.remember("Aging belief.", extract=False, importance=0.9)
        age_days = 100.0
        old_iso = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=age_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        m.created_at = old_iso
        mind.store.add([m])
        mind.forget_curve(days_halflife=200, apply=True)
        got = mind.store.get(mind.namespace, m.id).importance
        expected = max(0.05, 0.9 * math.exp(-age_days / 200.0))   # ~0.636
        assert 0.05 < got < 0.9                                    # not floored, not unchanged
        assert abs(got - expected) < 0.02                         # matches the arithmetic


# ── M3: HTTP-level coverage of the new write endpoints + L3 400 handling ───────

def _spawn_server(root, port=0):
    """Bind an ephemeral port (0) and return (srv, port). Caller MUST call
    srv.shutdown() THEN srv.server_close() — shutdown() alone returns before the
    listening socket is released, so a fixed port races into EADDRINUSE."""
    import threading
    from http.server import ThreadingHTTPServer
    from logica_mind.web.server import make_handler
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(root))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def _close_server(srv):
    srv.shutdown()
    srv.server_close()


class TestWebWriteEndpoints:
    def _server(self):
        root = LogicaMind(namespace="proj", store=SQLiteStore(":memory:"))
        root.remember("Maya founded the company.", extract=False)
        srv, port = _spawn_server(root)
        return root, srv, port

    @staticmethod
    def _post(port, path, body):
        import urllib.request, urllib.error
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}", method="POST",
            data=json.dumps(body).encode(), headers={"content-type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode() or "{}")

    @staticmethod
    def _get(port, path):
        import urllib.request, urllib.error
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}") as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode() or "{}")

    def test_forget_about_http(self):
        root, srv, port = self._server()
        try:
            code, d = self._post(port, "/api/forget_about", {"namespace": "proj", "entity": "Maya"})
            assert code == 200 and d["deleted"] >= 1
            # missing entity → 400
            code, _ = self._post(port, "/api/forget_about", {"namespace": "proj", "entity": ""})
            assert code == 400
        finally:
            _close_server(srv)

    def test_clear_endpoint_http(self):
        root, srv, port = self._server()
        try:
            root.remember("ephemeral note", extract=False)
            code, d = self._post(port, "/api/clear", {"namespace": "proj", "layer": "semantic"})
            assert code == 200 and d["ok"] is True
            # bad layer → clean 400, not 500
            code, _ = self._post(port, "/api/clear", {"namespace": "proj", "layer": "garbage"})
            assert code == 400
            # bad older_than_days → 400
            code, _ = self._post(port, "/api/clear", {"namespace": "proj", "older_than_days": "notanum"})
            assert code == 400
            # nothing specified → 400
            code, _ = self._post(port, "/api/clear", {"namespace": "proj"})
            assert code == 400
        finally:
            _close_server(srv)

    def test_sessions_rename_http(self):
        root, srv, port = self._server()
        try:
            code, d = self._post(port, "/api/sessions/rename", {"session_id": "sess1", "name": "My chat"})
            assert code == 200 and d["name"] == "My chat"
            code, _ = self._post(port, "/api/sessions/rename", {"session_id": "", "name": ""})
            assert code == 400
        finally:
            _close_server(srv)

    def test_import_bundle_http_roundtrip(self):
        root, srv, port = self._server()
        try:
            # export a bundle from the live namespace, then import into a new one
            _, bundle = self._get(port, "/api/bundle?namespace=proj")
            code, d = self._post(port, "/api/import-bundle", {"namespace": "restored", "bundle": bundle})
            assert code == 200 and d["imported"] >= 1
            _, mems = self._get(port, "/api/memories?namespace=restored")
            assert any("Maya" in m["content"] for m in mems["memories"])
        finally:
            _close_server(srv)

    def test_bad_query_param_returns_400_not_500(self):
        root, srv, port = self._server()
        try:
            assert self._get(port, "/api/recall?namespace=proj&q=x&limit=abc")[0] == 400
            assert self._get(port, "/api/memories?namespace=proj&layer=garbage")[0] == 400
            assert self._get(port, "/api/forget_curve?namespace=proj&halflife=xx")[0] == 400
            assert self._get(port, "/api/contested?namespace=proj&threshold=zz")[0] == 400
        finally:
            _close_server(srv)


# ── M1: moat read endpoints aggregate across namespaces in __all__ mode ────────

class TestAllNamespaceAggregation:
    def test_stale_aggregates_in_all_mode(self):
        import urllib.request
        root = LogicaMind(namespace="a", store=SQLiteStore(":memory:"))
        # two namespaces, each with an old never-recalled belief
        import datetime as _dt
        old_iso = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
        for nm, txt in [("a", "alpha old belief"), ("b", "beta old belief")]:
            sub = root.for_namespace(nm)
            [mm] = sub.remember(txt, extract=False, importance=0.5)
            mm.created_at = old_iso
            sub.store.add([mm])
        srv, port = _spawn_server(root)
        try:
            d = json.load(urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/stale?namespace=__all__&min_age_days=30"))
            contents = {s["content"] for s in d["stale"]}
            # BOTH namespaces' stale beliefs present (not just the fallback one)
            assert "alpha old belief" in contents
            assert "beta old belief" in contents
            assert all("namespace" in s for s in d["stale"])
        finally:
            _close_server(srv)


# ── Structured session/run records (generic, framework-free) ───────────────────

class TestSessionRecords:
    def test_record_session_stores_header_and_contributions(self):
        mind = fresh_mind()
        rec = mind.record_session(
            title="Ship the installer",
            participants=[
                {"name": "Ada", "role": "analyst", "contribution": "Strategic read.", "metrics": {"score": 100}},
                {"name": "Sam", "role": "engineer", "contribution": "Built the DB step."},
            ],
            status="completed",
            metrics={"tokens": 28713, "cost_usd": 0.2058, "score": 95},
            links={"daily": "2026-04-09"},
        )
        md = rec.metadata
        assert md["record"] is True
        assert md["title"] == "Ship the installer"
        assert md["metrics"]["tokens"] == 28713
        assert [p["name"] for p in md["participants"]] == ["Ada", "Sam"]
        # contributions stored as separate linked memories sharing the session id
        sid = md["session"]
        from logica_mind.types import MemoryLayer
        contribs = [m for m in mind.store.all("test", [MemoryLayer.EPISODIC])
                    if "contribution" in (m.tags or []) and (m.metadata or {}).get("session") == sid]
        assert len(contribs) == 2

    def test_auto_session_id(self):
        mind = fresh_mind()
        rec = mind.record_session(title="No id given")
        assert (rec.metadata or {}).get("session", "").startswith("sess_")

    def test_session_record_getter_pairs_contributions(self):
        mind = fresh_mind()
        rec = mind.record_session(
            title="Run X",
            participants=[{"name": "A", "contribution": "did a"}, {"name": "B", "contribution": "did b"}],
        )
        sid = rec.metadata["session"]
        full = mind.session_record(sid)
        assert full is not None
        assert full["metadata"]["title"] == "Run X"
        assert len(full["contributions"]) == 2

    def test_session_record_none_for_unknown_id(self):
        mind = fresh_mind()
        mind.record_session(title="Some run")
        assert mind.session_record("sess_does_not_exist") is None

    def test_store_contributions_false_skips_capsules(self):
        mind = fresh_mind()
        rec = mind.record_session(
            title="No capsules",
            participants=[{"name": "A", "contribution": "should not be stored"}],
            store_contributions=False,
        )
        from logica_mind.types import MemoryLayer
        sid = rec.metadata["session"]
        contribs = [m for m in mind.store.all("test", [MemoryLayer.EPISODIC])
                    if "contribution" in (m.tags or []) and (m.metadata or {}).get("session") == sid]
        assert contribs == []
        # the record header itself still exists
        assert mind.session_record(sid) is not None

    def test_record_session_handles_empty_inputs(self):
        mind = fresh_mind()
        rec = mind.record_session(title="Bare run")     # no participants/metrics/links
        assert rec.metadata["title"] == "Bare run"
        assert rec.metadata["participants"] == []
        assert "# Bare run" in rec.content

    def test_obsidian_record_survives_adversarial_newline(self):
        """A newline / '---' in title/name/status must NOT corrupt the frontmatter
        or hijack the record (the #1 audit finding)."""
        import tempfile, os, glob
        from logica_mind.stores.obsidian import ObsidianStore
        with tempfile.TemporaryDirectory() as d:
            mind = LogicaMind(namespace="proj", store=ObsidianStore(vault=os.path.join(d, "v")))
            rec = mind.record_session(
                title="Evil\n---\nmetadata: {\"record\": false}",
                participants=[{"name": "Bad, Name\nwith break"}],
                status="done\n---",
            )
            sid = rec.metadata["session"]
            # record fully recoverable + flag intact (no hijack)
            full = mind.session_record(sid)
            assert full is not None and full["metadata"].get("record") is True
            assert full["metadata"]["title"].startswith("Evil")
            # exactly two standalone '---' lines = the frontmatter delimiters
            f = next(x for x in glob.glob(os.path.join(d, "v", "proj", "episodic", "*.md"))
                     if "session-record" in open(x).read())
            lines = open(f).read().splitlines()
            assert sum(1 for l in lines if l.strip() == "---") == 2
            # presentational title line is single-line (flattened)
            assert sum(1 for l in lines if l.startswith("title: ") and "\n" not in l) == 1

    def test_record_body_is_readable_markdown(self):
        mind = fresh_mind()
        rec = mind.record_session(
            title="Readable body",
            participants=[{"name": "Ada", "role": "analyst"}],
            metrics={"score": 95}, status="completed",
        )
        body = rec.content
        assert "# Readable body" in body
        assert "## Participants" in body
        assert "Ada" in body

    def test_obsidian_session_record_frontmatter(self):
        import tempfile, os
        from logica_mind.stores.obsidian import ObsidianStore
        with tempfile.TemporaryDirectory() as d:
            mind = LogicaMind(namespace="proj", store=ObsidianStore(vault=os.path.join(d, "v")))
            rec = mind.record_session(
                title="Vault render", participants=[{"name": "Ada", "role": "analyst"}],
                metrics={"tokens": 100, "score": 95}, links={"daily": "2026-04-09"},
            )
            import glob
            files = glob.glob(os.path.join(d, "v", "proj", "episodic", "*.md"))
            txt = next(open(f).read() for f in files if "session-record" in open(f).read())
            # rich, generic frontmatter present
            assert "type: session" in txt
            assert "title: Vault render" in txt
            assert "participants: [Ada]" in txt
            assert "metric_tokens: 100" in txt
            assert "link_daily: 2026-04-09" in txt
            # and it still round-trips back into a Memory (JSON metadata preserved)
            back = mind.store.get("proj", rec.id)
            assert back is not None and back.metadata.get("record") is True

    def test_mcp_record_session_dispatch(self):
        mind = fresh_mind()
        from logica_mind.mcp_server import MCPServer
        srv = MCPServer(mind)
        result = srv._dispatch("lm_record_session", {
            "title": "MCP run", "participants": [{"name": "Sam", "role": "engineer"}],
            "metrics": {"tokens": 50},
        })
        assert result["ok"] is True and result["session"]

    def test_record_session_in_tool_list(self):
        from logica_mind.mcp_server import TOOLS
        assert any(t["name"] == "lm_record_session" for t in TOOLS)

    def test_web_record_endpoint_and_session_getter(self):
        import urllib.request, json as _json
        root = LogicaMind(namespace="proj", store=SQLiteStore(":memory:"))
        srv, port = _spawn_server(root)
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/record", method="POST",
                data=_json.dumps({
                    "namespace": "proj", "title": "Web run",
                    "participants": [{"name": "Ada", "role": "analyst", "contribution": "x"}],
                    "metrics": {"tokens": 10},
                }).encode(), headers={"content-type": "application/json"})
            with urllib.request.urlopen(req) as r:
                d = _json.load(r)
            assert d["ok"] and d["session"]
            # the session appears in /api/sessions with the record summary
            sd = _json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/sessions?namespace=proj"))
            rec_sessions = [s for s in sd["sessions"] if s.get("record")]
            assert rec_sessions and rec_sessions[0]["record"]["title"] == "Web run"
            assert rec_sessions[0]["name"] == "Web run"     # record title becomes the name
            # and /api/session returns the full structured record
            full = _json.load(urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/session?namespace=proj&id={d['session']}"))
            assert full["record"]["metadata"]["title"] == "Web run"
            # non-existent session id → 200 with record None (the guard path)
            none_resp = _json.load(urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/session?namespace=proj&id=sess_does_not_exist"))
            assert none_resp["record"] is None
        finally:
            _close_server(srv)
