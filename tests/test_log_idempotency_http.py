"""POST /api/log with an idempotency key: exact replay, conflict and invalid key.

Reusing a key with different content is a client contract violation. It must be
refused WITHOUT writing and answered 409 with a stable, sanitized body; storage
failures and any other error keep their 503/500 path.
"""
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

from logica_mind import LogicaMind
from logica_mind.core import InvalidLogIdempotencyKey, LogIdempotencyConflict
from logica_mind.stores import InMemoryStore
from logica_mind.web.server import make_handler

TOKEN = "fixture-only"
CONFLICT = {"ok": False, "code": "MEMORY_IDEMPOTENCY_CONFLICT",
            "error": "idempotency key already used with different content"}
INVALID = {"ok": False, "code": "MEMORY_IDEMPOTENCY_KEY_INVALID", "error": "invalid idempotency key"}
BODY = {"namespace": "fixture", "ownerId": "fixture-owner", "session": "fixture-session",
        "role": "user", "channel": "fixture", "text": "fixture original turn",
        "idempotencyKey": "fixture-turn-1"}


class GetFails(InMemoryStore):
    def get(self, namespace, memory_id):
        raise OSError("fixture storage outage at /secret/dsn")


class AddRaisesValueError(InMemoryStore):
    def add(self, memories):
        raise ValueError("fixture driver value error with private row")


class AddFails(InMemoryStore):
    def add(self, memories):
        raise RuntimeError("fixture write failure")


class LogIdempotencyHttpTests(unittest.TestCase):
    def serve(self, store):
        self.mind = LogicaMind(namespace="fixture", store=store)
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.mind, token=TOKEN))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 3)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.port = server.server_port

    def post(self, body, path="/api/log"):
        connection = HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.request("POST", path, json.dumps(body), {
                "Content-Type": "application/json", "Authorization": "Bearer " + TOKEN})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def stored(self):
        return [(m.id, m.content) for m in self.mind.store.all("fixture", with_embeddings=False)]

    def test_exact_replay_returns_same_receipt_without_second_row(self):
        self.serve(InMemoryStore())
        code, first = self.post(BODY)
        self.assertEqual((code, first["ok"]), (200, True))
        for _ in range(3):
            self.assertEqual(self.post(BODY), (200, {"ok": True, "id": first["id"]}))
        self.assertEqual(self.stored(), [(first["id"], BODY["text"])])

    def test_conflict_is_409_sanitized_and_writes_nothing(self):
        self.serve(InMemoryStore())
        code, first = self.post(BODY)
        self.assertEqual(code, 200)
        divergent = {**BODY, "text": "fixture DIVERGENT private text"}
        for path in ("/api/log", "/api/journal/log"):
            code, payload = self.post(divergent, path)
            self.assertEqual((code, payload), (409, CONFLICT), path)
            raw = json.dumps(payload)
            for leaked in (first["id"], BODY["idempotencyKey"], "DIVERGENT", "Traceback"):
                self.assertNotIn(leaked, raw)
        self.assertEqual(self.stored(), [(first["id"], BODY["text"])])
        # the original key still works for the original content after the refusal
        self.assertEqual(self.post(BODY), (200, {"ok": True, "id": first["id"]}))

    def test_conflict_before_any_write_never_happens_for_other_partitions(self):
        self.serve(InMemoryStore())
        code, first = self.post(BODY)
        code_b, other = self.post({**BODY, "ownerId": "fixture-owner-b", "text": "other owner"})
        code_s, session = self.post({**BODY, "session": "fixture-session-2", "text": "other session"})
        self.assertEqual((code, code_b, code_s), (200, 200, 200))
        self.assertEqual(len({first["id"], other["id"], session["id"]}), 3)
        self.assertEqual(len(self.stored()), 3)

    def test_invalid_key_is_400_and_writes_nothing(self):
        self.serve(InMemoryStore())
        for key in ("x" * 301, "bad\nkey", ""):
            code, payload = self.post({**BODY, "idempotencyKey": key}, "/api/log")
            self.assertEqual((code, payload), (400, INVALID), repr(key))
        self.assertEqual(self.stored(), [])

    def test_concurrent_conflicting_writers_keep_one_row_and_never_500(self):
        self.serve(InMemoryStore())
        texts = ["fixture race A", "fixture race B"] * 8
        with ThreadPoolExecutor(max_workers=4) as pool:  # listen backlog of the stdlib server is 5
            results = list(pool.map(lambda t: (t, self.post({**BODY, "text": t})), texts))
        rows = self.stored()
        self.assertEqual(len(rows), 1)
        winner_id, winner_text = rows[0]
        for text, (code, payload) in results:
            if text == winner_text:
                self.assertEqual((code, payload), (200, {"ok": True, "id": winner_id}))
            else:
                self.assertEqual((code, payload), (409, CONFLICT))

    def test_storage_outage_keeps_503(self):
        self.serve(GetFails())
        code, payload = self.post(BODY)
        self.assertEqual(code, 503)
        self.assertEqual(payload["code"], "MEMORY_UNAVAILABLE")
        self.assertNotIn("secret", json.dumps(payload))

    def test_other_value_errors_are_not_swallowed_as_conflict(self):
        self.serve(AddRaisesValueError())
        code, payload = self.post(BODY)
        self.assertEqual((code, payload["code"]), (500, "MEMORY_INTERNAL_ERROR"))
        self.assertNotIn("private row", json.dumps(payload))

    def test_write_failure_keeps_500(self):
        self.serve(AddFails())
        code, payload = self.post(BODY)
        self.assertEqual((code, payload["code"]), (500, "MEMORY_INTERNAL_ERROR"))


class LogIdempotencyCoreTests(unittest.TestCase):
    def test_typed_errors_stay_value_errors_for_existing_callers(self):
        self.assertTrue(issubclass(LogIdempotencyConflict, ValueError))
        self.assertTrue(issubclass(InvalidLogIdempotencyKey, ValueError))
        self.assertFalse(issubclass(LogIdempotencyConflict, InvalidLogIdempotencyKey))

    def test_core_conflict_leaves_stored_content_untouched(self):
        mind = LogicaMind(namespace="fixture", store=InMemoryStore())
        first = mind.log("fixture original", session="s", idempotency_key="k")
        self.assertEqual(mind.log("fixture original", session="s", idempotency_key="k").id, first.id)
        with self.assertRaises(LogIdempotencyConflict):
            mind.log("fixture changed", session="s", idempotency_key="k")
        with self.assertRaises(InvalidLogIdempotencyKey):
            mind.log("fixture original", session="s", idempotency_key="a\x00b")
        rows = mind.store.all("fixture", with_embeddings=False)
        self.assertEqual([(m.id, m.content) for m in rows], [(first.id, "fixture original")])


if __name__ == "__main__":
    unittest.main()
