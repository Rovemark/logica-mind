"""Real HTTP contracts, offline canonical memory. No provider/network side effects."""
import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from unittest.mock import patch
import pytest
from logica_mind import LogicaMind
from logica_mind.stores import InMemoryStore
from logica_mind.web.server import make_handler

@pytest.fixture
def service():
    mind = LogicaMind(namespace="astro", store=InMemoryStore())
    with patch.dict("os.environ", {"LOGICAOS_MULTIUSER": "1"}):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(mind, token="fixture-only"))
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
        thread.start()
        def request(path, body=None):
            conn = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            headers = {"Authorization": "Bearer fixture-only", "X-LogicaOS-Company-Mind": "1", "Content-Type": "application/json"}
            conn.request("POST" if body is not None else "GET", "/api/" + path, json.dumps(body) if body is not None else None, headers)
            response = conn.getresponse()
            try: return response.status, json.loads(response.read())
            finally: conn.close()
        yield mind, request
        server.shutdown(); server.server_close(); thread.join(2)


def test_directional_pair_roundtrip_and_validation(service):
    mind, call = service
    assert call("peers?namespace=__all__")[1]["peers"] == []
    body = {"namespace": "astro", "ownerId": "company-a", "observer": "astro", "observed": "green", "text": "Green conferiu os testes do projeto."}
    assert call("observe_peer", {**body, "observer": " "})[0] == 400
    assert call("observe_peer", body)[1]["ok"] is True
    assert call("observe_peer", {**body, "observer": "green", "observed": "astro", "text": "Astro prefere evidências."})[1]["ok"] is True
    pairs = call("peers?namespace=__all__")[1]["peers"]
    assert len(pairs) == 2
    assert all(p["namespace"] == "astro" and p["count"] == 1 for p in pairs)
    card = call("peer_card?namespace=astro&observer=astro&observed=green")[1]["card"]
    assert "Green conferiu" in card and "Astro prefere" not in card
    assert mind._peer_obs("astro", "green")[0].metadata["ownerId"] == "company-a"


def test_all_communities_include_each_namespace_and_typed_relations(service):
    mind, call = service
    # Graph extractor writes fixture relations directly, no model invoked.
    for ns, subject in [("astro", "Deck"), ("green", "Router")]:
        mind.for_namespace(ns).graph.ingest(subject, "part_of", "LogicaOS")
    code, result = call("communities?namespace=__all__")
    assert code == 200 and result["namespace"] == "__all__"
    assert {c["namespace"] for c in result["communities"]} == {"astro", "green"}
    assert all(c["relations"][0]["predicate"] == "part_of" for c in result["communities"])
    assert {c["namespace"] for c in call("communities?namespace=green")[1]["communities"]} == {"green"}


def test_peer_projections_skip_unrelated_user_records_and_keep_direction(tmp_path):
    from logica_mind.stores import SQLiteStore, MultiStore
    from logica_mind.stores.privacy import PrivacyStore
    from logica_mind import Memory, MemoryLayer
    store = SQLiteStore(str(tmp_path / 'peers.db'))
    store.add([Memory(namespace='astro', layer=MemoryLayer.USER, content=f'Unrelated profile {i}', metadata={}) for i in range(60)])
    mind = LogicaMind(namespace='astro', store=store)
    mind.observe_peer('astro', 'green', 'Verificou a entrega.')
    mind.observe_peer('green', 'astro', 'Prefere evidências.')
    # Optimized SQL reads must not fall back to materializing every user profile.
    store.all = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('full profile scan'))
    wrapped = PrivacyStore(MultiStore([store]))
    store.add([Memory(namespace='private-cli-hidden', layer=MemoryLayer.USER, content='Private', metadata={'observer':'private','observed':'private','memoryScope':'personal'})])
    assert len(wrapped.peer_pairs()) == 2
    assert len(wrapped.peer_pairs('astro')) == 2
    assert [m.content for m in wrapped.peer_memories('astro', 'astro', 'green')] == ['Verificou a entrega.']
    with pytest.raises(ValueError):
        wrapped.peer_pairs('private-cli-not-authorized')


def test_observation_pruning_matches_exhaustive_top_pairs():
    import random
    from collections import Counter, defaultdict
    rng = random.Random(29)
    mind = LogicaMind(namespace='fixture', store=InMemoryStore())
    for i in range(260):
        a, b = rng.sample(range(65), 2)
        mind.graph.ingest(f'e{a}', f'relation{i % 3}', f'e{b}')
    neighbors, degree = defaultdict(set), Counter()
    for e in mind.graph.edges():
        neighbors[e.subject].add(e.object); neighbors[e.object].add(e.subject)
        degree[e.subject] += 1; degree[e.object] += 1
    entities = sorted(neighbors)
    expected = []
    for i, a in enumerate(entities):
        for b in entities[i+1:]:
            common = (neighbors[a] & neighbors[b]) - {a, b}
            if len(common) >= 2:
                expected.append((len(common), (a,b)))
    expected.sort(key=lambda v: (-v[0],v[1]))
    for limit in (1, 6, 12, 30):
        actual = mind.observations(limit=limit)
        hubs = [o for o in actual if o['kind'] == 'hub']
        pairs = [(o['count'], tuple(o['entities'])) for o in actual if o['kind'] == 'co_occurrence']
        assert pairs == expected[:max(0,limit-len(hubs))]


def test_demo_detection_counts_in_storage_without_enumerating_memories(tmp_path):
    from logica_mind.stores import SQLiteStore, MultiStore
    from logica_mind.stores.privacy import PrivacyStore
    from logica_mind import Memory, MemoryLayer
    from logica_mind.demo import count
    store = SQLiteStore(str(tmp_path / 'demo.db'))
    store.add([Memory(namespace='astro', layer=MemoryLayer.SEMANTIC, content='Real'),
        Memory(namespace='astro', layer=MemoryLayer.SEMANTIC, content='Fictional metadata', metadata={'demo':True}),
        Memory(namespace='other', layer=MemoryLayer.SEMANTIC, content='Fictional tag', tags=['demo']),
        Memory(namespace='private-cli-other', layer=MemoryLayer.SEMANTIC, content='Private', tags=['demo'], metadata={'memoryScope':'personal'})])
    store.all = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('must not deserialize the archive'))
    mind = LogicaMind(namespace='astro', store=PrivacyStore(MultiStore([store])))
    assert count(mind) == 2
    assert store.demo_count('astro') == 1
