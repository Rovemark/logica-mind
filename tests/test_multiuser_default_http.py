"""Default HTTP requests must require owner scope; opt-out stays explicit."""
import json
import os
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from test_memory_http_mutation_scope import FixtureMind
from logica_mind.web.server import make_handler

class MultiuserDefaultHttpTests(unittest.TestCase):
    def request(self, flag):
        with patch.dict(os.environ, {"LOGICAOS_OWNER_ID": "company-a"}):
            if flag is None:
                os.environ.pop("LOGICAOS_MULTIUSER", None)
            else:
                os.environ["LOGICAOS_MULTIUSER"] = flag
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(FixtureMind(), token="qa-key"))
            thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
            thread.start()
            conn = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            try:
                conn.request("GET", "/api/memories?namespace=fixture", headers={"Authorization": "Bearer qa-key", "X-LogicaOS-Company-Mind": "1"})
                response = conn.getresponse()
                return response.status, json.loads(response.read())
            finally:
                conn.close(); server.shutdown(); server.server_close(); thread.join(timeout=3)

    def test_missing_and_unknown_flags_fail_closed(self):
        for flag in (None, "", "unexpected", " YES "):
            with self.subTest(flag=flag):
                status, body = self.request(flag)
                self.assertEqual(status, 400)
                self.assertIn("owner scope required", body.get("error", ""))

    def test_explicit_standalone_opt_out(self):
        for flag in ("0", " false ", "No"):
            with self.subTest(flag=flag):
                status, _ = self.request(flag)
                self.assertEqual(status, 200)
