from logica_mind import LogicaMind, Memory, MemoryLayer
from logica_mind.stores import InMemoryStore


def _memory(content, owner, project):
    return Memory(
        content=content,
        namespace="ceo",
        layer=MemoryLayer.EPISODIC,
        metadata={"ownerId": owner, "project": project},
    )


def test_recall_context_and_forget_are_owner_project_scoped():
    store = InMemoryStore()
    mind = LogicaMind(namespace="ceo", store=store)
    alice_alpha = _memory("alpha segredo único", "alice", "projects/alpha")
    alice_beta = _memory("beta segredo único", "alice", "projects/beta")
    bob_alpha = _memory("alpha segredo único de bob", "bob", "projects/alpha")
    store.add([alice_alpha, alice_beta, bob_alpha])

    scope = {"ownerId": "alice", "project": "projects/alpha"}
    hits = mind.recall("segredo único", limit=10, metadata_filter=scope)
    assert [hit.memory.id for hit in hits] == [alice_alpha.id]

    block = mind.context("segredo único", token_budget=1000, metadata_filter=scope)
    assert "alpha segredo único" in block
    assert "beta segredo único" not in block
    assert "de bob" not in block

    assert mind.forget(memory_id=bob_alpha.id, metadata_filter=scope) == 0
    assert store.get("ceo", bob_alpha.id) is not None
    assert mind.forget(memory_id=alice_alpha.id, metadata_filter=scope) == 1
    assert store.get("ceo", alice_alpha.id) is None


def test_forget_exact_content_and_scope_never_erases_neighbor():
    store = InMemoryStore()
    mind = LogicaMind(namespace="ceo", store=store)
    marker = "voice-organism-e2e-ABC123"
    alice_alpha = _memory(f"Usuário: {marker}\nAssistente: concluído", "alice", "projects/alpha")
    alice_beta = _memory(f"Usuário: {marker}\nAssistente: outro projeto", "alice", "projects/beta")
    bob_alpha = _memory(f"Usuário: {marker}\nAssistente: outro dono", "bob", "projects/alpha")
    store.add([alice_alpha, alice_beta, bob_alpha])

    deleted = mind.forget(
        contains=marker.lower(),
        metadata_filter={"ownerId": "alice", "project": "projects/alpha"},
    )
    assert deleted == 1
    assert store.get("ceo", alice_alpha.id) is None
    assert store.get("ceo", alice_beta.id) is not None
    assert store.get("ceo", bob_alpha.id) is not None


def test_forget_by_scope_without_content_erases_only_that_partition():
    store = InMemoryStore()
    mind = LogicaMind(namespace="ceo", store=store)
    alice_alpha = _memory("primeiro", "alice", "projects/alpha")
    alice_alpha_2 = _memory("segundo", "alice", "projects/alpha")
    bob_alpha = _memory("preservar", "bob", "projects/alpha")
    store.add([alice_alpha, alice_alpha_2, bob_alpha])

    assert mind.forget(metadata_filter={"ownerId": "alice", "project": "projects/alpha"}) == 2
    assert store.get("ceo", bob_alpha.id) is not None


def test_recall_across_does_not_mix_projects_or_owners():
    store = InMemoryStore()
    mind = LogicaMind(namespace="root", store=store)
    store.add([
        Memory(content="entrega alpha", namespace="ana", layer=MemoryLayer.EPISODIC,
               metadata={"ownerId": "alice", "project": "projects/alpha"}),
        Memory(content="entrega beta", namespace="bia", layer=MemoryLayer.EPISODIC,
               metadata={"ownerId": "bob", "project": "projects/beta"}),
    ])
    hits = mind.recall_across(
        "entrega", limit=10,
        metadata_filter={"ownerId": "alice", "project": "projects/alpha"},
    )
    assert len(hits) == 1
    assert hits[0].memory.metadata["ownerId"] == "alice"
    assert hits[0].memory.metadata["project"] == "projects/alpha"


