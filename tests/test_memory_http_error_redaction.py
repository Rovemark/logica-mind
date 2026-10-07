"""Unexpected memory failures must not disclose DSNs, SQL or private row values."""
import copy
import io
import json
import threading
import unittest
from contextlib import redirect_stderr
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch

from psycopg import OperationalError
from psycopg_pool import PoolTimeout
from logica_mind.stores import InMemoryStore
from logica_mind.web import server as web

SENTINEL = "SYNTHETIC_MEMORY_DSN_SQL_PASSWORD_SENTINEL"
KEY = "synthetic-error-test-key"


class FailingStore(InMemoryStore):
    def __init__(self, error):
        super().__init__(); self.error = error

    def all(self, *args, **kwargs):
        raise self.error


class Mind:
    namespace = "fixture"
    llm = SimpleNamespace(available=True, name="no-real-model-called")

    def __init__(self, error):
        self.store = FailingStore(error); self.error = error

    def for_namespace(self, namespace):
        view = copy.copy(self); view.namespace = namespace; return view

    def list_namespaces(self):
        return [{"namespace": "fixture"}]

    def log(self, *args, **kwargs):
        raise self.error

    def dream(self, *args, **kwargs):
        raise self.error


class MemoryHttpErrorRedactionTests(unittest.TestCase):
    def call(self, error, endpoint, method="GET", body=None):
        log = io.StringIO()
        with patch.dict("os.environ", {"LOGICAOS_MULTIUSER": "0", "LOGICA_MIND_PUBLIC": "0"}), redirect_stderr(log):
            http = ThreadingHTTPServer(("127.0.0.1", 0), web.make_handler(Mind(error), token=KEY))
            worker = threading.Thread(target=lambda: http.serve_forever(poll_interval=0.01), daemon=True)
            worker.start()
            conn = HTTPConnection("127.0.0.1", http.server_port, timeout=3)
            try:
                conn.request(method, endpoint, json.dumps(body or {}) if method == "POST" else None,
                             {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
                response = conn.getresponse(); code, payload = response.status, json.loads(response.read())
            finally:
                conn.close(); http.shutdown(); http.server_close(); worker.join(timeout=3)
        return code, payload, log.getvalue()

    def test_get_post_and_dream_driver_errors_are_sanitized_unavailable(self):
        for error in (OperationalError(f"postgresql://fixture:{SENTINEL}@invalid SELECT private_value"),
                      PoolTimeout(f"pool deadline {SENTINEL}")):
            for endpoint, method, body in (("/api/memories?namespace=fixture", "GET", None),
                                           ("/api/log", "POST", {"namespace": "fixture", "text": "fixture"}),
                                           ("/api/dream", "POST", {"namespace": "fixture"})):
                with self.subTest(endpoint=endpoint, error_type=type(error).__name__):
                    code, payload, log = self.call(error, endpoint, method, body)
                    self.assertEqual(code, 503)
                    self.assertFalse(payload["ok"])
                    self.assertNotIn(SENTINEL, json.dumps(payload) + log)
                    self.assertNotIn("postgresql://", json.dumps(payload))

    def test_get_post_and_dream_unexpected_errors_remain_sanitized_500(self):
        for endpoint, method, body in (("/api/memories?namespace=fixture", "GET", None),
                                       ("/api/log", "POST", {"namespace": "fixture", "text": "fixture"}),
                                       ("/api/dream", "POST", {"namespace": "fixture"})):
            with self.subTest(endpoint=endpoint):
                code, payload, log = self.call(RuntimeError(SENTINEL), endpoint, method, body)
                self.assertEqual(code, 500)
                self.assertFalse(payload["ok"])
                self.assertNotIn(SENTINEL, json.dumps(payload) + log)

    def test_validation_errors_keep_domain_400_and_specific_safe_message(self):
        error = RuntimeError(SENTINEL)
        code, payload, _ = self.call(error, "/api/memories?layer=not-a-layer&namespace=fixture")
        self.assertEqual(code, 400); self.assertIn("invalid layer", payload["error"])
        code, payload, _ = self.call(error, "/api/log", "POST", {"namespace": "private-cli-forbidden", "text": "fixture"})
        self.assertEqual(code, 400); self.assertIn("reserved memory namespace", payload["error"])
        code, payload, _ = self.call(web._Http400("invalid dream option"), "/api/dream", "POST", {"namespace": "fixture"})
        self.assertEqual(code, 400); self.assertEqual(payload["error"], "invalid dream option")

    def test_namespace_discovery_post_failure_is_also_contained_without_traceback(self):
        with patch.object(Mind, "list_namespaces", side_effect=OperationalError(SENTINEL)):
            code, payload, log = self.call(RuntimeError("unused"), "/api/log", "POST", {"namespace": "fixture", "text": "fixture"})
        self.assertEqual(code, 503)
        self.assertFalse(payload["ok"])
        self.assertNotIn(SENTINEL, json.dumps(payload) + log)


if __name__ == "__main__":
    unittest.main()
