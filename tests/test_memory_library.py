"""Canonical read-only classification + consolidation, offline deterministic fixtures."""
import json
import threading
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from urllib.parse import urlencode

import pytest
from logica_mind import LogicaMind, Memory, MemoryLayer
from logica_mind.stores import SQLiteStore, InMemoryStore
from logica_mind.stores.privacy import PrivacyStore
from logica_mind.library import present, collection_sql, consolidation_evidence
from logica_mind.web.server import make_handler
from logica_mind.dreaming import Dreamer, DreamReport


def record(content, *, layer=MemoryLayer.SEMANTIC, id=None, owner='company-a', project='alpha', **metadata):
    return Memory(content=content, namespace='astro', layer=layer, metadata={'ownerId': owner, 'project': project, **metadata}, **({'id': id} if id else {}))


@pytest.fixture
def archive(tmp_path):
    s = SQLiteStore(str(tmp_path / 'library.db'))
    rows = [
        record('Andre prefere respostas objetivas.'),
        record('Usaremos Expo no aplicativo.', type='decision'),
        record('Mensagem histórica da CLI.', source='cli:codex:auto-capture'),
        record(json.dumps({'mentor_slug':'sec','output':'Parecer com ressalvas.'}), type='mentor_review'),
        record('Organism signals: 42 sinais', source='anima-bus', layer=MemoryLayer.EPISODIC),
        record('{"identity":"agente","version":3}', id='self-model::astro::v3', layer=MemoryLayer.USER),
        record('Pode haver lentidão no servidor.', id='hyp::astro::1'),
        record('```js\nconst x=1;\n```'),
        record('{"summary":"Relatório bruto"}'),
        record('Memória de outra empresa.', owner='company-b'),
        record('Memória de outro projeto.', project='beta'),
        record('Memória pessoal.', memoryScope='personal', actorId='andre'),
        Memory(content='Partição pessoal', namespace='private-cli-test-astro', metadata={'ownerId':'company-a'}),
    ]
    s.add(rows)
    return s, rows


def test_sql_and_presenter_agree_for_legacy_and_typed_records(archive):
    store, originals = archive
    view = PrivacyStore(store)
    before = {m.id: m.content for m in originals}
    counts, all_rows = view.library(collection='all', metadata_filter={'ownerId':'company-a','project':'alpha'})
    assert counts == dict(knowledge=1, decisions=1, conversations=1, executions=1, system=2, review=3)
    assert sum(counts.values()) == len(all_rows) == 9
    for kind, count in counts.items():
        _, rows = view.library(collection=kind, metadata_filter={'ownerId':'company-a','project':'alpha'})
        assert len(rows) == count
        assert all(present(m)['presentation']['collection'] == kind for m in rows)
    assert {m.id: store.get(m.namespace,m.id).content for m in originals} == before
    assert present(originals[3])['presentation']['body'] == 'Parecer com ressalvas.'
    assert consolidation_evidence(originals[4]) is None
    assert consolidation_evidence(originals[6]) is None


def test_shared_agent_claims_are_not_promoted_to_verified_knowledge_by_confidence(tmp_path):
    store = SQLiteStore(str(tmp_path / 'claims.db'))
    claim = record('O próximo deploy falhará sem novos arquivos.', continuity='world-insights', confidence=0.99, agent='qa')
    fact = record('Andre escolheu Expo para o aplicativo.')
    store.add([claim, fact])
    scope = {'ownerId':'company-a', 'project':'alpha'}
    counts, knowledge = store.library(collection='knowledge', metadata_filter=scope)
    assert counts['review'] == 1 and [m.id for m in knowledge] == [fact.id]
    assert present(claim)['presentation']['collection'] == 'review'
    assert consolidation_evidence(claim) is None
    assert store.get(claim.namespace, claim.id).content == claim.content


