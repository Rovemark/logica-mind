"""Real HTTP Banco guards, with a fake pool and synthetic credentials only."""
import base64
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
from types import SimpleNamespace
from unittest.mock import patch

from psycopg import OperationalError
from psycopg_pool import PoolTimeout
from logica_mind.banco import servico
from logica_mind.web import server as web

SECRET = "synthetic-service-key-only"
OWNER = "company-fixture"
SENTINEL = "SYNTHETIC_PASSWORD_SQL_SENTINEL"


def capability(target, **overrides):
    body = {"actorId": "alice", "ownerId": OWNER, "role": "super-admin",
            "method": "GET", "target": target, "issuedAt": int(time.time() * 1000)}
    body.update(overrides)
    encoded = base64.urlsafe_b64encode(json.dumps(body, separators=(",", ":")).encode()).rstrip(b"=").decode()
    signature = base64.urlsafe_b64encode(hmac.new(SECRET.encode(),
        f"logicaos-system-inspection-v1:{encoded}".encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    return f"lsi-v1.{encoded}.{signature}"


class Cursor:
    def __init__(self, queries):
        self.queries = queries
        self.last = ""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, parameters=None):
        self.last = sql
        self.queries.append((sql, parameters))

    def fetchone(self):
        return (1,)

    def fetchall(self):
        if "pg_total_relation_size" in self.last:
            return [("tasks", "1 kB"), ("release_keys", "1 kB"), ("team_users", "1 kB")]
        if "format_type" in self.last:
            return [(name, column, "text", False) for name in ("tasks", "release_keys", "team_users")
                    for column in ("id", "owner_id")]
        if "SELECT a.attname" in self.last:
            return [("id",), ("payload",), ("owner_id",)]
        if "UNION ALL" in self.last or "SELECT 'tasks' t" in self.last:
            return [("tasks", 1), ("release_keys", 1), ("team_users", 1)]
        return [(1, "fixture-row")]


class Pool:
    def __init__(self):
        self.queries = []
        self.connections = 0

    def connection(self):
        self.connections += 1
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return Cursor(self.queries)


class BancoHttpBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.pool = Pool()
        self.log = io.StringIO()
        self.stack = [
            patch.dict("os.environ", {"LOGICAOS_OWNER_ID": OWNER}),
            patch.object(servico, "ligado", return_value=True),
            patch.object(servico, "pool", return_value=self.pool),
            redirect_stderr(self.log),
        ]
        for context in self.stack:
            context.__enter__()
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), web.make_handler(
            SimpleNamespace(namespace="fixture"), token=SECRET))
        self.thread = threading.Thread(target=lambda: self.http.serve_forever(poll_interval=0.01), daemon=True)
        self.thread.start()

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=3)
        for context in reversed(self.stack):
            context.__exit__(None, None, None)

    def request(self, target, cap=None, method="GET", body=None, authorization=None):
        headers = {"Authorization": authorization if authorization is not None else f"Bearer {SECRET}", "Content-Type": "application/json"}
        if cap is not None:
            headers["X-LogicaOS-System-Inspection"] = cap
        connection = HTTPConnection("127.0.0.1", self.http.server_port, timeout=3)
        try:
            connection.request(method, target, json.dumps(body) if body is not None else None, headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_global_service_bearer_alone_cannot_inspect_system_or_personal_banco(self):
        for target in ("/api/banco/tabela?esquema=sistema&nome=tasks",
                       "/api/banco/tabelas?esquema=sistema",
                       "/api/banco/tabela?esquema=banco&nome=perfil",
                       "/api/banco/tabelas?esquema=banco"):
            with self.subTest(target=target):
                code, _ = self.request(target)
                self.assertEqual(code, 403)
        self.assertEqual(self.pool.connections, 0)

    def test_signed_admin_capability_reads_safe_table(self):
        target = "/api/banco/tabela?esquema=sistema&nome=tasks"
        code, body = self.request(target, capability(target))
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertGreater(self.pool.connections, 0)
        row_reads = [(sql, parameters) for sql, parameters in self.pool.queries if "SELECT *" in sql]
        self.assertTrue(row_reads)
        self.assertTrue(all("WHERE owner_id=%s" in sql and parameters[0] == OWNER for sql, parameters in row_reads))

    def test_secret_and_unknown_tables_are_denied_even_for_admin_before_pool(self):
        for name in ("release_keys", "team_users", "logicaos_licenses", "credentials", "synapse_sessions", "unknown"):
            target = f"/api/banco/tabela?esquema=sistema&nome={name}"
            with self.subTest(name=name):
                code, _ = self.request(target, capability(target))
                self.assertEqual(code, 403)
        self.assertEqual(self.pool.connections, 0)

    def test_system_catalogue_filters_secrets_from_rows_and_count_queries(self):
        target = "/api/banco/tabelas?esquema=sistema"
        code, body = self.request(target, capability(target))
        self.assertEqual(code, 200)
        self.assertEqual([item["nome"] for item in body["dados"]], ["tasks"])
        counts = [sql for sql, _ in self.pool.queries if "count(*)" in sql]
        self.assertTrue(counts)
        self.assertFalse(any("release_keys" in sql or "team_users" in sql for sql in counts))
        self.assertTrue(all("WHERE owner_id=%s" in sql for sql in counts))
        self.assertTrue(body["dados"][0]["escopada"])

    def test_secret_columns_and_missing_owner_fail_closed_before_row_reads(self):
        target = "/api/banco/tabela?esquema=sistema&nome=tasks"
        original = Cursor.fetchall
        for column in ("key_b64", "private_key", "credential", "api_key", "access_token", "password_hash", None):
            def metadata(cursor, selected=column):
                if "SELECT a.attname" in cursor.last:
                    return [("id",)] + ([("owner_id",), (selected,)] if selected else [])
                return original(cursor)
            with self.subTest(column=column), patch.object(Cursor, "fetchall", metadata):
                before = len(self.pool.queries)
                code, _ = self.request(target, capability(target))
                self.assertEqual(code, 403)
                self.assertFalse(any("SELECT *" in sql or "count(*)" in sql for sql, _ in self.pool.queries[before:]))

    def test_same_read_can_repeat_within_ttl_but_never_authorizes_write(self):
        target = "/api/banco/tabela?esquema=sistema&nome=tasks"
        cap = capability(target)
        self.assertEqual(self.request(target, cap)[0], 200)
        self.assertEqual(self.request(target, cap)[0], 200)
        self.assertIn(self.request(target, cap, method="POST")[0], (403, 405))

    def test_signed_claim_still_requires_global_bearer_and_loopback(self):
        target = "/api/banco/tabela?esquema=sistema&nome=tasks"
        for bearer, loopback in (("", True), ("Bearer delegated", True), (f"Bearer {SECRET}", False)):
            with self.subTest(loopback=loopback):
                answer = servico.despacha("GET", "/api/banco/tabela", {"esquema": ["sistema"], "nome": ["tasks"]}, {},
                    bearer, SECRET, False, de_loopback=loopback,
                    inspection_capability=capability(target), request_target=target)
                self.assertIn(answer.codigo, (401, 403))
        self.assertEqual(self.pool.connections, 0)

    def test_capability_rejects_expiry_future_owner_role_tampering_and_replay_to_another_target(self):
        target = "/api/banco/tabela?esquema=sistema&nome=tasks"
        caps = [
            capability(target, issuedAt=int(time.time() * 1000) - 91_000),
            capability(target, issuedAt=int(time.time() * 1000) + 60_000),
            capability(target, ownerId="other-company"), capability(target, actorId=""),
            capability(target, role="user"), capability(target, method="POST"),
            capability("/api/banco/tabelas?esquema=sistema"),
            capability(target)[:-4] + "AAAA", "client-forged", "lsi-v1..",
        ]
        for cap in caps:
            with self.subTest(cap_kind=cap[:10]):
                code, _ = self.request(target, cap)
                self.assertEqual(code, 403)
        self.assertEqual(self.pool.connections, 0)

    def test_body_cannot_forge_authority_or_enable_global_inspection(self):
        code, _ = self.request("/api/banco/tabela?esquema=sistema&nome=tasks", method="POST", body={
            "admin": True, "role": "super-admin", "systemInspection": True, "user_id": OWNER,
        })
        self.assertIn(code, (403, 405))
        self.assertEqual(self.pool.connections, 0)

    def test_pool_timeout_and_connectivity_errors_return_sanitized_503_without_secret_logs(self):
        for error in (PoolTimeout(f"couldn't get a connection after 2.00 sec {SENTINEL}"),
                      OperationalError(f"postgresql://fixture:{SENTINEL}@invalid SELECT secret"),
                      ConnectionError(SENTINEL), TimeoutError(SENTINEL)):
            with self.subTest(error_type=type(error).__name__), patch.object(servico, "despacha", side_effect=error):
                code, body = self.request("/api/banco/saude")
                self.assertEqual(code, 503)
                self.assertFalse(body["ok"])
                self.assertNotIn(SENTINEL, json.dumps(body))
        self.assertNotIn(SENTINEL, self.log.getvalue())

    def test_unexpected_failure_returns_sanitized_500_not_success(self):
        with patch.object(servico, "despacha", side_effect=RuntimeError(f"SELECT private {SENTINEL}")):
            code, body = self.request("/api/banco/saude")
            self.assertEqual(code, 500)
            self.assertFalse(body["ok"])
            self.assertNotIn(SENTINEL, json.dumps(body))
        self.assertNotIn(SENTINEL, self.log.getvalue())

    def test_missing_banco_module_does_not_leak_import_exception(self):
        with patch.object(web, "_banco", None), patch.object(web, "_banco_erro", SENTINEL):
            code, body = self.request("/api/banco/saude")
            self.assertEqual(code, 503)
            self.assertNotIn(SENTINEL, json.dumps(body))

    def test_direct_trata_is_closed_without_capability_and_delegated_owner_keeps_scoped_banco(self):
        denied = servico.trata("GET", "/api/banco/tabela", {"esquema": ["sistema"], "nome": ["tasks"]}, {}, OWNER)
        self.assertEqual(denied.codigo, 403)
        self.assertEqual(self.pool.connections, 0)
        scoped = servico.trata("GET", "/api/banco/tabela", {"esquema": ["banco"], "nome": ["no"]}, {}, "employee-fixture")
        self.assertEqual(scoped.codigo, 200)
        self.assertTrue(any("WHERE user_id = %s" in sql and parameters[0] == "employee-fixture"
                            for sql, parameters in self.pool.queries if parameters))

    def test_life_delegated_token_keeps_owner_scoped_http_inspection_without_admin_capability(self):
        owner = "life-owner-fixture"
        encoded = base64.urlsafe_b64encode(owner.encode()).rstrip(b"=").decode()
        bucket = int(time.time() // 60)
        signature = base64.urlsafe_b64encode(hmac.new(SECRET.encode(),
            f"life-banco-v1:{encoded}:{bucket}".encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
        code, body = self.request("/api/banco/tabela?esquema=banco&nome=no",
            authorization=f"Bearer life-v1.{encoded}.{bucket}.{signature}")
        self.assertEqual(code, 200)
        self.assertTrue(body["dados"]["escopada"])
        reads = [(sql, parameters) for sql, parameters in self.pool.queries if "SELECT *" in sql]
        self.assertTrue(reads)
        self.assertTrue(all("WHERE user_id = %s" in sql and parameters[0] == owner for sql, parameters in reads))


if __name__ == "__main__":
    unittest.main()
