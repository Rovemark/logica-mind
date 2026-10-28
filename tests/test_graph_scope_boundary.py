import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from logica_mind import LogicaMind, Memory, MemoryLayer
from logica_mind.stores import InMemoryStore
from logica_mind.web.server import make_handler


def test_scoped_graph_and_prediction_fail_closed_but_company_gateway_keeps_access():
    store = InMemoryStore()
    for owner, project, subject in [('alice', 'alpha', 'AlicePrivateNode'), ('bob', 'beta', 'BobPrivateNode')]:
        store.add([Memory(namespace='ceo', layer=MemoryLayer.GRAPH, content=subject+' relates Thing', tags=['edge'], metadata={'ownerId':owner, 'project':project, 'subject':subject, 'predicate':'relates', 'object':'Thing'})])
    mind = LogicaMind(namespace='ceo', store=store)
    with patch.dict('os.environ', {'LOGICAOS_MULTIUSER':'1'}):
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(mind, token='fixture-token'))
        thread = threading.Thread(target=lambda:server.serve_forever(poll_interval=.01), daemon=True); thread.start()
        def get(path, gateway=False):
            conn = HTTPConnection('127.0.0.1', server.server_port, timeout=3)
            try:
                headers = {'Authorization':'Bearer fixture-token'}
                if gateway: headers['X-LogicaOS-Company-Mind']='1'
                conn.request('GET',path,headers=headers); resp = conn.getresponse()
                return resp.status, json.loads(resp.read())
            finally: conn.close()
        try:
            path = '/api/graph?namespace=ceo&owner=alice&project=alpha&orphans=1'
            status, payload = get(path)
            assert status == 403 and 'BobPrivateNode' not in json.dumps(payload)
            status, payload = get(path, gateway=True)
            assert status == 200 and {'AlicePrivateNode','BobPrivateNode'} <= {n['id'] for n in payload['nodes']}
            path = '/api/predict?namespace=ceo&owner=alice&project=alpha'
            assert get(path)[0] == 403
            assert get(path, gateway=True)[0] == 200
            assert get('/api/graph?namespace=ceo')[0] == 400
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=3)


def test_spotlight_multiuser_rejects_unscoped_analytics_but_company_gateway_can_search():
    store = InMemoryStore()
    store.add([Memory(namespace='ceo', content='needle-visible', metadata={'ownerId': 'alice', 'project': 'alpha'})])
    mind = LogicaMind(namespace='ceo', store=store)
    with patch.dict('os.environ', {'LOGICAOS_MULTIUSER': '1'}):
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(mind, token='fixture-token'))
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
        thread.start()
        try:
            path = '/api/search?namespace=ceo&owner=alice&project=alpha&q=needle-visible'
            for gateway, expected in [(False, 403), (True, 200)]:
                conn = HTTPConnection('127.0.0.1', server.server_port, timeout=3)
                try:
                    headers = {'Authorization': 'Bearer fixture-token'}
                    if gateway:
                        headers['X-LogicaOS-Company-Mind'] = '1'
                    conn.request('GET', path, headers=headers)
                    response = conn.getresponse(); body = json.loads(response.read())
                    assert response.status == expected
                    if gateway:
                        assert any('needle-visible' in item['memory']['content'] for item in body['memories'])
                    else:
                        assert 'needle-visible' not in json.dumps(body)
                finally:
                    conn.close()
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=3)