def test_pagination_filters_before_limit_and_reaches_older_records(archive):
    store, _ = archive
    scope = {'ownerId':'company-a','project':'alpha'}
    for i in range(230):
        store.add([record(f'Aprendizado duradouro número {i:03d}.')])
    counts, page = store.library(metadata_filter=scope, offset=220, limit=20)
    assert counts['knowledge'] == 231 and len(page) == 11
    assert len({m.id for m in page}) == 11
    _, query = store.library(metadata_filter=scope, query='número 003')
    assert len(query) == 1
    store.add([record('Meta comercial 100% preservada.')])
    assert len(store.library(metadata_filter=scope, query='100%')[1]) == 1
    assert store.library(metadata_filter=scope, query="' OR 1=1 --")[1] == []
    with pytest.raises(ValueError):
        store.library(collection="knowledge' OR TRUE --")


def test_http_boundary_counts_and_deep_link(archive, monkeypatch):
    monkeypatch.setenv('LOGICAOS_MULTIUSER','1')
    store, rows = archive
    mind = LogicaMind(namespace='astro', store=store)
    srv = ThreadingHTTPServer(('127.0.0.1',0), make_handler(mind, token='fixture-token'))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    def read(**params):
        req = urllib.request.Request(f'http://127.0.0.1:{srv.server_port}/api/library?'+urlencode({'namespace':'__all__','ownerId':'company-a',**params}), headers={'Authorization':'Bearer fixture-token'})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    try:
        status, data = read(collection='all', project='alpha', limit=2)
        assert status == 200 and len(data['memories']) == 2 and data['total'] == 9 and data['hasMore']
        assert read(ownerId='company-b', collection='all')[1]['total'] == 1
        assert read(ownerId='', collection='all')[0] == 400
        assert read(collection='invalid')[0] == 400
        assert read(layer='invalid')[0] == 400
        linked = read(collection='all', id=rows[3].id)[1]
        assert linked['total'] == 1 and linked['memories'][0]['presentation']['collection'] == 'executions'
        assert read(namespace='private-cli-test-astro')[0] == 400
    finally:
        srv.shutdown(); srv.server_close()


class ExtractLLM:
    available = True
    def __init__(self, invalid=False):
        self.prompts = []; self.invalid = invalid
    def complete_json(self, prompt, system=None):
        self.prompts.append(prompt)
        return {'invalid':'model-output'} if self.invalid else [{'content':'O usuário prefere respostas curtas.','op':'add','dimension':'preference','kind':'preference'}]


def test_consolidation_preserves_scope_sources_and_excludes_telemetry():
    llm = ExtractLLM()
    mind = LogicaMind(namespace='astro',store=InMemoryStore(),llm=llm)
    a = mind.log('Prefiro respostas curtas.',role='user',metadata={'ownerId':'company-a','project':'alpha','type':'conversation'})
    b = mind.log('Prefiro respostas curtas.',role='user',metadata={'ownerId':'company-b','project':'beta','type':'conversation'})
    signal = mind.log('Organism signals: 90 sinais',metadata={'ownerId':'company-a','source':'anima-bus'})
    report=DreamReport(); Dreamer(mind)._consolidate(report)
    facts=mind.store.all('astro',[MemoryLayer.SEMANTIC])
    assert len(facts)==2 and report.distilled==2
    assert {(f.metadata['ownerId'],f.metadata['project']) for f in facts} == {('company-a','alpha'),('company-b','beta')}
    assert {tuple(f.source_ids) for f in facts} == {(a.id,),(b.id,)}
    assert all('role=user' in p and '90 sinais' not in p for p in llm.prompts)
    assert all(f.metadata['memoryKind'] == 'preference' for f in facts)
    assert not signal.metadata.get('consolidated')


def test_invalid_extraction_does_not_promote_raw_or_consume_evidence():
    mind=LogicaMind(namespace='astro',store=InMemoryStore(),llm=ExtractLLM(invalid=True))
    event=mind.log('Prefiro respostas curtas.',role='user',metadata={'ownerId':'company-a'})
    report=DreamReport(); Dreamer(mind)._consolidate(report)
    assert report.distilled==0 and not event.metadata.get('consolidated')
    assert report.consolidation_state=='failed' and report.failed_batches==1
    assert mind.store.all('astro',[MemoryLayer.SEMANTIC]) == []


