"""Full HTTP identity override boundary; memory-only, no models or real database."""
import base64
import copy
import hashlib
import hmac
import io
import json
import threading
import time
import unittest
from contextlib import redirect_stderr
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from logica_mind.continuity import SelfModel
from logica_mind.stores import InMemoryStore
from logica_mind.web import server as web

KEY = "synthetic-identity-service-key"
OWNER = "company-fixture"


def raw_body(body):
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()


def seed_capability(target, body, **overrides):
    claim = {"actorId": "alice", "ownerId": OWNER, "role": "super-admin", "method": "POST",
             "target": target, "bodyHash": hashlib.sha256(raw_body(body)).hexdigest(),
             "issuedAt": int(time.time() * 1000)}
    claim.update(overrides)
    payload = base64.urlsafe_b64encode(raw_body(claim)).rstrip(b"=").decode()
    signature = base64.urlsafe_b64encode(hmac.new(KEY.encode(),
        f"logicaos-identity-seed-v1:{payload}".encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    return f"lis-v1.{payload}.{signature}"


class Mind:
    namespace = "fixture"

    def __init__(self):
        self.store = InMemoryStore()

    def for_namespace(self, namespace):
        result = copy.copy(self)
        result.namespace = namespace
        return result

    def list_namespaces(self):
        return [{"namespace": "fixture"}]


class SelfModelHttpAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.mind = Mind()
        self.model = SelfModel(self.mind.store, "fixture")
        self.model.save({"identity": "Original identity"})
        self.env = patch.dict("os.environ", {"LOGICAOS_MULTIUSER": "0", "LOGICAOS_OWNER_ID": OWNER})
        self.env.__enter__()
        self.stderr = redirect_stderr(io.StringIO()); self.stderr.__enter__()
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), web.make_handler(self.mind, token=KEY))
        self.thread = threading.Thread(target=lambda: self.http.serve_forever(poll_interval=0.01), daemon=True)
        self.thread.start()

    def tearDown(self):
        self.http.shutdown(); self.http.server_close(); self.thread.join(timeout=3)
        self.stderr.__exit__(None, None, None); self.env.__exit__(None, None, None)

    def request(self, body, cap=None, target="/api/self-model", extra_headers=None):
        headers = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
        headers.update(extra_headers or {})
        if cap is not None: headers["X-LogicaOS-Identity-Seed"] = cap
        conn = HTTPConnection("127.0.0.1", self.http.server_port, timeout=3)
        try:
            conn.request("POST", target, raw_body(body), headers)
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()

    def body(self, **extra):
        return {"namespace": "fixture", "patch": {"identity": "Replacement identity"}, **extra}

    def test_service_bearer_body_and_forged_header_cannot_disable_identity_guard(self):
        for extra in ({"seed": True}, {"seed": True, "role": "super-admin", "admin": True}):
            code, _ = self.request(self.body(**extra), "forged-client-header")
            self.assertEqual(code, 403)
        self.assertEqual(self.model.load()["identity"], "Original identity")
        self.assertEqual(self.model.load()["version"], 1)

    def test_seed_is_strict_boolean_not_truthy_string_number_or_container(self):
        for seed in ("true", "false", 1, {"role": "super-admin"}, [True]):
            with self.subTest(seed_type=type(seed).__name__):
                self.assertIn(self.request(self.body(seed=seed))[0], (400, 403))
        self.assertEqual(self.model.load()["version"], 1)

    def test_normal_write_keeps_red_zone_guard_and_ordinary_evolution(self):
        for body in (self.body(), self.body(seed=False), self.body(patch={"identity": "Replacement identity", "seed": True})):
            self.assertEqual(self.request(body, target="/api/self-model?seed=true")[0], 403)
        code, _ = self.request({"namespace": "fixture", "patch": {"direction": "Legitimate evolution"}})
        self.assertEqual(code, 200)
        self.assertEqual(self.model.load()["identity"], "Original identity")

    def test_signed_admin_override_is_bound_to_exact_body_and_target(self):
        body = self.body(seed=True)
        code, _ = self.request(body, seed_capability("/api/self-model", body))
        self.assertEqual(code, 200)
        self.assertEqual(self.model.load()["identity"], "Replacement identity")

    def test_bad_authority_expiry_owner_role_or_body_never_overrides(self):
        body = self.body(seed=True)
        caps = [seed_capability("/api/self-model", body, role="user"),
                seed_capability("/api/self-model", body, ownerId="other-company"),
                seed_capability("/api/self-model", body, issuedAt=int(time.time() * 1000) - 91_000),
                seed_capability("/api/self-model", body, method="GET"),
                seed_capability("/api/self-model?other=1", body),
                seed_capability("/api/self-model", self.body(seed=True, patch={"identity": "Other payload"}))]
        for cap in caps:
            self.assertEqual(self.request(body, cap)[0], 403)
        self.assertEqual(self.model.load()["version"], 1)


if __name__ == "__main__":
    unittest.main()