def test_remember_dedup_is_partitioned_by_owner_and_project():
    store = InMemoryStore()
    mind = LogicaMind(namespace="ceo", store=store)
    alice = mind.remember("mesmo fato", extract=False,
                          metadata={"ownerId": "alice", "project": "alpha"})
    bob = mind.remember("mesmo fato", extract=False,
                        metadata={"ownerId": "bob", "project": "beta"})
    duplicate_alice = mind.remember("mesmo fato", extract=False,
                                    metadata={"ownerId": "alice", "project": "alpha"})
    assert len(alice) == 1
    assert len(bob) == 1
    assert duplicate_alice == []
    assert store.count("ceo") == 2


def test_http_multiuser_requires_and_materializes_owner_scope(monkeypatch):
    import json
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer
    from logica_mind.web.server import make_handler

    monkeypatch.setenv("LOGICAOS_MULTIUSER", "1")
    store = InMemoryStore()
    mind = LogicaMind(namespace="ceo", store=store)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(mind, token="tok"))
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def call(method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(base + path, data=data, method=method,
                                     headers={"Authorization": "Bearer tok",
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=3) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    try:
        assert call("POST", "/api/remember", {"namespace": "ceo", "text": "sem dono"})[0] == 400
        for owner, project in (("alice", "alpha"), ("bob", "beta")):
            status, payload = call("POST", "/api/remember", {
                "namespace": "ceo", "text": "fato compartilhado", "ownerId": owner,
                "project": project, "metadata": {"source": "test"},
            })
            assert status == 200 and payload["count"] == 1

        assert call("GET", "/api/recall?namespace=ceo&q=fato&limit=10")[0] == 400
        status, payload = call("GET", "/api/recall?namespace=ceo&q=fato&limit=10&owner=alice&project=alpha")
        assert status == 200
        assert len(payload["results"]) == 1
        assert payload["results"][0]["memory"]["metadata"]["ownerId"] == "alice"
        status, payload = call("GET", "/api/recall?namespace=ceo&q=fato&limit=10&ownerId=bob&projectId=beta")
        assert status == 200
        assert len(payload["results"]) == 1
        assert payload["results"][0]["memory"]["metadata"]["ownerId"] == "bob"
        status, payload = call("POST", "/api/remember", {
            "namespace": "ceo", "text": "alias de escrita", "owner": "carol", "project": "gamma",
        })
        assert status == 200 and payload["count"] == 1

        assert call("POST", "/api/mcp/dispatch", {
            "namespace": "ceo", "name": "lm_stats", "args": {},
        })[0] == 400
        status, payload = call("POST", "/api/mcp/dispatch", {
            "namespace": "ceo", "name": "lm_stats", "args": {},
            "ownerId": "alice", "project": "alpha",
        })
        assert status == 200
        assert payload["result"]["total"] == 1
        status, payload = call("POST", "/api/mcp/dispatch", {
            "namespace": "ceo", "name": "lm_recall", "args": {"query": "fato", "limit": 10},
            "owner": "bob", "project": "beta",
        })
        assert status == 200
        assert len(payload["result"]) == 1
        assert "bob" not in payload["result"][0]["content"]  # conteúdo igual; isolamento vem da contagem

        assert call("GET", "/api/predict?namespace=ceo")[0] == 400
        assert call("GET", "/api/predict?namespace=ceo&owner=alice&project=alpha")[0] == 200
        assert call("GET", "/api/graph?namespace=ceo")[0] == 400
        assert call("GET", "/api/graph?namespace=ceo&owner=alice")[0] == 200

        for session in ("cli-codex-1", "cli-codex-2"):
            status, payload = call("POST", "/api/remember", {
                "namespace": "ceo", "text": f"decisão exclusiva {session}",
                "ownerId": "alice", "project": "alpha", "session": session,
            })
            assert status == 200 and payload["count"] == 1
        status, payload = call(
            "GET", "/api/recall?namespace=ceo&q=exclusiva&limit=10"
            "&owner=alice&project=alpha&session=cli-codex-1",
        )
        assert status == 200
        assert len(payload["results"]) == 1
        assert payload["results"][0]["memory"]["metadata"]["session"] == "cli-codex-1"
    finally:
        srv.shutdown()
        srv.server_close()
