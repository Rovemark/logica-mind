"""Two-company mutation boundaries through real HTTP and the actual memory engine."""
import copy
import io
import json
import threading
import tempfile
from datetime import datetime, timezone, timedelta
import unittest
from contextlib import redirect_stderr
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from logica_mind.core import LogicaMind
from logica_mind.continuity import SelfModel
from logica_mind.stores import InMemoryStore
from logica_mind.types import Memory, MemoryLayer
from logica_mind.web.server import make_handler

OWNER = "company-a"
KEY = "synthetic-mutation-fixture-key"


class FixtureMind(LogicaMind):
    def __init__(self):
        self.namespace = "fixture"
        self.store = InMemoryStore()

    def for_namespace(self, namespace):
        result = copy.copy(self); result.namespace = namespace; return result

    def list_namespaces(self):
        return [{"namespace": "fixture"}]

    def _embed(self, text):
        return [1.0, 0.0]


class MemoryHttpMutationScopeTests(unittest.TestCase):
    def setUp(self):
        self.mind = FixtureMind()
        self.add("a", OWNER, "project-a")
        self.add("b", "company-b", "project-a")
        self.add("a-other-project", OWNER, "project-b")
        self.env = patch.dict("os.environ", {"LOGICAOS_MULTIUSER": "1", "LOGICAOS_OWNER_ID": OWNER})
        self.env.__enter__()
        self.stderr = redirect_stderr(io.StringIO()); self.stderr.__enter__()
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.mind, token=KEY))
        self.thread = threading.Thread(target=lambda: self.http.serve_forever(poll_interval=0.01), daemon=True)
        self.thread.start()

    def tearDown(self):
        self.http.shutdown(); self.http.server_close(); self.thread.join(timeout=3)
        self.stderr.__exit__(None, None, None); self.env.__exit__(None, None, None)

    def add(self, memory_id, owner, project):
        memory = Memory(id=memory_id, namespace="fixture", layer=MemoryLayer.SEMANTIC,
            content="Fixture entity alice", embedding=[1.0, 0.0], created_at="2020-01-01T00:00:00",
            metadata={"ownerId": owner, "project": project})
        self.mind.store.add([memory]); return memory

    def request(self, endpoint, *, _gateway=True, **fields):
        body = {"namespace": "fixture", "ownerId": OWNER, "metadata": {"ownerId": OWNER}, **fields}
        conn = HTTPConnection("127.0.0.1", self.http.server_port, timeout=3)
        try:
            headers = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
            if _gateway: headers["X-LogicaOS-Company-Mind"] = "1"
            conn.request("POST", "/api/" + endpoint, json.dumps(body), headers)
            response = conn.getresponse(); return response.status, json.loads(response.read())
        finally:
            conn.close()

    def test_clear_purge_layer_and_age_keep_other_owner_and_project(self):
        for fields in ({"purge_all": True}, {"layer": "semantic"}, {"older_than_days": 0}):
            with self.subTest(mode=next(iter(fields))):
                self.add("a", OWNER, "project-a")
                code, _ = self.request("clear", project="project-a", **fields)
                self.assertEqual(code, 200)
                self.assertIsNone(self.mind.store.get("fixture", "a"))
                self.assertIsNotNone(self.mind.store.get("fixture", "b"))
                self.assertIsNotNone(self.mind.store.get("fixture", "a-other-project"))

    def test_clear_missing_scope_or_non_boolean_purge_is_not_global(self):
        for fields in ({"ownerId": "", "metadata": {}, "purge_all": True}, {"purge_all": "false"}):
            self.assertIn(self.request("clear", **fields)[0], (400, 403))
        self.assertIsNotNone(self.mind.store.get("fixture", "b"))

    def test_import_materializes_authenticated_scope_not_nested_bundle_owner_aliases(self):
        memory = self.mind.store.get("fixture", "b").to_dict()
        memory["id"] = "new-import"
        memory["metadata"] = {"ownerId": "company-b", "owner_id": "company-b", "project": "project-b", "project_id": "project-b"}
        code, _ = self.request("import-bundle", project="project-a", bundle={"payload": {"memories": [memory]}})
        self.assertEqual(code, 200)
        imported = next(memory for memory in self.mind.store.all("fixture") if memory.metadata.get("importedId") == "new-import")
        self.assertNotEqual(imported.id, "new-import")
        self.assertEqual(imported.metadata["ownerId"], OWNER)
        self.assertEqual(imported.metadata["project"], "project-a")
        self.assertNotIn("owner_id", imported.metadata)
        self.assertNotIn("project_id", imported.metadata)

    def test_import_rejects_colliding_foreign_id_before_any_partial_write(self):
        existing = self.mind.store.get("fixture", "b")
        valid = existing.to_dict(); valid["id"] = "must-not-write"
        conflicting = existing.to_dict(); conflicting["content"] = "Must not replace foreign memory"
        code, _ = self.request("import-bundle", bundle={"payload": {"memories": [valid, conflicting]}})
        self.assertIn(code, (400, 403))
        self.assertIsNone(self.mind.store.get("fixture", "must-not-write"))
        self.assertEqual(self.mind.store.get("fixture", "b").metadata["ownerId"], "company-b")
        self.assertEqual(self.mind.store.get("fixture", "b").content, "Fixture entity alice")

    def test_import_cannot_replace_reserved_self_model_identity(self):
        model = SelfModel(self.mind.store, "fixture", metadata_scope={"ownerId": OWNER})
        model.save({"identity": "Original identity"})
        memory = self.mind.store.get("fixture", "self-model::fixture::current").to_dict()
        state = json.loads(memory["content"]); state["identity"] = "Forged identity"; memory["content"] = json.dumps(state)
        code, _ = self.request("import-bundle", bundle={"payload": {"memories": [memory]}})
        self.assertIn(code, (400, 403))
        self.assertEqual(model.load()["identity"], "Original identity")

    def test_http_forget_about_keeps_other_owner_and_project_including_all_namespaces(self):
        code, _ = self.request("forget_about", namespace="__all__", project="project-a", entity="alice")
        self.assertEqual(code, 200)
        self.assertIsNone(self.mind.store.get("fixture", "a"))
        self.assertIsNotNone(self.mind.store.get("fixture", "b"))
        self.assertIsNotNone(self.mind.store.get("fixture", "a-other-project"))

    def test_mcp_forget_pin_unpin_snooze_wake_cannot_mutate_foreign_ids(self):
        for name, args in (("lm_forget", {"id": "b"}), ("lm_pin", {"id": "b"}),
                           ("lm_pin", {"id": "b", "unpin": True}),
                           ("lm_snooze", {"id": "b", "until": "2099-01-01"}), ("lm_snooze", {"id": "b", "wake": True})):
            with self.subTest(tool=name):
                self.add("b", "company-b", "project-a")
                code, _ = self.request("mcp/dispatch", name=name, args=args)
                self.assertEqual(code, 200)
                memory = self.mind.store.get("fixture", "b")
                self.assertIsNotNone(memory)
                self.assertNotIn("pinned", memory.metadata)
                self.assertNotIn("snooze_until", memory.metadata)

    def test_mcp_forget_about_filters_owner_project_and_legitimate_pin_still_works(self):
        code, _ = self.request("mcp/dispatch", project="project-a", name="lm_pin", args={"id": "a"})
        self.assertEqual(code, 200); self.assertTrue(self.mind.store.get("fixture", "a").metadata["pinned"])
        code, _ = self.request("mcp/dispatch", project="project-a", name="lm_forget_about", args={"entity": "alice"})
        self.assertEqual(code, 200)
        self.assertIsNone(self.mind.store.get("fixture", "a"))
        self.assertIsNotNone(self.mind.store.get("fixture", "b"))
        self.assertIsNotNone(self.mind.store.get("fixture", "a-other-project"))

    def test_demo_clear_is_owner_project_scoped_across_namespaces(self):
        from logica_mind.demo import DEMO_FLAG
        for memory_id in ("a", "b", "a-other-project"):
            memory = self.mind.store.get("fixture", memory_id); memory.metadata[DEMO_FLAG] = True
            self.mind.store.add([memory])
        other = Memory(id="other-b", namespace="other-fixture", layer=MemoryLayer.SEMANTIC,
            content="fixture", metadata={"ownerId": "company-b", "project": "project-a", DEMO_FLAG: True})
        self.mind.store.add([other])
        code, _ = self.request("demo/clear", project="project-a")
        self.assertEqual(code, 200)
        self.assertIsNone(self.mind.store.get("fixture", "a"))
        self.assertIsNotNone(self.mind.store.get("fixture", "b"))
        self.assertIsNotNone(self.mind.store.get("fixture", "a-other-project"))
        self.assertIsNotNone(self.mind.store.get("other-fixture", "other-b"))

    def test_mcp_applied_decay_only_changes_authenticated_owner_project(self):
        foreign = self.mind.store.get("fixture", "b").importance
        other_project = self.mind.store.get("fixture", "a-other-project").importance
        own = self.mind.store.get("fixture", "a").importance
        code, body = self.request("mcp/dispatch", project="project-a", name="lm_forget_curve", args={"apply": True})
        self.assertEqual(code, 200)
        self.assertLess(self.mind.store.get("fixture", "a").importance, own)
        self.assertEqual(self.mind.store.get("fixture", "b").importance, foreign)
        self.assertEqual(self.mind.store.get("fixture", "a-other-project").importance, other_project)
        self.assertEqual([item["id"] for item in body["result"]], ["a"])

    def test_generic_deletes_and_mcp_metadata_cannot_reset_reserved_identity(self):
        from logica_mind.demo import DEMO_FLAG
        model = SelfModel(self.mind.store, "fixture", metadata_scope={"ownerId": OWNER, "project": "project-a", DEMO_FLAG: True})
        model.save({"identity": "Original identity"})
        reserved_id = "self-model::fixture::current"
        operations = [("forget", {"id": reserved_id}), ("clear", {"purge_all": True}),
                      ("forget_about", {"entity": "identity"}), ("demo/clear", {}),
                      ("mcp/dispatch", {"name": "lm_forget", "args": {"id": reserved_id}}),
                      ("mcp/dispatch", {"name": "lm_forget_about", "args": {"entity": "identity"}}),
                      ("mcp/dispatch", {"name": "lm_pin", "args": {"id": reserved_id}}),
                      ("mcp/dispatch", {"name": "lm_snooze", "args": {"id": reserved_id, "until": "2099-01-01"}}),
                      ("mcp/dispatch", {"name": "lm_forget_curve", "args": {"apply": True}})]
        for endpoint, fields in operations:
            with self.subTest(endpoint=endpoint):
                self.assertEqual(self.request(endpoint, project="project-a", **fields)[0], 200)
                self.assertEqual(model.load()["identity"], "Original identity")
                memory = self.mind.store.get("fixture", reserved_id)
                self.assertNotIn("pinned", memory.metadata)
                self.assertNotIn("snooze_until", memory.metadata)
        code, _ = self.request("self-model", project="project-a", patch={"identity": "Forged replacement"})
        self.assertEqual(code, 403)
        self.assertEqual(model.load()["identity"], "Original identity")

    def test_trusted_sdk_unscoped_portability_and_legacy_lifecycle_are_preserved(self):
        memory = self.mind.store.get("fixture", "b").to_dict(); memory["id"] = "sdk-unscoped-import"
        self.assertEqual(self.mind.import_bundle({"payload": {"memories": [memory]}}, verify=False), 1)
        self.assertEqual(self.mind.store.get("fixture", "sdk-unscoped-import").metadata["ownerId"], "company-b")
        self.assertTrue(self.mind.pin("b"))
        self.assertTrue(self.mind.store.get("fixture", "b").metadata["pinned"])

    def test_standalone_http_legacy_without_scope_preserves_continuity(self):
        model = SelfModel(self.mind.store, "fixture"); model.save({"identity": "Original identity"})
        with patch.dict("os.environ", {"LOGICAOS_MULTIUSER": "0"}):
            fields = {"ownerId": "", "metadata": {}}
            code, _ = self.request("mcp/dispatch", _gateway=False, name="lm_forget", args={"id": "self-model::fixture::current"}, **fields)
            self.assertEqual(code, 200)
            code, _ = self.request("clear", _gateway=False, purge_all=True, **fields)
            self.assertEqual(code, 200)
            self.assertEqual(model.load()["identity"], "Original identity")
            memory = Memory(id="legacy-import", namespace="fixture", layer=MemoryLayer.SEMANTIC, content="ordinary fixture").to_dict()
            code, _ = self.request("import-bundle", _gateway=False, bundle={"payload": {"memories": [memory]}}, **fields)
            self.assertEqual(code, 200)
            self.assertIsNotNone(self.mind.store.get("fixture", "legacy-import"))
            code, _ = self.request("forget", _gateway=False, id="legacy-import", **fields)
            self.assertEqual(code, 200)
            self.assertIsNone(self.mind.store.get("fixture", "legacy-import"))

    def test_clear_age_uses_iso_timezone_not_local_wall_clock(self):
        now = 1_800_000_000.0
        for index, offset in enumerate((timezone.utc, timezone(timedelta(hours=3)), timezone(timedelta(hours=-4)))):
            memory = self.add("recent-" + str(index), OWNER, "project-a")
            memory.created_at = datetime.fromtimestamp(now - 3600, offset).isoformat().replace("+00:00", "Z")
            self.mind.store.add([memory])
        with patch("time.time", return_value=now):
            code, _ = self.request("clear", project="project-a", older_than_days=0.1)
        self.assertEqual(code, 200)
        for index in range(3): self.assertIsNotNone(self.mind.store.get("fixture", "recent-" + str(index)))
        self.assertIsNone(self.mind.store.get("fixture", "a"))

    def test_sqlite_global_primary_key_import_remaps_ids_and_provenance_idempotently(self):
        from logica_mind.stores.sqlite import SQLiteStore
        with tempfile.TemporaryDirectory(prefix="mind-import-scope-") as directory:
            mind = FixtureMind(); mind.store = SQLiteStore(directory + "/fixture.db")
            try:
                foreign = Memory(id="collision", namespace="foreign-namespace", layer=MemoryLayer.SEMANTIC,
                    content="foreign fixture", embedding=[1.0, 0.0], metadata={"ownerId": "company-b"})
                mind.store.add([foreign])
                parent = foreign.to_dict(); parent["content"] = "imported parent"
                child = foreign.to_dict(); child["id"] = "child"; child["source_ids"] = ["collision", "unknown-foreign-reference"]
                bundle = {"payload": {"memories": [parent, child]}}
                scope = {"ownerId": OWNER, "project": "project-a"}
                self.assertEqual(mind.import_bundle(bundle, metadata_scope=scope, verify=False), 2)
                self.assertEqual(mind.store.get("foreign-namespace", "collision").content, "foreign fixture")
                records = {memory.metadata["importedId"]: memory for memory in mind.store.all("fixture")}
                self.assertNotEqual(records["collision"].id, "collision")
                self.assertEqual(records["child"].source_ids, [records["collision"].id])
                self.assertEqual(mind.import_bundle(bundle, metadata_scope=scope, verify=False), 2)
                self.assertEqual(len(mind.store.all("fixture")), 2)
                exported = mind.export_bundle(secret=KEY)
                self.assertEqual(mind.import_bundle(exported, secret=KEY, metadata_scope=scope), 2)
                self.assertEqual(len(mind.store.all("fixture")), 2)
            finally:
                mind.store.close()

    def test_concurrent_scoped_imports_cannot_claim_same_new_id_across_owners(self):
        barrier = threading.Barrier(2)
        def embed(_text):
            barrier.wait(timeout=3); return [1.0, 0.0]
        self.mind._embed = embed
        memory = Memory(id="concurrent-new-id", namespace="fixture", layer=MemoryLayer.SEMANTIC,
            content="concurrent fixture").to_dict()
        errors = []
        def run(owner):
            try: self.mind.import_bundle({"payload": {"memories": [memory]}}, metadata_scope={"ownerId": owner}, verify=False)
            except Exception as error: errors.append(type(error).__name__)
        threads = [threading.Thread(target=run, args=(owner,)) for owner in (OWNER, "company-b")]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=4)
        self.assertFalse(any(thread.is_alive() for thread in threads)); self.assertEqual(errors, [])
        imported = [record for record in self.mind.store.all("fixture") if record.metadata.get("importedId") == "concurrent-new-id"]
        self.assertEqual(len(imported), 2)
        self.assertEqual({record.metadata["ownerId"] for record in imported}, {OWNER, "company-b"})
        self.assertNotEqual(imported[0].id, imported[1].id)


if __name__ == "__main__":
    unittest.main()
