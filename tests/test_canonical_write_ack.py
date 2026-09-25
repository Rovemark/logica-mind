"""A successful HTTP log must not acknowledge a failed canonical write."""
import unittest
import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

from logica_mind import LogicaMind, Memory
from logica_mind.stores import InMemoryStore, MultiStore
from logica_mind.web.server import make_handler


class FailingStore(InMemoryStore):
    name = "unavailable-fixture"

    def add(self, memories):
        raise OSError("fixture storage outage")


class CanonicalWriteAckTests(unittest.TestCase):
    def test_primary_failure_is_not_hidden_by_successful_mirror(self):
        mirror = InMemoryStore()
        store = MultiStore([FailingStore(), mirror], require_primary=True)
        memory = Memory(content="fixture canonical receipt", namespace="fixture")
        with self.assertRaisesRegex(RuntimeError, "Canonical"):
            store.add([memory])
        self.assertIsNotNone(mirror.get("fixture", memory.id))

    def test_mirror_failure_does_not_discard_primary_success(self):
        primary = InMemoryStore()
        store = MultiStore([primary, FailingStore()], require_primary=True)
        memory = Memory(content="fixture primary receipt", namespace="fixture")
        store.add([memory])
        self.assertIsNotNone(primary.get("fixture", memory.id))

    def test_all_destinations_failing_never_returns_success(self):
        store = MultiStore([FailingStore(), FailingStore()])
        with self.assertRaisesRegex(RuntimeError, "No memory store"):
            store.add([Memory(content="fixture")])

    def test_optional_primary_preserves_existing_replica_fallback(self):
        mirror = InMemoryStore()
        store = MultiStore([FailingStore(), mirror])
        memory = Memory(content="fixture fallback")
        store.add([memory])
        self.assertIsNotNone(mirror.get("default", memory.id))

    def test_log_cannot_generate_receipt_for_failed_primary(self):
        mind = LogicaMind(namespace="fixture", store=MultiStore(
            [FailingStore(), InMemoryStore()], require_primary=True))
        with self.assertRaisesRegex(RuntimeError, "Canonical"):
            mind.log("fixture user turn", metadata={"ownerId": "fixture-owner"})

    def test_empty_batch_is_a_noop(self):
        MultiStore([FailingStore()], require_primary=True).add([])

    def _http_log(self, primary, mirror):
        mind = LogicaMind(namespace="fixture", store=MultiStore(
            [primary, mirror], require_primary=True))
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(
            mind, token="fixture-only"))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        try:
            connection.request("POST", "/api/log", json.dumps({
                "namespace": "fixture", "ownerId": "fixture-owner",
                "text": "fixture desktop turn", "channel": "computer-use",
            }), {"Content-Type": "application/json", "Authorization": "Bearer fixture-only"})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_http_does_not_issue_receipt_when_only_mirror_saved(self):
        status, payload = self._http_log(FailingStore(), InMemoryStore())
        self.assertEqual(status, 500)
        self.assertNotIn("id", payload)
        self.assertIn("Canonical", payload["error"])

    def test_http_receipt_can_be_read_from_primary(self):
        primary = InMemoryStore()
        status, payload = self._http_log(primary, FailingStore())
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        saved = primary.get("fixture", payload["id"])
        self.assertIsNotNone(saved)
        self.assertEqual(saved.metadata["ownerId"], "fixture-owner")
        self.assertEqual(saved.metadata["channel"], "computer-use")


if __name__ == "__main__":
    unittest.main()
