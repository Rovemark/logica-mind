"""Spotlight must find literal identifiers independently of semantic popularity."""
import tempfile
import unittest
import json
import os
from unittest.mock import patch
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from logica_mind import Memory, LogicaMind
from logica_mind.types import SearchResult
from logica_mind.stores import InMemoryStore, SQLiteStore, MultiStore
from logica_mind.stores.privacy import PrivacyStore
from logica_mind.web.server import _spotlight_memories, make_handler


class SpotlightLiteralTests(unittest.TestCase):
    marker = "qa-linux-mind-20261022-41"

    def memory(self, content=None, **kw):
        return Memory(content=content or self.marker, namespace="qa", **kw)

    def test_literal_survives_semantic_top_n_and_namespace_merge(self):
        store = InMemoryStore()
        literal = self.memory(metadata={"ownerId": "qa"})
        other = self.memory("qa linux unrelated popular report", access_count=10000)
        store.add([literal, other])
        calls = []
        mind = SimpleNamespace(store=store, recall_across=lambda q, **kw:
                               calls.append(kw) or [SearchResult(other, 8.0, {})])
        rows = _spotlight_memories(mind, self.marker, 1, {"ownerId": "qa"})
        self.assertEqual([r.memory.id for r in rows], [literal.id])
        self.assertEqual(calls, [], "a full literal result does not need semantic provider work")

    def test_no_literal_keeps_semantic_order_without_duplicate(self):
        store = InMemoryStore()
        note = self.memory("blue ocean")
        store.add([note])
        hit = SearchResult(note, 0.8, {})
        mind = SimpleNamespace(store=store, recall_across=lambda q, **kw: [hit])
        self.assertEqual(_spotlight_memories(mind, "turquoise", 6), [hit])
        self.assertEqual(len(_spotlight_memories(mind, "blue", 6)), 1)

    def test_semantic_fallback_receives_the_same_owner_project_filter(self):
        captured = []
        mind = SimpleNamespace(store=InMemoryStore(), recall_across=lambda q, **kw:
                               captured.append(kw) or [])
        _spotlight_memories(mind, "not-present", 6, {"ownerId": "qa", "project": "qa-project"})
        self.assertEqual(captured[0]["metadata_filter"]["ownerId"], "qa")
        self.assertEqual(captured[0]["metadata_filter"]["project"], "qa-project")
        self.assertIn("$not", captured[0]["metadata_filter"])

    def test_private_namespace_other_owner_self_model_and_alias_stay_hidden(self):
        raw = InMemoryStore()
        good = self.memory(metadata={"ownerId": "qa"})
        raw.add([good, self.memory(metadata={"ownerId": "other"}),
                 Memory(content=self.marker, namespace="private-cli-secret-qa", metadata={"ownerId": "qa"}),
                 self.memory(tags=["alias"], metadata={"ownerId": "qa"}),
                 self.memory(metadata={"ownerId": "qa", "continuity": "self-model"})])
        view = PrivacyStore(raw)
        mind = SimpleNamespace(store=view, recall_across=lambda q, **kw: [])
        self.assertEqual([r.memory.id for r in _spotlight_memories(mind, self.marker, 10, {"ownerId": "qa"})], [good.id])
        with self.assertRaises(ValueError):
            view.literal_matches("private-cli-secret-qa", self.marker)

    def test_literal_wildcards_and_empty_query_do_not_match_everything(self):
        store = InMemoryStore()
        exact = self.memory("QA!%_identifier")
        store.add([exact, self.memory("QAxxxxidentifier")])
        self.assertEqual([m.id for m in store.literal_matches("qa", "!%_")], [exact.id])
        self.assertEqual(store.literal_matches("qa", "  "), [])

    def test_sqlite_old_literal_ignores_recency_window_and_filters_before_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SQLiteStore(str(Path(folder) / "qa.sqlite"), max_candidates=1)
            try:
                old = self.memory("QA!%_identifier", created_at="2000-01-01T00:00:00Z", metadata={"ownerId": "qa"})
                wrong = self.memory("QA!%_identifier", metadata={"ownerId": "other"})
                hidden = self.memory("QA!%_identifier", metadata={"ownerId": "qa", "kind": "self_model"})
                store.add([old, wrong, hidden, self.memory("unrelated")])
                store.all = lambda *a, **kw: self.fail("SQL lookup must not materialize all memories")
                rows = store.literal_matches("qa", "!%_", limit=1,
                                             metadata_filter={"ownerId": "qa", "$not": {"kind": "self_model"}})
                self.assertEqual([m.id for m in rows], [old.id])
            finally:
                store.close()

    def test_multi_store_lookup_is_bounded_and_deduplicated(self):
        one, two = InMemoryStore(), InMemoryStore()
        note = self.memory()
        one.add([note]); two.add([note])
        self.assertEqual([m.id for m in MultiStore([one, two]).literal_matches("qa", self.marker, limit=1)], [note.id])

    def test_optional_mirror_outage_does_not_hide_canonical_lookup(self):
        one, two = InMemoryStore(), InMemoryStore()
        note = self.memory()
        one.add([note])
        def unavailable(*args, **kwargs):
            raise OSError("synthetic mirror unavailable")
        two.literal_matches = unavailable
        self.assertEqual([m.id for m in MultiStore([one, two], require_primary=True)
                          .literal_matches("qa", self.marker)], [note.id])
        with self.assertRaisesRegex(RuntimeError, "Canonical"):
            MultiStore([two, one], require_primary=True).literal_matches("qa", self.marker)
        with self.assertRaisesRegex(RuntimeError, "No memory store"):
            MultiStore([two]).literal_matches("qa", self.marker)

    def test_sqlite_unicode_lists_null_and_not_are_filtered_before_limit(self):
        store = SQLiteStore(":memory:")
        try:
            good = self.memory("AÇÃO !%_ literal", metadata={"ownerId": "qa", "active": True})
            store.add([good, self.memory("ação !%_ literal", metadata={"ownerId": "other"})])
            rows = store.literal_matches("qa", "ação !%_", limit=1,
                metadata_filter={"ownerId": ["qa", "also-qa"], "active": True,
                                 "missing": None, "$not": {"ownerId": "other"}})
            self.assertEqual([m.id for m in rows], [good.id])
            self.assertEqual(store.literal_matches("qa", "ação", metadata_filter={"ownerId": []}), [])
        finally:
            store.close()

    def test_postgres_uses_parameterized_literal_query_and_owner_before_limit(self):
        from logica_mind.stores.postgres import PostgresStore
        store = object.__new__(PostgresStore)
        captured = []
        store._q = lambda sql, params: captured.append((sql, params)) or []
        self.assertEqual(store.literal_matches("qa", "x!%_' OR TRUE", limit=500,
                                              metadata_filter={"ownerId": "qa"}), [])
        sql, params = captured[0]
        self.assertNotIn("OR TRUE", sql)
        self.assertIn("ILIKE %s ESCAPE '!'", sql)
        self.assertIn("metadata @>", sql)
        projection = sql.split(" FROM ")[0]
        self.assertIn("NULL::bytea AS embedding", projection)
        self.assertNotIn("embedding", projection.replace("NULL::bytea AS embedding", ""))
        self.assertEqual(params[0], "qa")
        self.assertEqual(params[1], "%x!!!%!_' OR TRUE%")
        self.assertEqual(params[-1], 50)

    @patch.dict(os.environ, {"LOGICAOS_MULTIUSER": "1"})
    def test_real_http_search_returns_literal_without_private_or_other_owner(self):
        store = InMemoryStore()
        good = self.memory(metadata={"ownerId": "qa"})
        store.add([good, self.memory(metadata={"ownerId": "other"}),
                   Memory(content=self.marker, namespace="private-cli-secret-qa",
                          metadata={"ownerId": "qa"})])
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(
            LogicaMind(namespace="qa", store=store), token="isolated-test-token"))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        conn = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        try:
            path = "/api/search?ownerId=qa&q=" + self.marker
            auth = {"Authorization": "Bearer isolated-test-token"}
            conn.request("GET", path, headers=auth)
            denied = conn.getresponse()
            self.assertEqual(denied.status, 403)
            denied.read()
            conn.request("GET", path, headers={**auth, "X-LogicaOS-Company-Mind": "1"})
            response = conn.getresponse()
            body = json.loads(response.read())
            self.assertEqual(response.status, 200)
            self.assertEqual([row["memory"]["id"] for row in body["memories"]], [good.id])
        finally:
            conn.close()
            server.shutdown(); server.server_close(); thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