def test_extracted_explicit_decision_goes_to_decisions_without_changing_raw_text(tmp_path):
    class DecisionLLM(ExtractLLM):
        def complete_json(self, prompt, system=None):
            return [{'content':'Marina decidiu usar Expo no projeto Aurora.', 'op':'add', 'kind':'decision'}]
    store=SQLiteStore(str(tmp_path/'decision.db'))
    mind=LogicaMind(namespace='astro',store=store,llm=DecisionLLM())
    event=mind.log('Decidi usar Expo no projeto Aurora.',role='user',metadata={'ownerId':'company-a','project':'alpha','type':'conversation'})
    Dreamer(mind)._consolidate(DreamReport())
    counts,rows=store.library(collection='decisions',metadata_filter={'ownerId':'company-a','project':'alpha'})
    assert counts['decisions']==1 and rows[0].source_ids==[event.id]
    assert present(rows[0])['presentation']['collection']=='decisions'
    assert store.get('astro',event.id).content=='Decidi usar Expo no projeto Aurora.'


def test_postgres_query_escapes_patterns_and_binds_user_values():
    from logica_mind.library import library_queries
    counts,page=library_queries('mind.memories','id',pg=True,query="100%_ done",metadata_filter={'ownerId':'company-a'})
    assert '100%' not in counts[0] and 'private-cli-%%' in counts[0]
    assert '%100!%!_ done%' in counts[1]
    assert 'company-a' not in counts[0] and 'company-a' in counts[1]


def test_shared_facet_projection_batches_namespaces_and_excludes_private(archive):
    from unittest.mock import patch
    store, _ = archive
    store.add([
        record('Visible public facet.', project='alpha', channel='deck', dimension='work'),
        record('Personal facet.', memoryScope='personal', channel='deck', dimension='work'),
        Memory(namespace='private-cli-actor-astro',content='Private partition facet.',metadata={'channel':'deck','dimension':'work'}),
    ])
    view=PrivacyStore(store)
    with patch.object(view, 'namespaces', side_effect=AssertionError('No N+1 namespace sweep')):
        tagged=view.tagged(None,'channel')
        dimensions=view.dimensioned(None)
    assert tagged == [('Visible public facet.','deck')]
    batched=view.shared_facet_rows()
    assert any(text=='Visible public facet.' for text,_ in batched)
    assert not any('Personal facet' in text or 'Private partition' in text or text.startswith('Organism signals') for text,_ in batched)
    assert dimensions == [('Visible public facet.','work')]
    assert store.shared_facets("source' OR 1=1 --") == []


def test_mention_index_matches_boundaries_and_short_phrases():
    from logica_mind.entity_index import MentionIndex
    index=MentionIndex(['Deck','LogicaOS','Tailwind config js','Ana'])
    assert set(index.matches('Deck and LogicaOS; Deck again.')) == {'Deck','LogicaOS'}
    assert index.matches('banana and decking') == []
    assert index.matches('tailwind config js') == ['Tailwind config js']
    assert len(index.matches('Deck and LogicaOS',limit=1)) == 1


def test_quick_graph_does_not_scan_prose_or_compute_facets():
    from unittest.mock import patch
    store=InMemoryStore()
    mind=LogicaMind(namespace='astro',store=store)
    with patch.object(mind, '_entity_facets',side_effect=AssertionError('heavy facet')), \
         patch.object(mind, '_entity_dimensions',side_effect=AssertionError('heavy dimensions')), \
         patch.object(mind, '_co_mention_links',side_effect=AssertionError('heavy co-mentions')):
        result=mind.graph_viz(summary=True,limit=600)
    assert result['nodes'] == []
