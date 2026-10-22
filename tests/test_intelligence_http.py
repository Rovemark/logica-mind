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
