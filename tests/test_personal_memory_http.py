"""Real HTTP+canonical SQLite fixture; no production database, provider or keys."""
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

from logica_mind import LogicaMind
from logica_mind.stores import SQLiteStore
from logica_mind.web.server import make_handler
from logica_mind.stores.privacy import personal_prefix, PrivacyStore


def test_private_memory_http_boundary_and_shared_views(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGICAOS_MULTIUSER", "1")
    store = SQLiteStore(str(tmp_path / "memory.db"))
    mind = LogicaMind(namespace="astro", store=store)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(mind, token="fixture-token"))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def call(method, endpoint, data=None, bearer=True):
        headers = {"Content-Type": "application/json"}
        if bearer:
            headers["Authorization"] = "Bearer fixture-token"
        req = urllib.request.Request(base + endpoint, method=method, headers=headers,
                                     data=json.dumps(data).encode() if data is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def read(endpoint="recall", **extra):
        query = {"namespace": "astro", "q": "unique orchid preference", "ownerId": "company-a",
                 "actorId": "alice", "memoryScope": "personal", **extra}
        return call("GET", "/api/personal/" + endpoint + "?" + urllib.parse.urlencode(query))

    try:
        assert call("GET", "/api/health")[1]["memoryScopes"] == ["shared", "personal"]
        body = {"namespace": "astro", "text": "unique orchid preference Alice", "channel": "cli",
                "ownerId": "company-a", "actorId": "alice", "memoryScope": "personal", "session": "cli-one"}
        body["idempotencyKey"] = "fixture-session-one-turn-one"
        code, saved = call("POST", "/api/personal/log", body)
        assert code == 200 and saved["ok"] is True and saved["id"]
        assert len(read()[1]["results"]) == 1
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as pool:
            replays = list(pool.map(lambda _: call("POST", "/api/personal/log", body), range(8)))
        assert all(code == 200 and replay["id"] == saved["id"] for code, replay in replays)
        assert len(read()[1]["results"]) == 1
        assert call("POST", "/api/personal/log", {**body, "text": "conflicting content"})[0] == 409
        # A new session retrieves the same confirmed memory via owner + actor.
        code, recent = read("memories", session="")
        assert code == 200 and recent["memories"][0]["id"] == saved["id"]
        assert recent["memories"][0]["metadata"]["session"] == "cli-one"
        assert "orchid" in read("context")[1]["block"]
        assert len(read(namespace="__all__")[1]["results"]) == 1
        for scope in ({"actorId": "bob"}, {"ownerId": "company-b"}):
            assert read(**scope)[1]["results"] == []
            assert read("memories", **scope)[1]["memories"] == []
            assert read("context", **scope)[1]["block"] == ""
        for extra in ({"project": "project-a"}, {"actorId": ""}, {"actorId": "system:cron"}, {"memoryScope": "bogus"}):
            assert read(**extra)[0] == 400
        assert call("GET", "/api/personal/recall?ownerId=company-a&actorId=alice&memoryScope=personal&q=orchid", bearer=False)[0] == 403
        for endpoint in ("graph", "export", "sessions", "user", "stats", "namespaces"):
            assert read(endpoint)[0] == 403
        for endpoint in ("remember", "ingest", "mcp/dispatch", "heartbeat/beat", "clear"):
            assert call("POST", "/api/personal/" + endpoint, body)[0] == 403
        # Unsupported/old-style API cannot silently interpret personal as shared.
        assert call("POST", "/api/log", body)[0] == 400
        assert call("GET", "/api/recall?ownerId=company-a&memoryScope=personal&q=orchid")[0] == 400
        private_ns = personal_prefix("company-a", "alice") + "astro"
        assert call("GET", f"/api/recall?namespace={private_ns}&ownerId=company-a&q=orchid")[0] == 400
        assert call("POST", "/api/log", {**body, "namespace": private_ns, "memoryScope": "shared"})[0] == 400
        # Default reads and even the corporate gateway cannot discover private data.
        for namespace in ("astro", "__all__"):
            for endpoint, result_key in (("recall", "results"), ("memories", "memories")):
                result = call("GET", f"/api/{endpoint}?namespace={namespace}&ownerId=company-a&q=orchid")[1]
                assert result[result_key] == []
        assert call("GET", "/api/namespaces?ownerId=company-a")[1]["namespaces"] == []
        shared = PrivacyStore(store)
        assert shared.path == store.path
        assert shared.namespaces() == []
        assert shared.bucket_counts() == {}
        assert shared.session_stats() == []
        assert shared.day() == []
        assert shared.filter_memories() == []
        # Neighbor actor and shared memory are retained when forgetting Alice.
        assert call("POST", "/api/personal/log", {**body, "actorId": "bob"})[0] == 200
        assert call("POST", "/api/log", {"namespace": "astro", "text": "shared orchid",
                                          "ownerId": "company-a", "project": "project-a"})[0] == 200
        code, forgotten = call("POST", "/api/personal/forget", {**body, "id": saved["id"]})
        assert code == 200 and forgotten["deleted"] == 1
        assert read()[1]["results"] == []
        assert len(read(actorId="bob")[1]["results"]) == 1
        assert len(call("GET", "/api/recall?namespace=astro&ownerId=company-a&project=project-a&q=orchid")[1]["results"]) == 1
        # SQL paging applies privacy before LIMIT; the newest neighbor cannot
        # hide an older shared/Alice item from a page of size one.
        assert call("POST", "/api/personal/log", {**body, "text": "alice pagination", "idempotencyKey": "alice-page"})[0] == 200
        for index in range(3):
            assert call("POST", "/api/personal/log", {**body, "actorId": "bob", "text": f"bob page {index}",
                                                      "idempotencyKey": f"bob-page-{index}"})[0] == 200
        assert read("memories", namespace="__all__", limit=1)[1]["memories"][0]["content"] == "alice pagination"
        page = call("GET", "/api/memories?namespace=__all__&ownerId=company-a&limit=1")[1]["memories"]
        assert len(page) == 1 and page[0]["content"] == "shared orchid"
        shared_body = {"namespace": "astro", "text": "shared journal", "ownerId": "company-a", "actorId": "alice",
                       "project": "project-a", "session": "cli-two", "idempotencyKey": "turn-one"}
        code, journal = call("POST", "/api/journal/log", shared_body)
        assert code == 200 and journal["ok"]
        assert call("POST", "/api/journal/log", shared_body)[1]["id"] == journal["id"]
        assert call("POST", "/api/journal/log", {**shared_body, "idempotencyKey": None})[0] == 400
    finally:
        srv.shutdown()
        srv.server_close()
        store.close()


def test_personal_partition_uses_primary_without_company_mirrors(tmp_path):
    from logica_mind.stores import InMemoryStore, MultiStore
    from logica_mind.types import Memory
    primary, mirror = InMemoryStore(), InMemoryStore()
    multi = MultiStore([primary, mirror])
    prefix = personal_prefix("company-a", "alice")
    private = PrivacyStore(multi, prefix)
    memory = Memory(namespace=prefix + "astro", content="private fixture")
    private.add([memory])
    assert primary.get(memory.namespace, memory.id).content == "private fixture"
    assert mirror.namespaces() == []
    assert private.get(memory.namespace, memory.id).id == memory.id
    assert PrivacyStore(multi).namespaces() == []

    class FailingPrimary(InMemoryStore):
        def add(self, memories):
            raise RuntimeError("primary unavailable")
    blocked = PrivacyStore(MultiStore([FailingPrimary(), mirror]), prefix)
    import pytest
    with pytest.raises(RuntimeError, match="primary unavailable"):
        blocked.add([memory])
    assert mirror.namespaces() == []


def test_shared_native_aggregates_keep_capabilities_and_exclude_personal_metadata(tmp_path):
    from logica_mind.types import Memory
    store = SQLiteStore(str(tmp_path / "aggregate.db"))
    shared = PrivacyStore(store)
    prefix = personal_prefix("company-a", "alice")
    private = PrivacyStore(store, prefix)
    shared.add([Memory(namespace="astro", content="company fixture", metadata={"dimension": "company", "category": "shared", "channel": "cli"})])
    private.add([Memory(namespace=prefix + "astro", content="personal fixture", metadata={"dimension": "private-topic", "category": "private-category", "channel": "private-channel", "memoryScope": "personal"})])
    try:
        counts, _ = shared.dimension_counts()
        assert list(counts) == ["company"]
        assert sum(day["total"] for day in shared.day_counts().values()) == 1
        assert all("personal" not in content for content, _ in shared.tagged())
        assert all("personal" not in content for content, _ in shared.dimensioned())
        assert shared.change_token() is not None
        import pytest
        with pytest.raises(ValueError):
            shared.set_embeddings(prefix + "astro", [])
    finally:
        store.close()
