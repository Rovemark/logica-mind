import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

from logica_mind.stores.supabase import SupabaseStore


@pytest.fixture
def rest():
    calls = []
    rows = [{"id": f"id-{i:05d}", "namespace": "qa", "content": str(i),
             "created_at": "2026-01-01", "access_count": 0} for i in range(2400)]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            query = parse_qs(urlsplit(self.path).query)
            calls.append(("GET", self.path, query))
            assert query.get("namespace") == ["eq.qa"]
            assert "limit" in query
            candidates = rows
            if "id" in query:
                candidates = [row for row in rows if '"' + row["id"] + '"' in query["id"][0]]
            offset = int(query.get("offset", [0])[0])
            size = min(137, int(query["limit"][0]))
            body = json.dumps(candidates[offset:offset + size]).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_PATCH(self):
            query = parse_qs(urlsplit(self.path).query)
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(("PATCH", self.path, query))
            assert query["namespace"] == ["eq.qa"]
            assert body["access_count"] == 1
            self.send_response(204)
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield SupabaseStore(url=f"http://127.0.0.1:{server.server_port}", key="isolated-test", max_candidates=2100), calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_requested_window_survives_server_cap_and_offset(rest):
    store, calls = rest
    rows = store._request("GET", store.table + "?namespace=eq.qa&limit=1501&offset=211&order=id.asc")
    assert [row["id"] for row in rows] == [f"id-{i:05d}" for i in range(211, 1712)]
    assert all(int(query["limit"][0]) <= 1000 for _, _, query in calls)
    assert [int(query["offset"][0]) for _, _, query in calls] == list(range(211, 1712, 137))


def test_candidate_window_and_long_id_query_preserve_all_rows(rest):
    store, calls = rest
    assert len(store.all("qa")) == 2100
    calls.clear()
    store.touch("qa", [f"id-{i:05d}" for i in range(1100)])
    reads = [path for method, path, _ in calls if method == "GET"]
    writes = [query["id"][0] for method, _, query in calls if method == "PATCH"]
    assert len(reads) > 1
    assert max(map(len, reads)) < 3200
    assert len(set(writes)) == len(writes) == 1100


def test_zero_window_and_invalid_windows_do_not_send_http(rest):
    store, calls = rest
    assert store._request("GET", store.table + "?namespace=eq.qa&limit=0") == []
    for query in ("limit=-1", "limit=no", "limit=1&limit=2", "offset=-1"):
        with pytest.raises(ValueError):
            store._request("GET", store.table + "?namespace=eq.qa&" + query)
    assert calls == []


@pytest.mark.parametrize('invalid', [None, {}, False, 0, '', 'invalid', 1])
@pytest.mark.parametrize('prefix', [[], [{'id': 'first', 'namespace': 'qa'}]])
def test_malformed_http_page_never_proves_exhaustion(invalid, prefix):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            query = parse_qs(urlsplit(self.path).query)
            assert query['namespace'] == ['eq.qa']
            calls.append(query)
            page = prefix if prefix and len(calls) == 1 else invalid
            body = json.dumps(page).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        store = SupabaseStore(url=f'http://127.0.0.1:{server.server_port}', key='isolated-test')
        with pytest.raises(RuntimeError, match='invalid page'):
            store._request('GET', store.table + '?namespace=eq.qa&limit=10&offset=5')
        assert len(calls) == (2 if prefix else 1)
        assert int(calls[-1]['offset'][0]) == 5 + len(prefix)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
