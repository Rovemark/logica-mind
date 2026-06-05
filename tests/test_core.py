"""Core behavior tests — run with: pytest

All offline: InMemoryStore + HashingEmbedder, no API keys.
"""
import asyncio
import json

from logica_mind import LogicaMind, Memory, MemoryLayer
from logica_mind.stores import InMemoryStore, SQLiteStore, MultiStore
from logica_mind.stores.supabase import SupabaseStore
from logica_mind.mcp_server import MCPServer
from logica_mind import hooks, devtools
from logica_mind.embeddings import HashingEmbedder
from logica_mind.embeddings import VoyageEmbedder
from logica_mind.extract import Extractor, Fact, ExtractOp
from logica_mind.rerank import MMRReranker
from logica_mind.graph import GraphExtractor
from logica_mind._vector import cosine


def mk(ns="t"):
    return LogicaMind(namespace=ns, store=InMemoryStore())


class FakeLLM:
    """Routes by system prompt so one object can stand in for graph extraction,
    fact extraction and dialectic answering in tests."""
    available = True

    def __init__(self, triples=None, facts=None, answer="ANSWER", observations=None):
        self.triples = triples or []
        self.facts = facts or []
        self.answer = answer
        self.observations = observations or []

    def complete(self, prompt, system=None):
        return self.answer

    def complete_json(self, prompt, system=None):
        s = (system or "").lower()
        if "triple" in s:
            return self.triples
        if "observation" in s:           # the deriver's system prompt
            return self.observations
        if "atomic facts" in s:
            return self.facts
        return None


def test_remember_and_recall():
    # the default embedder is lexical (offline) — query with shared vocabulary;
    # real semantic matching needs Voyage/OpenAI.
    m = mk()
    m.remember("The user wants replies in the Portuguese language.")
    m.remember("The user lives in Sao Paulo, Brazil.")
    hits = m.recall("what language does the user want?")
    assert hits
    assert "Portuguese" in hits[0].memory.content


def test_dedup_skips_duplicates():
    m = mk()
    a = m.remember("Maya founded Acme Inc.")
    b = m.remember("Maya founded Acme Inc.")  # exact dup
    assert len(a) == 1
    assert len(b) == 0
    assert m.stats()["semantic"] == 1


def test_log_is_episodic():
    m = mk()
    m.log("we talked about embeddings", role="user")
    assert m.stats()["episodic"] == 1
    assert m.stats()["semantic"] == 0


def test_forget_by_id_and_query():
    m = mk()
    [mem] = m.remember("delete me by id")
    assert m.forget(memory_id=mem.id) == 1
    m.remember("a transient secret token value")
    removed = m.forget(query="a transient secret token value", threshold=0.6)
    assert removed >= 1


def test_temporal_graph_invalidation():
    m = mk()
    m.graph.ingest("Maya", "focus", "Project A")
    m.graph.ingest("Maya", "focus", "Project B")  # supersedes A
    valid = [e for e in m.graph.edges() if e.predicate == "focus"]
    assert len(valid) == 1
    assert valid[0].object == "Project B"
    history = m.graph.edges(include_history=True)
    assert any(e.object == "Project A" and not e.is_valid for e in history)


def test_namespaces_and_aggregate_graph():
    store = InMemoryStore()
    root = LogicaMind(namespace="research", store=store)
    root.for_namespace("research").graph.ingest("Maya", "founded", "Acme")
    root.for_namespace("marketing").graph.ingest("Maya", "leads", "Marketing")
    assert set(store.namespaces()) == {"research", "marketing"}
    viz = root.graph_viz(namespace=None)  # general graph
    maya = [n for n in viz["nodes"] if n["id"] == "Maya"][0]
    assert maya["shared"] is True  # Maya appears in both agents


def _seed_categorized(m):
    """Plant categorized facts + a couple of graph edges (no LLM needed)."""
    def fact(content, dim, cat):
        m.store.add([Memory(content=content, namespace=m.namespace, layer=MemoryLayer.SEMANTIC,
                            metadata={"dimension": dim, "category": cat})])
    fact("Andre founded Acme Corp in 2021", "biz_revenue", "company")
    fact("Acme Corp raised a seed round led by Maya", "biz_funding", "fundraising")
    fact("Andre prefers dark roast coffee", "preference", "food")
    m.graph.ingest("Andre", "founded", "Acme Corp")
    m.graph.ingest("Maya", "invested_in", "Acme Corp")


def _seed_org(m):
    """A small org graph: a hub (Acme) with several people + assets, so paths,
    bridges, co-mentions and centrality are all exercised."""
    g = m.graph
    for p in ["Maya", "Jordan", "Sam", "Priya"]:
        g.ingest(p, "works_at", "Acme")
    g.ingest("Maya", "founded", "Acme")
    g.ingest("Jordan", "leads", "the mobile app")   # the app hangs off Jordan ONLY → he's a bridge
    g.ingest("Sam", "reports_to", "Maya")
    g.ingest("Priya", "reports_to", "Maya")         # Sam & Priya share {Acme, Maya}, no direct edge
    # co-mention facts (no edge between the named pairs)
    def fact(c):
        m.store.add([Memory(content=c, namespace=m.namespace, layer=MemoryLayer.SEMANTIC)])
    fact("Maya and Jordan reviewed the roadmap together.")
    fact("Maya and Jordan met about hiring.")


def test_predicate_class_buckets():
    from logica_mind.graph.analytics import predicate_class
    assert predicate_class("works_at") == "social"
    assert predicate_class("part_of") == "has"
    assert predicate_class("scheduled_for") == "temporal"
    assert predicate_class("blocks") == "causal"
    assert predicate_class("zzz") == "other"


def test_pagerank_ranks_the_hub_highest():
    from logica_mind.graph.analytics import pagerank
    edges = [("Acme", p, 1.0) for p in ["Maya", "Jordan", "Sam", "Priya"]]
    pr = pagerank(["Acme", "Maya", "Jordan", "Sam", "Priya"], edges)
    assert pr["Acme"] == 1.0                       # normalized max = the hub
    assert all(pr[p] < pr["Acme"] for p in ["Maya", "Jordan", "Sam", "Priya"])


def test_graph_viz_tags_kind_weight_and_centrality():
    m = mk()
    _seed_org(m)
    viz = m.graph_viz(namespace="t", layers=["relation", "co_mention"])
    rels = [l for l in viz["links"] if l["kind"] == "relation"]
    assert rels and all("pclass" in l and l["directed"] for l in rels)
    coms = [l for l in viz["links"] if l["kind"] == "co_mention"]
    assert any({l["source"], l["target"]} == {"Maya", "Jordan"} for l in coms)  # co-mentioned 2x
    cby = {n["id"]: n["centrality"] for n in viz["nodes"]}
    assert cby["Acme"] > cby["the mobile app"]     # a hub outranks a leaf


def test_how_related_returns_typed_path():
    m = mk()
    _seed_org(m)
    r = m.how_related("the mobile app", "Sam")
    assert r["found"]
    assert r["path"][0] == "the mobile app" and r["path"][-1] == "Sam"
    assert "Acme" in r["path"]                      # routes through the hub
    assert all(h["predicate"] for h in r["hops"])


def test_bridges_finds_articulation_point():
    m = mk()
    _seed_org(m)
    names = {b["entity"] for b in m.bridges()}
    assert "Jordan" in names                        # removing Jordan isolates the mobile app


def test_suggested_links_predicts_unconnected_pairs():
    m = mk()
    _seed_org(m)
    sug = m.suggested_links(min_common=2)
    # Sam & Priya share ≥2 neighbours (Acme + via people) yet have no edge
    pairs = {frozenset((s["a"], s["b"])) for s in sug}
    assert any(len(p) == 2 for p in pairs)
    assert all(s["score"] > 0 for s in sug)


def test_graph_viz_annotates_entities_with_life_area():
    m = mk()
    _seed_categorized(m)
    nodes = {n["id"]: n for n in m.graph_viz(namespace="t")["nodes"]}
    # Acme Corp is named only by business-group facts → a business dimension
    assert nodes["Acme Corp"].get("dimension", "").startswith("biz_")
    # Andre is named by a personal fact too → resolves to a personal dimension
    assert nodes["Andre"].get("dimension") in ("preference", "biz_revenue")


def test_connections_derives_backlinks_without_manual_links():
    m = mk()
    _seed_categorized(m)
    target = [x for x in m.store.all("t")
              if "founded Acme" in x.content and "edge" not in (x.tags or [])][0]
    conn = m.connections(target.id)
    ents = {e["name"] for e in conn["entities"]}
    assert {"Andre", "Acme Corp"} <= ents
    # typed relations touching those entities are surfaced
    preds = {(r["subject"], r["predicate"], r["object"]) for r in conn["relations"]}
    assert ("Maya", "invested_in", "Acme Corp") in preds
    # auto-backlink: another fact mentioning Acme Corp is linked, with no [[wikilink]]
    linked = {mm["content"] for mm in conn["mentions"]}
    assert any("seed round" in c for c in linked)
    # the target itself is never listed as its own connection
    assert all(mm["id"] != target.id for mm in conn["mentions"] + conn["siblings"])


def test_dreaming_reinforces_recalled_memories():
    m = mk()
    m.remember("important fact about the product roadmap")
    m.recall("product roadmap")          # bumps access_count
    before = m.recall("product roadmap")[0].memory.importance
    m.dream(prune=False)
    after = m.recall("product roadmap")[0].memory.importance
    assert after >= before


def test_dream_consolidation_preserves_categorization():
    # a belief born in a dream must be as queryable as one stated directly:
    # the extractor's category/dimension has to ride onto the distilled fact.
    llm = FakeLLM(facts=[{"content": "The user loves espresso.",
                          "category": "Coffee preference", "dimension": "preference", "op": "add"}])
    m = LogicaMind(namespace="t", store=InMemoryStore(), llm=llm)
    m.log("we talked about coffee this morning")
    m.log("they mentioned espresso again later")
    m.dream(prune=False)
    distilled = [x for x in m.store.all("t", [MemoryLayer.SEMANTIC]) if "distilled" in (x.tags or [])]
    assert distilled, "dream should distill at least one semantic fact"
    assert any((x.metadata or {}).get("dimension") == "preference"
               and (x.metadata or {}).get("category") == "Coffee preference" for x in distilled)


def test_user_model_observe_and_profile():
    m = mk()
    m.observe_user("Likes concise answers.")
    m.observe_user("Works in health-tech.")
    m.user.synthesize()
    profile = m.user_profile()
    assert "concise" in profile.lower() or "health" in profile.lower()


def test_dimension_guard_no_silent_truncation():
    assert abs(cosine([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) - 1.0) < 1e-9
    # mismatched lengths must NOT zip-truncate into a bogus score
    assert cosine([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0


def test_session_scoping_filters_recall():
    m = mk()
    m.remember("The deployment target is staging.", session="alpha")
    m.remember("The deployment target is production.", session="beta")
    a = m.recall("deployment target", session="alpha")
    assert a and all(h.memory.metadata.get("session") == "alpha" for h in a)
    b = m.recall("deployment target", session="beta")
    assert b and all(h.memory.metadata.get("session") == "beta" for h in b)


def test_metadata_filter_recall():
    m = mk()
    m.remember("Ticket about billing.", metadata={"topic": "billing"})
    m.remember("Ticket about latency.", metadata={"topic": "perf"})
    hits = m.recall("ticket", metadata_filter={"topic": "billing"})
    assert hits and all(h.memory.metadata.get("topic") == "billing" for h in hits)


def test_delete_op_removes_memory():
    class DeletingExtractor(Extractor):
        def __init__(self, target_id):
            self.target_id = target_id
        def extract(self, text, existing):
            return [Fact(content="(retracted)", op=ExtractOp.DELETE, target_id=self.target_id)]

    m = mk()
    [mem] = m.remember("Provisional fact to be retracted.", extract=False)
    assert m.get(mem.id) is not None
    m.extractor = DeletingExtractor(mem.id)
    created = m.remember("Actually that fact was wrong.")
    assert created == []
    assert m.get(mem.id) is None


def test_mmr_reranker_runs_and_annotates():
    m = LogicaMind(namespace="t", store=InMemoryStore(), reranker=MMRReranker(lambda_=0.6))
    m.remember("Cats are independent pets that groom themselves.")
    m.remember("Dogs are loyal animals that enjoy long walks.")
    m.remember("Parrots can mimic human speech remarkably well.")
    hits = m.recall("tell me about cats", limit=2)
    assert hits
    assert "mmr" in hits[0].components  # reranker pass executed


def test_track_access_no_write_amplification():
    # memory exists ONLY in store A of a MultiStore; a read must not write into B
    a, b = InMemoryStore(), InMemoryStore()
    emb = HashingEmbedder()
    mem = Memory(content="this lives only in store A", namespace="t",
                 layer=MemoryLayer.SEMANTIC, embedding=emb.embed_one("this lives only in store A"))
    a.add([mem])
    mind = LogicaMind(namespace="t", store=MultiStore([a, b]), embedder=emb)
    hits = mind.recall("this lives only in store A")
    assert hits
    assert len(b.all("t")) == 0                       # B was never written to
    assert a.get("t", mem.id).access_count == 1       # touched once, not doubled


def test_session_dedup_keeps_identical_facts_per_session():
    m = mk()
    a = m.remember("The API key rotates monthly.", session="alpha")
    b = m.remember("The API key rotates monthly.", session="beta")   # identical text
    assert len(a) == 1 and len(b) == 1                # not deduped across sessions
    again = m.remember("The API key rotates monthly.", session="alpha")
    assert again == []                                # still deduped within a session
    assert len(m.recall("api key", session="alpha")) == 1
    assert len(m.recall("api key", session="beta")) == 1


def test_metadata_filter_survives_limit_window():
    # an OLD session row must still be found even when it's outside the newest-N
    # fetch window (filter is pushed into SQL before LIMIT)
    store = SQLiteStore(":memory:", max_candidates=2)
    old = Memory(content="legacy note from session old", namespace="t",
                 layer=MemoryLayer.SEMANTIC, metadata={"session": "old"},
                 created_at="2020-01-01T00:00:00Z")
    store.add([old])
    for i in range(3):  # newer rows that would fill the LIMIT-2 window
        store.add([Memory(content=f"new note {i}", namespace="t",
                          layer=MemoryLayer.SEMANTIC, metadata={"session": "new"},
                          created_at=f"2026-06-0{i+1}T00:00:00Z")])
    hits = store.search("t", None, "legacy note", limit=5, metadata_filter={"session": "old"})
    assert any(h.memory.id == old.id for h in hits)


def test_voyage_dtype_guard_rejects_quantized():
    raised = False
    try:
        VoyageEmbedder(output_dtype="int8", api_key="x")
    except ValueError:
        raised = True
    assert raised


def test_mmr_scores_are_monotonic():
    m = LogicaMind(namespace="t", store=InMemoryStore(), reranker=MMRReranker(lambda_=0.6))
    for t in ["cats purr when content", "dogs bark at strangers",
              "birds sing in the morning", "cats nap most of the day"]:
        m.remember(t)
    hits = m.recall("cats", limit=3)
    assert hits
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)     # reranker owns .score, descending


def test_auto_graph_extraction_from_text():
    llm = FakeLLM(triples=[
        {"subject": "Maya", "predicate": "founded", "object": "Acme Inc",
         "fact": "Maya founded Acme Inc."},
    ])
    m = LogicaMind(namespace="t", store=InMemoryStore(), llm=llm)
    m.remember("Maya founded Acme Inc in 2020.", build_graph=True)
    edges = m.graph.edges()
    assert any(e.subject == "Maya" and e.object == "Acme Inc" for e in edges)


def test_dialectic_query_with_llm():
    llm = FakeLLM(answer="The user prefers concise Brazilian Portuguese.")
    m = LogicaMind(namespace="t", store=InMemoryStore(), llm=llm)
    m.observe_user("Always answers in PT-BR and likes short replies.")
    ans = m.ask_about_user("What language and style should I use?")
    assert "Portuguese" in ans


def test_dialectic_query_offline_fallback_returns_facts():
    m = mk()  # NullLLM
    m.observe_user("The user drinks coffee every morning.")
    ans = m.ask_about_user("what does the user drink?")
    assert "coffee" in ans.lower()


def test_context_respects_token_budget():
    m = mk()
    m.observe_user("Likes concise answers."); m.user.synthesize()
    for t in ["The project ships on Friday.", "The database is Postgres.",
              "The team uses Python.", "The budget is fixed."]:
        m.remember(t)
    ctx = m.context("project details", token_budget=80)
    assert ctx
    assert LogicaMind._approx_tokens(ctx) <= 80  # contract: the result fits the budget


def test_ingest_document_chunks():
    m = mk()
    # distinct sentences so chunks aren't deduped as near-identical
    text = " ".join(
        f"Paragraph {i} explains a unique aspect number {i} of the system design."
        for i in range(40)
    )
    created = m.ingest_document(text, chunk_size=200, overlap=20)
    assert len(created) > 1
    assert all("document" in c.tags for c in created)
    assert all(c.metadata.get("chunk") is not None for c in created)


def test_graph_multivalued_relations_coexist():
    llm = FakeLLM(triples=[
        {"subject": "Alice", "predicate": "speaks", "object": "English", "fact": "Alice speaks English."},
        {"subject": "Alice", "predicate": "speaks", "object": "Spanish", "fact": "Alice speaks Spanish."},
    ])
    m = LogicaMind(namespace="t", store=InMemoryStore(), llm=llm)
    m.learn_graph("Alice speaks English and Spanish.")
    valid = [e for e in m.graph.edges() if e.predicate == "speaks"]
    assert len(valid) == 2  # neither invalidates the other (same text, multi-valued)


def test_graph_edge_dedup_idempotent():
    llm = FakeLLM(triples=[{"subject": "Bob", "predicate": "lives_in", "object": "Paris", "fact": "Bob lives in Paris."}])
    m = LogicaMind(namespace="t", store=InMemoryStore(), llm=llm)
    m.learn_graph("Bob lives in Paris.")
    m.learn_graph("Bob lives in Paris.")  # same fact again
    valid = [e for e in m.graph.edges() if e.is_valid and e.subject == "Bob"]
    assert len(valid) == 1  # idempotent, no duplicate edge


def test_graph_close_preserves_embedding():
    m = mk()  # InMemoryStore + HashingEmbedder
    m.graph.ingest("Carol", "focus", "ProjectA")
    m.graph.ingest("Carol", "focus", "ProjectB")  # supersedes ProjectA
    closed = [e for e in m.graph.edges(include_history=True) if e.object == "ProjectA"][0]
    assert not closed.is_valid
    stored = m.store.get("t", closed.id)
    assert stored is not None and stored.embedding is not None  # embedding survived the close


def test_graph_extractor_coerces_nonstring_and_unwraps_dict():
    # non-string object must not crash
    ge = GraphExtractor(FakeLLM(triples=[
        {"subject": "X", "predicate": "value_is", "object": 42, "fact": "X is 42"}]))
    triples = ge.extract("x")
    assert triples and triples[0].object == "42"
    # dict-wrapped list must be unwrapped
    ge2 = GraphExtractor(FakeLLM(triples={"triples": [
        {"subject": "A", "predicate": "knows", "object": "B", "fact": "A knows B"}]}))
    t2 = ge2.extract("x")
    assert t2 and t2[0].subject == "A"


def test_graph_confidence_rating():
    m = mk()
    m.graph.ingest("A", "relates_to", "B", confidence=0.7)
    e = m.graph.edges()[0]
    assert e.confidence == 0.7
    assert m.graph.to_viz()["links"][0]["confidence"] == 0.7


def test_point_in_time_query():
    m = mk()
    m.graph.ingest("Maya", "focus", "ProjectA", ts="2026-01-01T00:00:00Z")
    m.graph.ingest("Maya", "focus", "ProjectB", ts="2026-06-01T00:00:00Z")  # closes A
    march = m.graph.edges(at="2026-03-01T00:00:00Z")
    assert any(e.object == "ProjectA" for e in march)
    assert not any(e.object == "ProjectB" for e in march)
    july = m.graph.edges(at="2026-07-01T00:00:00Z")
    assert any(e.object == "ProjectB" for e in july)
    assert not any(e.object == "ProjectA" for e in july)


def test_graph_communities():
    m = mk()
    m.graph.ingest("A", "r", "B")
    m.graph.ingest("B", "r", "C")   # A-B-C
    m.graph.ingest("X", "r", "Y")   # X-Y (separate cluster)
    comms = m.graph.communities()
    assert len(comms) == 2
    assert sorted(len(c["nodes"]) for c in comms) == [2, 3]


def test_entity_boosted_retrieval():
    m = LogicaMind(namespace="t", store=InMemoryStore(), entity_boost=0.5)
    m.graph.ingest("Northwind", "is", "a project")
    m.remember("Northwind launched a new feature.")
    m.remember("The weather is nice today.")
    hits = m.recall("tell me about Northwind")
    assert hits and "Northwind" in hits[0].memory.content
    assert hits[0].components.get("entity_boost") == 0.5


def test_async_api():
    async def go():
        m = mk()
        await m.aremember("Async fact about testing the event loop.")
        return await m.arecall("testing event loop")
    hits = asyncio.run(go())
    assert hits


def test_mcp_server_handshake_and_tools():
    srv = MCPServer(mk())
    init = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"protocolVersion": "2024-11-05"}})
    assert init["result"]["serverInfo"]["name"] == "logica-mind"
    assert srv.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    tl = srv.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = [t["name"] for t in tl["result"]["tools"]]
    assert "lm_remember" in names and "lm_recall" in names
    srv.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "lm_remember", "arguments": {"text": "MCP plugs into Logica Mind."}}})
    res = srv.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                      "params": {"name": "lm_recall", "arguments": {"query": "MCP"}}})
    assert "MCP" in res["result"]["content"][0]["text"]
    err = srv.handle({"jsonrpc": "2.0", "id": 5, "method": "does_not_exist"})
    assert err["error"]["code"] == -32601


def test_point_in_time_handles_offset_and_fractional_timestamps():
    m = mk()
    # stored valid_from in offset form (as Supabase would return it)
    m.graph.ingest("Maya", "focus", "P1", ts="2026-01-01T12:00:00.123456+00:00")
    # query with canonical 'Z' form — lexical compare would break, datetime works
    assert any(e.object == "P1" for e in m.graph.edges(at="2026-03-01T00:00:00Z"))
    assert not any(e.object == "P1" for e in m.graph.edges(at="2025-12-01T00:00:00Z"))
    # non-UTC offset 'at' (03:00-03:00 == 06:00Z, still after valid_from)
    assert any(e.object == "P1" for e in m.graph.edges(at="2026-03-01T03:00:00-03:00"))


def test_confidence_is_clamped():
    m = mk()
    m.graph.ingest("A", "likes", "jazz", confidence=5.0)
    m.graph.ingest("A", "likes", "rock", confidence=-2.0, single_valued=False)
    confs = {e.object: e.confidence for e in m.graph.edges()}
    assert confs["jazz"] == 1.0 and confs["rock"] == 0.0


def test_graph_edge_importance_is_neutral():
    m = mk()
    m.graph.ingest("A", "r", "B")  # default confidence 1.0
    edge_mem = m.store.all("t", [MemoryLayer.GRAPH])[0]
    assert edge_mem.importance == 0.5  # not lifted to 1.0; semantic facts stay competitive


def test_entity_boost_no_substring_false_positive():
    m = LogicaMind(namespace="t", store=InMemoryStore(), entity_boost=0.5)
    m.graph.ingest("rain", "is", "weather")  # 'rain' must NOT match 'training'
    m.remember("The training pipeline is slow.")
    hits = m.recall("training")
    assert hits
    assert all(h.components.get("entity_boost") is None for h in hits)


def test_mcp_notifications_version_and_argcheck():
    srv = MCPServer(mk())
    # a known method without 'id' is a notification → no reply
    assert srv.handle({"jsonrpc": "2.0", "method": "ping"}) is None
    assert srv.handle({"jsonrpc": "2.0", "id": 7, "method": "ping"})["result"] == {}
    # unsupported protocol version negotiated down to the server's own
    init = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"protocolVersion": "2099-01-01"}})
    assert init["result"]["protocolVersion"] == "2024-11-05"
    # missing required arg → clean message, not a raw KeyError
    res = srv.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                      "params": {"name": "lm_remember", "arguments": {}}})
    assert res["result"]["isError"]
    assert "missing required argument" in res["result"]["content"][0]["text"]


def test_mcp_stdio_survives_non_object_json():
    import io
    srv = MCPServer(mk())
    out = io.StringIO()
    srv.serve_stdio(
        stdin=io.StringIO('[1,2,3]\n{"jsonrpc":"2.0","id":1,"method":"ping"}\n'),
        stdout=out,
    )
    lines = [json.loads(l) for l in out.getvalue().strip().split("\n")]
    assert lines[0]["error"]["code"] == -32600  # invalid request, didn't crash
    assert lines[1]["result"] == {}             # loop continued to the next message


def test_hook_userpromptsubmit_saves_and_injects():
    m = LogicaMind(namespace="t", store=InMemoryStore())
    m.remember("The project uses Postgres for storage.")
    out = hooks.handle("userpromptsubmit",
                       {"prompt": "what storage does the project use?", "session_id": "s1"}, m)
    assert m.stats()["episodic"] >= 1                       # the prompt was captured
    assert out and "Postgres" in out["hookSpecificOutput"]["additionalContext"]  # memory injected


def test_hook_sessionstart_brief():
    m = LogicaMind(namespace="t", store=InMemoryStore())
    m.observe_user("Prefers PT-BR."); m.user.synthesize()
    m.remember("Important architectural decision: use event sourcing.", importance=0.9)
    out = hooks.handle("sessionstart", {"cwd": "/x/proj"}, m)
    assert out and "event sourcing" in out["hookSpecificOutput"]["additionalContext"]


def test_hook_stop_saves_assistant_turn():
    import tempfile, os as _os
    lines = [
        json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}}),
        json.dumps({"type": "assistant", "message": {"role": "assistant",
                    "content": [{"type": "text", "text": "I refactored the auth module."}]}}),
    ]
    tf = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    tf.write("\n".join(lines)); tf.close()
    m = LogicaMind(namespace="t", store=InMemoryStore())
    hooks.handle("stop", {"transcript_path": tf.name, "session_id": "s1"}, m)
    _os.unlink(tf.name)
    eps = m.store.all("t", [MemoryLayer.EPISODIC])
    assert any("refactored the auth" in e.content for e in eps)


def test_hook_run_smoke_with_patched_mind():
    m = LogicaMind(namespace="t", store=InMemoryStore())
    m.remember("The deploy script lives in scripts/deploy.sh.")
    orig = hooks._build_mind
    hooks._build_mind = lambda payload, *a, **k: m
    try:
        out = hooks.run("userpromptsubmit",
                        stdin_text=json.dumps({"prompt": "where is the deploy script?", "session_id": "s1"}))
    finally:
        hooks._build_mind = orig
    assert out
    data = json.loads(out)
    assert "deploy" in data["hookSpecificOutput"]["additionalContext"].lower()


def test_install_hooks_idempotent():
    import tempfile, os as _os, shutil
    d = tempfile.mkdtemp()
    try:
        sp = _os.path.join(d, "settings.json")
        path, added = hooks.install(sp)
        assert set(added) == {"SessionStart", "UserPromptSubmit", "Stop", "PreCompact"}
        data = json.load(open(sp))
        cmd = data["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        assert cmd.endswith("hook sessionstart")   # pinned invocation + event
        _, added2 = hooks.install(sp)         # second run is a no-op
        assert added2 == []
    finally:
        shutil.rmtree(d)


def test_namespace_avoids_basename_collision():
    a = hooks._namespace({"cwd": "/tmp/clientX/app"})
    b = hooks._namespace({"cwd": "/tmp/clientY/app"})
    assert a != b                              # same basename, different paths
    assert a == hooks._namespace({"cwd": "/tmp/clientX/app"})  # stable


def test_consolidate_no_llm_leaves_turns_unmarked():
    m = mk()  # NullLLM
    m.log("we discussed the rate limiter design", role="user")
    m.log("we shipped the retry backoff", role="assistant")
    m.dream(prune=False)  # offline: must NOT mark turns consolidated
    eps = m.store.all("t", [MemoryLayer.EPISODIC])
    assert eps and all(not (e.metadata or {}).get("consolidated") for e in eps)


def test_session_brief_dedups_and_no_dangling_header():
    m = mk()
    for _ in range(3):
        m.log("run the tests", role="user")          # repeated identical turns
    m.remember("The service is written in Go.", importance=0.9)
    brief = m.session_brief(token_budget=400)
    # episodic repeats collapsed to one line
    assert brief.count("- run the tests") == 1
    # no header is emitted without at least one body line under it
    for header in ("## What I know about you", "## From past sessions", "## Recent activity"):
        if header in brief:
            after = brief.split(header, 1)[1].lstrip("\n")
            assert after.startswith("- ") or after.startswith("-")


def test_now_iso_canonical_whole_second_format():
    from logica_mind.types import now_iso
    ts = now_iso()
    # one consistent format (no fractional part that would break lexical ordering
    # against legacy rows); same-second ties resolved by SQLite rowid
    assert ts.endswith("Z") and "." not in ts and len(ts) == 20


def test_devtools_execute_summary():
    r = devtools.execute("print(40 + 2)", lang="python")
    assert r["exit_code"] == 0 and "42" in r["stdout"]
    r2 = devtools.execute("import sys; sys.exit(3)", lang="python")
    assert r2["exit_code"] == 3


def test_devtools_scan_detects_language():
    import tempfile, os as _os, shutil
    d = tempfile.mkdtemp()
    try:
        with open(_os.path.join(d, "app.py"), "w") as f:
            f.write("x = 1\n")
        with open(_os.path.join(d, "pyproject.toml"), "w") as f:
            f.write("[project]\nname='x'\n")
        dna = devtools.scan(d)
        assert any(l["name"] == "Python" for l in dna["languages"])
        assert "pyproject.toml" in dna["key_files"]
    finally:
        shutil.rmtree(d)


def test_devtools_git_non_repo():
    import tempfile, shutil
    d = tempfile.mkdtemp()
    try:
        assert devtools.git(d).get("error") == "not a git repository"
    finally:
        shutil.rmtree(d)


def test_devtools_budget_and_mcp_aggregate():
    assert "72%" in devtools.budget_bar(144000, 200000)
    import tempfile, os as _os, shutil
    d = tempfile.mkdtemp()
    try:
        with open(_os.path.join(d, ".mcp.json"), "w") as f:
            json.dump({"mcpServers": {"supabase": {}, "notion": {}}}, f)
        agg = devtools.mcp_aggregate(d)   # may also pick up global ~/.claude.json servers
        names = [s["name"] for s in agg["servers"]]
        assert "supabase" in names and "notion" in names
        assert agg["est_context_cost"] == 800 * agg["active"]
    finally:
        shutil.rmtree(d)


def test_mcp_devtools_and_team_tools():
    srv = MCPServer(mk())
    names = [t["name"] for t in srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]]
    for t in ("lm_execute", "lm_scan", "lm_git", "lm_budget", "lm_team_push", "lm_team_search"):
        assert t in names
    # execute through the MCP surface
    res = srv.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                      "params": {"name": "lm_execute", "arguments": {"command": "print('hi-mcp')", "lang": "python"}}})
    assert "hi-mcp" in res["result"]["content"][0]["text"]
    # team KB push + search (local fallback)
    srv.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "lm_team_push", "arguments": {"text": "Team convention: use conventional commits."}}})
    res2 = srv.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                       "params": {"name": "lm_team_search", "arguments": {"query": "what commit convention?"}}})
    assert "conventional commits" in res2["result"]["content"][0]["text"]


def test_truncate_zero_budget():
    assert devtools._truncate("hello", 0) == ("", True)
    assert devtools._truncate("", 0) == ("", False)
    assert devtools._truncate("short", 100) == ("short", False)


def test_git_path_handles_rename():
    assert devtools._git_path("R  old.txt -> new.txt") == "new.txt"
    assert devtools._git_path("M  file.py") == "file.py"


def test_team_kb_refuses_supabase_with_offline_embedder():
    import os as _os
    srv = MCPServer(mk())   # HashingEmbedder (dim 256)
    saved = {k: _os.environ.get(k) for k in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "SUPABASE_KEY")}
    _os.environ["SUPABASE_URL"] = "https://x.supabase.co"
    _os.environ["SUPABASE_SERVICE_KEY"] = "k"
    try:
        # a hashing (offline) embedder must never read/write the shared Supabase table
        assert srv._remote_team_mind() is None
    finally:
        for k, v in saved.items():
            if v is None:
                _os.environ.pop(k, None)
            else:
                _os.environ[k] = v


def test_graph_bfs():
    m = mk()
    m.graph.ingest("A", "to", "B")
    m.graph.ingest("B", "to", "C")
    m.graph.ingest("C", "to", "D")
    out = m.graph.bfs("A", depth=2)
    assert out["levels"].get("a") == 0
    assert out["levels"].get("b") == 1
    assert out["levels"].get("c") == 2
    assert "d" not in out["levels"]          # 3 hops away, beyond depth=2


def test_ingest_json():
    m = mk()
    created = m.ingest_json({"name": "Maya", "stack": ["python", "typescript"], "active": True})
    contents = [c.content for c in created]
    assert any("name = Maya" in c for c in contents)
    assert any("stack[0] = python" in c for c in contents)
    assert all("json" in c.tags for c in created)


def test_reflect_offline_returns_digest():
    m = mk()
    m.remember("The team adopted trunk-based development.")
    m.remember("CI now runs on every push.")
    text = m.reflect()
    assert "trunk-based" in text or "CI" in text
    # the reflection is stored as a tagged semantic memory
    assert any("reflection" in mm.tags for mm in m.store.all("t", [MemoryLayer.SEMANTIC]))


def test_graph_rerankers_run():
    from logica_mind.rerank import NodeDistanceReranker, EpisodeMentionReranker
    m = LogicaMind(namespace="t", store=InMemoryStore(),
                   reranker=NodeDistanceReranker(graph=None, weight=0.2))
    m.reranker.graph = m.graph
    m.graph.ingest("Northwind", "uses", "Postgres")
    m.remember("Northwind migration notes for Postgres.")
    m.remember("Unrelated note about coffee.")
    hits = m.recall("tell me about Northwind", limit=3)
    assert hits and "Northwind" in hits[0].memory.content
    # episode-mention reranker runs without error
    m2 = LogicaMind(namespace="t2", store=InMemoryStore(), reranker=EpisodeMentionReranker())
    m2.remember("a fact")
    assert m2.recall("fact") is not None


def test_export_import_migrate():
    m = LogicaMind(namespace="t", store=InMemoryStore())
    m.remember("fact one about deploys")
    m.remember("fact two about caching")
    dump = m.export()
    assert len(dump) == 2

    m2 = LogicaMind(namespace="t", store=InMemoryStore())
    assert m2.import_memories(dump) == 2
    assert m2.stats()["semantic"] == 2

    dst = InMemoryStore()
    assert m.migrate_to(dst) == 2
    assert len(dst.all("t")) == 2


def test_langchain_memory_adapter():
    from logica_mind.integrations import LangChainMemory
    m = LogicaMind(namespace="t", store=InMemoryStore())
    mem = LangChainMemory(m)
    assert mem.memory_variables == ["history"]
    mem.save_context({"input": "My database is Postgres."}, {"output": "Noted."})
    out = mem.load_memory_variables({"input": "what database do we use?"})
    assert "Postgres" in out["history"]


def test_llamaindex_memory_adapter():
    from logica_mind.integrations import LlamaIndexMemory
    m = LogicaMind(namespace="t", store=InMemoryStore())
    mem = LlamaIndexMemory(m)
    mem.put({"role": "user", "content": "We deploy on Fridays."})
    got = mem.get("when do we deploy?")
    assert any("Friday" in g["content"] for g in got)


def test_web_post_remember_and_recall():
    import threading, time, urllib.request, urllib.parse
    from http.server import ThreadingHTTPServer
    from logica_mind.web.server import make_handler
    root = LogicaMind(namespace="proj", store=InMemoryStore())
    srv = ThreadingHTTPServer(("127.0.0.1", 8771), make_handler(root))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    time.sleep(0.2)
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8771/api/remember", method="POST",
            data=json.dumps({"namespace": "proj", "text": "The queue uses RabbitMQ."}).encode(),
            headers={"content-type": "application/json"})
        urllib.request.urlopen(req)
        d = json.load(urllib.request.urlopen(
            "http://127.0.0.1:8771/api/recall?namespace=proj&q=" + urllib.parse.quote("what queue do we use")))
        assert any("RabbitMQ" in r["memory"]["content"] for r in d["results"])
    finally:
        srv.shutdown()
        srv.server_close()   # release the listening socket now (shutdown() alone races into EADDRINUSE)


def test_ingest_json_keeps_distinct_numeric_and_dedups_exact():
    m = mk()
    created = m.ingest_json({"items": list(range(10))})
    assert len(created) == 10                      # short/numeric values NOT collapsed
    again = m.ingest_json({"items": list(range(10))})
    assert again == []                             # exact lines dedup
    # empty containers are recorded
    c2 = m.ingest_json({"cfg": {}, "list": [], "n": 1})
    assert any(c.content.endswith("= {}") for c in c2)


def test_reflect_no_duplicate_rows():
    m = mk()
    m.remember("We migrated to Kubernetes.")
    m.reflect()
    m.reflect()
    refl = [mm for mm in m.store.all("t", [MemoryLayer.SEMANTIC]) if "reflection" in mm.tags]
    assert len(refl) == 1


def test_edge_provenance_merges_sources():
    m = mk()
    m.graph.ingest("Bob", "lives_in", "Paris", source_ids=["ep1"])
    m.graph.ingest("Bob", "lives_in", "Paris", source_ids=["ep2"])
    edges = [e for e in m.graph.edges() if e.subject == "Bob"]
    assert len(edges) == 1
    assert sorted(edges[0].source_ids) == ["ep1", "ep2"]


def test_node_distance_reranker_drops_short_entity():
    from logica_mind.rerank import NodeDistanceReranker
    m = LogicaMind(namespace="t", store=InMemoryStore(),
                   reranker=NodeDistanceReranker(graph=None))
    m.reranker.graph = m.graph
    m.graph.ingest("AI", "is", "a field")          # 'AI' (2 chars) must be ignored
    m.remember("the ai winter was a long period")
    hits = m.recall("tell me about AI")
    assert all("graph_distance" not in (h.components or {}) for h in hits)


def test_web_post_namespace_create_vs_malformed():
    import threading, time, urllib.request, urllib.error
    from http.server import ThreadingHTTPServer
    from logica_mind.web.server import make_handler
    root = LogicaMind(namespace="known", store=InMemoryStore())
    srv = ThreadingHTTPServer(("127.0.0.1", 8772), make_handler(root))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    time.sleep(0.2)

    def post(ns):
        req = urllib.request.Request(
            "http://127.0.0.1:8772/api/remember", method="POST",
            data=json.dumps({"namespace": ns, "text": "x"}).encode(),
            headers={"content-type": "application/json"})
        try:
            return urllib.request.urlopen(req).status
        except urllib.error.HTTPError as e:
            return e.code
    try:
        # a well-formed NEW namespace is created on first write (bootstrap an agent)
        assert post("new-agent") == 200
        assert "new-agent" in root.store.namespaces()
        # a malformed namespace is rejected
        assert post("../etc/passwd") == 400
        assert post("a b c") == 400
    finally:
        srv.shutdown()
        srv.server_close()   # release the listening socket now (shutdown() alone races into EADDRINUSE)


def test_min_importance_and_category_filters():
    m = mk()
    m.remember("low priority note about logging", importance=0.2, extract=False)
    m.remember("high priority note about security", importance=0.9, extract=False)
    hits = m.recall("priority note", min_importance=0.7)
    assert hits and all(h.memory.importance >= 0.7 for h in hits)
    assert not any("logging" in h.memory.content for h in hits)
    m.remember("billing ticket about invoices", category="billing", extract=False)
    cat = m.recall("ticket", category="billing")
    assert cat and all(h.memory.metadata.get("category") == "billing" for h in cat)


def test_peers_multi_perspective():
    m = mk()
    m.observe_peer("Alice", "Bob", "Bob is an expert in jazz piano.")
    m.observe_peer("Carol", "Bob", "Bob dislikes early meetings.")
    card = m.peer_card("Alice", "Bob")
    assert "jazz" in card.lower() and "meeting" not in card.lower()  # directional, not merged


def test_contradictions_tracks_change():
    m = mk()
    m.graph.ingest("Maya", "focus", "ProjA")
    m.graph.ingest("Maya", "focus", "ProjB")
    cs = m.contradictions()
    assert any(c["subject"] == "Maya" and c["predicate"] == "focus" and len(c["history"]) == 2 for c in cs)


def test_diff_changelog():
    m = mk()
    m.store.add([Memory(content="old fact", namespace="t", layer=MemoryLayer.SEMANTIC, created_at="2020-01-01T00:00:00Z")])
    m.store.add([Memory(content="new fact", namespace="t", layer=MemoryLayer.SEMANTIC, created_at="2026-06-01T00:00:00Z")])
    d = m.diff("2026-01-01T00:00:00Z")
    assert [x["content"] for x in d] == ["new fact"]


def test_forget_about_and_purge():
    m = mk()
    m.remember("Maya founded Acme.", extract=False)
    m.graph.ingest("Maya", "founded", "Acme")
    assert m.forget_about("Maya") >= 2
    assert not any("Maya" in mm.content for mm in m.store.all("t"))
    m.remember("anything", extract=False)
    assert m.purge() >= 1 and m.stats()["total"] == 0


def test_transfer_cross_agent():
    store = InMemoryStore()
    a = LogicaMind(namespace="agent-a", store=store)
    a.remember("The deploy uses Docker and k8s.", extract=False)
    assert a.transfer_to("agent-b", "deploy") >= 1
    assert any("Docker" in mm.content for mm in store.all("agent-b"))


def test_rrf_reranker():
    from logica_mind.rerank import RRFReranker
    m = LogicaMind(namespace="t", store=InMemoryStore(), reranker=RRFReranker())
    m.remember("alpha fact about cats")
    m.remember("beta fact about cats")
    hits = m.recall("cats fact")
    assert hits and "rrf" in hits[0].components


def test_decay_per_layer():
    from logica_mind.dreaming import Dreamer
    m = mk()
    m.store.add([Memory(content="stale semantic", namespace="t", layer=MemoryLayer.SEMANTIC,
                        importance=0.1, created_at="2020-01-01T00:00:00Z")])
    Dreamer(m, prune_layers=[MemoryLayer.SEMANTIC], reinforce=False, synthesize_user=False).run()
    assert m.stats()["semantic"] == 0


def test_purge_and_delete_layers():
    m = mk()
    m.log("hello", role="user")
    m.store.add([Memory(content="durable", namespace="t", layer=MemoryLayer.SEMANTIC)])
    assert m.store.count("t") == 2
    # bulk delete one layer leaves the other
    removed = m.store.delete_layers("t", [MemoryLayer.EPISODIC])
    assert removed == 1 and m.store.count("t", [MemoryLayer.SEMANTIC]) == 1
    # purge wipes everything in the namespace
    assert m.purge() == 1 and m.store.count("t") == 0


def test_delete_layers_sqlite(tmp_path):
    m = LogicaMind(namespace="t", store=SQLiteStore(str(tmp_path / "m.db")))
    m.store.add([
        Memory(content="ep", namespace="t", layer=MemoryLayer.EPISODIC),
        Memory(content="se", namespace="t", layer=MemoryLayer.SEMANTIC),
    ])
    assert m.store.delete_layers("t", [MemoryLayer.EPISODIC]) == 1
    assert m.store.count("t") == 1
    assert m.store.delete_layers("t") == 1
    assert m.store.count("t") == 0


def test_peer_observation_is_directional():
    m = mk()
    m.observe_peer("alice", "bob", "Bob ships fast.")
    m.observe_peer("carol", "bob", "Bob is quiet.")
    card = m.peer_card("alice", "bob")
    # alice's card on bob must not leak carol's observation
    assert "ships fast" in card.lower()
    assert "quiet" not in card.lower()


def test_contradictions_tracks_changed_objects():
    llm = FakeLLM(triples=[
        {"subject": "Bob", "predicate": "lives_in", "object": "Paris", "fact": "Bob lives in Paris."},
    ])
    m = LogicaMind(namespace="t", store=InMemoryStore(), llm=llm)
    m.graph.ingest_text("Bob lives in Paris.", m.graph_extractor)
    llm.triples = [{"subject": "Bob", "predicate": "lives_in", "object": "Berlin", "fact": "Bob lives in Berlin."}]
    m.graph.ingest_text("Bob lives in Berlin.", m.graph_extractor)
    c = m.contradictions()
    assert any("bob" in str(x).lower() for x in c)


def test_diff_window_filters_by_time():
    m = mk()
    m.store.add([
        Memory(content="old", namespace="t", layer=MemoryLayer.SEMANTIC, created_at="2020-01-01T00:00:00Z"),
        Memory(content="new", namespace="t", layer=MemoryLayer.SEMANTIC, created_at="2026-01-01T00:00:00Z"),
    ])
    out = m.diff(since="2025-01-01T00:00:00Z")
    assert [d["content"] for d in out] == ["new"]


def test_forget_about_no_substring_false_positive():
    m = mk()
    m.store.add([
        Memory(content="ana likes coffee", namespace="t", layer=MemoryLayer.SEMANTIC),
        Memory(content="banana bread recipe", namespace="t", layer=MemoryLayer.SEMANTIC),
    ])
    removed = m.forget_about("ana")
    # must not also erase "banana" by substring
    assert removed == 1
    remaining = [x.content for x in m.store.all("t")]
    assert "banana bread recipe" in remaining


def test_transfer_to_copies_with_provenance():
    src = LogicaMind(namespace="src", store=InMemoryStore())
    dst = LogicaMind(namespace="dst", store=src.store)
    src.remember("The project ships in July.", extract=False)
    n = src.transfer_to(dst, "when does the project ship")
    assert n >= 1
    moved = [x for x in dst.store.all("dst") if x.metadata.get("from") == "src"]
    assert moved and "transferred" in (moved[0].tags or [])


def test_langchain_distil_throttle():
    from logica_mind.integrations.langchain import LogicaMindMemory
    calls = {"n": 0}
    m = mk()
    orig = m.remember
    def counting(*a, **k):
        calls["n"] += 1
        return orig(*a, **k)
    m.remember = counting
    mem = LogicaMindMemory(m, distil_every=2)
    for i in range(4):
        mem.save_context({"input": f"msg {i}"}, {"output": "ok"})
    # distil only every 2nd turn → 2 extractions for 4 turns
    assert calls["n"] == 2
    # episodic still has every turn logged
    assert m.store.count("t", [MemoryLayer.EPISODIC]) == 8  # 4 user + 4 ai


def test_diff_handles_mixed_timestamp_formats():
    # a microsecond+offset row just after the 'Z' boundary must be INCLUDED
    m = mk()
    m.store.add([
        Memory(content="just after", namespace="t", layer=MemoryLayer.SEMANTIC,
               created_at="2026-06-01T00:00:00.500000+00:00"),
        Memory(content="before", namespace="t", layer=MemoryLayer.SEMANTIC,
               created_at="2026-05-01T00:00:00Z"),
    ])
    out = m.diff(since="2026-06-01T00:00:00Z")
    assert [d["content"] for d in out] == ["just after"]


def test_rrf_ties_get_equal_scores():
    from logica_mind.rerank.rrf import RRFReranker
    from logica_mind.types import SearchResult
    rr = RRFReranker()
    rs = [SearchResult(memory=Memory(content=f"f{i}", namespace="t", importance=0.5),
                       score=0.9, components={"similarity": 0.9, "recency": 0.0}) for i in range(3)]
    out = rr.rerank("q", rs, top_k=3)
    scores = {r.components["rrf"] for r in out}
    assert len(scores) == 1  # genuine ties → one shared fused score


def test_dream_never_prunes_open_graph_edge():
    from logica_mind.dreaming import Dreamer
    llm = FakeLLM(triples=[{"subject": "Bob", "predicate": "lives_in", "object": "Paris", "fact": "Bob lives in Paris."}])
    m = LogicaMind(namespace="t", store=InMemoryStore(), llm=llm, half_life_days=1)
    m.graph.ingest("Bob", "lives_in", "Paris", ts="2000-01-01T00:00:00Z")  # ancient, weak
    # force GRAPH into prune_layers — __init__ should strip it, and _prune guards too
    d = Dreamer(m, prune_layers=[MemoryLayer.EPISODIC, MemoryLayer.GRAPH],
                reinforce=False, synthesize_user=False)
    assert MemoryLayer.GRAPH not in d.prune_layers
    d.run()
    assert m.stats()["graph"] == 1  # open edge survives


def test_dream_never_prunes_user_layer():
    from logica_mind.dreaming import Dreamer
    m = mk()
    m.observe_user("User likes terse answers.")  # USER observation, ancient/weak path
    for mem in m.store.all("t", [MemoryLayer.USER]):
        mem.created_at = "2000-01-01T00:00:00Z"
        m.store.add([mem])
    d = Dreamer(m, prune_layers=[MemoryLayer.USER], reinforce=False, synthesize_user=False)
    assert MemoryLayer.USER not in d.prune_layers
    d.run()
    assert m.stats()["user"] >= 1


def test_timerange_is_true_min_max():
    m = mk()
    m.store.add([
        Memory(content="a", namespace="t", layer=MemoryLayer.SEMANTIC, created_at="2024-01-01T00:00:00Z"),
        Memory(content="b", namespace="t", layer=MemoryLayer.SEMANTIC, created_at="2026-01-01T00:00:00Z"),
    ])
    lo, hi = m.store.timerange("t")
    assert lo == "2024-01-01T00:00:00Z" and hi == "2026-01-01T00:00:00Z"


def test_timerange_sqlite(tmp_path):
    m = LogicaMind(namespace="t", store=SQLiteStore(str(tmp_path / "m.db")))
    m.store.add([
        Memory(content="a", namespace="t", layer=MemoryLayer.SEMANTIC, created_at="2024-01-01T00:00:00Z"),
        Memory(content="b", namespace="t", layer=MemoryLayer.SEMANTIC, created_at="2026-01-01T00:00:00Z"),
    ])
    assert m.store.timerange("t") == ("2024-01-01T00:00:00Z", "2026-01-01T00:00:00Z")


def test_transfer_preserves_importance():
    src = LogicaMind(namespace="src", store=InMemoryStore())
    dst = LogicaMind(namespace="dst", store=src.store)
    src.remember("Low-rated fact about widgets.", importance=0.2, extract=False)
    src.transfer_to(dst, "widgets")
    moved = [x for x in dst.store.all("dst") if x.metadata.get("from") == "src"]
    assert moved and abs(moved[0].importance - 0.2) < 1e-9


def test_recall_conflicting_category_raises():
    import pytest
    m = mk()
    m.remember("x", category="a")
    with pytest.raises(ValueError):
        m.recall("x", metadata_filter={"category": "a"}, category="b")


def test_peer_obs_newest_via_created_at():
    # a store that returns rows newest-first must still yield newest in the tail
    m = mk()
    for i in range(3):
        ob = m.observe_peer("a", "b", f"obs {i}")
        ob.created_at = f"2026-01-0{i+1}T00:00:00Z"
        m.store.add([ob])
    got = m._peer_obs("a", "b")
    assert [x.content for x in got][-1] == "obs 2"  # newest last


def test_ingest_conversation_logs_extracts_and_derives():
    llm = FakeLLM(
        facts=[{"content": "The user deploys on Fridays.", "op": "add", "importance": 0.6}],
        observations=["Prefers deploying on Fridays", "Writes in Portuguese"],
    )
    m = LogicaMind(namespace="t", store=InMemoryStore(), llm=llm)
    r = m.ingest_conversation([
        {"role": "user", "content": "a gente faz deploy toda sexta e responde em português"},
        {"role": "assistant", "content": "Anotado!"},
    ])
    assert r["logged"] == 2
    assert m.stats()["episodic"] == 2                 # both turns logged
    assert r["facts"] >= 1                             # facts extracted from the exchange
    assert r["observations"] == 2                      # user model built itself
    obs = [o.content for o in m.user._observations()]
    assert any("Friday" in o or "Portuguese" in o for o in obs)


def test_derive_is_noop_offline():
    m = mk()                                            # no LLM
    m.log("eu prefiro respostas curtas", role="user")
    assert m.derive() == 0
    r = m.ingest_conversation([{"role": "user", "content": "oi"}])
    assert r["logged"] == 1 and r["observations"] == 0  # logged, but no derivation offline


def test_derive_dedups_against_existing():
    llm = FakeLLM(observations=["Likes terse replies", "Likes terse replies"])
    m = LogicaMind(namespace="t", store=InMemoryStore(), llm=llm)
    m.log("seja breve", role="user")
    assert m.derive() == 1                              # the two identical obs collapse to one
    assert m.derive() == 0                              # already known → nothing new


class _FakeSupabase(SupabaseStore):
    """SupabaseStore with the network stubbed — exercises the real query-building
    and parsing logic offline (the production backend has no live tests otherwise)."""
    def __init__(self, responder):
        super().__init__(url="http://fake", key="k")
        self.calls = []
        self._responder = responder

    def _request(self, method, path, body=None, extra_headers=None):
        self.calls.append((method, path, body, extra_headers))
        return self._responder(method, path, body)


def test_supabase_namespaces_paginates():
    # three pages (full, full, short tail) — catches an offset that fails to advance
    def resp(method, path, body):
        if "offset=2000" in path:
            return [{"namespace": "ns_tail"}]                       # <1000 → stop
        if "offset=1000" in path:
            return [{"namespace": f"p1_{i}"} for i in range(1000)]
        return [{"namespace": f"p0_{i}"} for i in range(1000)]
    s = _FakeSupabase(resp)
    out = s.namespaces()
    assert "ns_tail" in out and len(out) == 2001               # no page dropped
    assert any("offset=1000" in c[1] for c in s.calls)         # paged
    assert any("offset=2000" in c[1] for c in s.calls)         # offset really advanced


def test_supabase_timerange_two_cheap_queries():
    def resp(method, path, body):
        if "created_at.asc" in path:
            return [{"created_at": "2024-01-01T00:00:00Z"}]
        if "created_at.desc" in path:
            return [{"created_at": "2026-01-01T00:00:00Z"}]
        return []
    s = _FakeSupabase(resp)
    assert s.timerange("ns") == ("2024-01-01T00:00:00Z", "2026-01-01T00:00:00Z")
    assert all("select=created_at" in c[1] and "limit=1" in c[1] for c in s.calls)  # index-only, no rows pulled


def test_supabase_delete_layers_builds_filter():
    from urllib.parse import unquote
    s = _FakeSupabase(lambda *a: [{"id": "1"}, {"id": "2"}])
    assert s.delete_layers("ns", [MemoryLayer.EPISODIC]) == 2
    method, path, _, _ = s.calls[-1]
    path = unquote(path)
    assert method == "DELETE" and "namespace=eq.ns" in path and "layer=in.(episodic)" in path


def test_supabase_metadata_filter_pushdown():
    from urllib.parse import unquote
    cap = {}

    def resp(method, path, body):
        cap["path"] = path
        return []
    s = _FakeSupabase(resp)
    s.search("ns", [0.1] * 4, "q", metadata_filter={"session": "S1"})
    # the session filter must be pushed into PostgREST (before the LIMIT window)
    assert "metadata->>session=eq.S1" in unquote(cap["path"])


def test_mcp_exposes_moats():
    m = mk()
    srv = MCPServer(m)
    listed = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
    names = {t["name"] for t in listed}
    for t in ["lm_observe_user", "lm_observe_peer", "lm_peer_card", "lm_peer_query",
              "lm_ingest_conversation", "lm_reflect", "lm_contradictions", "lm_diff"]:
        assert t in names, f"MCP missing {t}"

    def call(name, args):
        return srv.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                           "params": {"name": name, "arguments": args}})["result"]

    r = call("lm_observe_user", {"text": "likes terse replies"})
    assert r["isError"] is False
    assert m.user._observations()                        # the observation landed
    assert call("lm_observe_peer", {"observer": "a", "observed": "b", "text": "b ships fast"})["isError"] is False
    assert call("lm_contradictions", {})["isError"] is False
    assert call("lm_diff", {"since": "2000-01-01T00:00:00Z"})["isError"] is False
    # missing required arg → clean isError, not a crash
    assert call("lm_observe_peer", {"observer": "a"})["isError"] is True


def test_dream_runs_deriver():
    llm = FakeLLM(observations=["Wants terse replies"])
    m = LogicaMind(namespace="t", store=InMemoryStore(), llm=llm)
    m.log("seja breve comigo", role="user")
    rep = m.dream()
    assert rep.derived >= 1
    assert any("terse" in o.content for o in m.user._observations())


def test_ingest_conversation_strict_no_transcript_blob():
    # LLM available but the fact-extraction reply isn't a JSON list → ZERO facts,
    # never the raw transcript stored as one semantic memory
    llm = FakeLLM(facts="not a list", observations=[])
    m = LogicaMind(namespace="t", store=InMemoryStore(), llm=llm)
    r = m.ingest_conversation([{"role": "user", "content": "qual a capital da franca"},
                               {"role": "assistant", "content": "paris"}])
    assert r["facts"] == 0
    sem = [x.content for x in m.store.all("t", [MemoryLayer.SEMANTIC])]
    assert not any("qual a capital" in s and "paris" in s for s in sem)


def test_derive_orders_same_second_turns_on_sqlite(tmp_path):
    cap = {}

    class EchoLLM(FakeLLM):
        def complete_json(self, prompt, system=None):
            if "observation" in (system or "").lower():
                cap["prompt"] = prompt
                return []
            return super().complete_json(prompt, system)
    m = LogicaMind(namespace="t", store=SQLiteStore(str(tmp_path / "m.db")), llm=EchoLLM())
    for c in ["Q1one", "A1one", "Q2two", "A2two"]:
        m.log(c, role="user")
    m.derive()                                              # transcript=None path
    p = cap["prompt"]
    assert p.index("Q1one") < p.index("A1one") < p.index("Q2two") < p.index("A2two")


def test_derive_idle_does_not_recall_llm():
    calls = {"n": 0}

    class CountLLM(FakeLLM):
        def complete_json(self, prompt, system=None):
            if "observation" in (system or "").lower():
                calls["n"] += 1
            return super().complete_json(prompt, system)
    m = LogicaMind(namespace="t", store=InMemoryStore(), llm=CountLLM(observations=["likes X"]))
    m.log("hello", role="user")
    m.dream(); m.dream(); m.dream()
    assert calls["n"] == 1                                  # idle cycles skip the deriver LLM


def test_derive_dedups_internal_whitespace():
    m = LogicaMind(namespace="t", store=InMemoryStore(), llm=FakeLLM(observations=["Works   in  fintech"]))
    m.observe_user("Works in fintech")
    m.log("x", role="user")
    assert m.derive() == 0                                  # whitespace variant == existing


def test_ingest_flattens_content_blocks():
    m = LogicaMind(namespace="t", store=InMemoryStore(), llm=FakeLLM(observations=[]))
    r = m.ingest_conversation([
        {"role": "user", "content": [{"type": "text", "text": "oi"}, {"type": "image", "x": 1}]},
        {"role": "user", "content": {"weird": 1}},          # non-text shape → skipped
    ])
    assert r["logged"] == 1
    ep = [x.content for x in m.store.all("t", [MemoryLayer.EPISODIC])]
    assert "oi" in ep and not any("weird" in e for e in ep)


def test_mcp_ingest_validates_messages_type():
    srv = MCPServer(mk())

    def call(args):
        return srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": "lm_ingest_conversation", "arguments": args}})["result"]
    assert call({"messages": "hello"})["isError"] is True   # str isn't an array
    assert call({"messages": []})["isError"] is False       # empty list is valid


def test_web_contradictions_aggregates_across_namespaces():
    import threading, time, urllib.request
    from http.server import ThreadingHTTPServer
    from logica_mind.web.server import make_handler
    root = LogicaMind(namespace="root", store=InMemoryStore())   # root left empty
    sub = root.for_namespace("agentx")
    sub.graph.ingest("Bob", "focus", "ProjA")
    sub.graph.ingest("Bob", "focus", "ProjB")                    # contradiction in agentx
    srv = ThreadingHTTPServer(("127.0.0.1", 8774), make_handler(root))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    time.sleep(0.2)
    try:
        d = json.loads(urllib.request.urlopen("http://127.0.0.1:8774/api/contradictions?namespace=__all__").read())
        assert any(c["subject"] == "Bob" for c in d["contradictions"])   # found via aggregation
    finally:
        srv.shutdown()
        srv.server_close()   # release the listening socket now (shutdown() alone races into EADDRINUSE)


def test_web_get_requires_auth_on_non_loopback():
    import io
    from logica_mind.web import server as S
    m = mk(); m.remember("secret", extract=False)
    H = S.make_handler(m, allow_writes=False, token="tok")

    def hit(path, peer, headers=None):
        class R:
            client_address = (peer, 1)
            def __init__(s):
                s.path = path; s.command = "GET"; s.headers = headers or {}
                s.rfile = io.BytesIO(b""); s.wfile = io.BytesIO(); s._st = None
            def send_response(s, c): s._st = c
            def send_header(s, k, v): pass
            def end_headers(s): pass
            def log_message(s, *a): pass
        r = R()
        for n in dir(H):
            if n.startswith(("do_", "_")) and callable(getattr(H, n, None)):
                try: setattr(r, n, getattr(H, n).__get__(r, R))
                except Exception: pass
        r.do_GET(); return r._st
    assert hit("/api/memories", "10.0.0.9") == 401                       # remote, no token
    assert hit("/api/memories", "127.0.0.1") == 200                      # loopback trusted
    assert hit("/api/namespaces", "10.0.0.9") == 200                     # public (counts only)
    assert hit("/api/memories", "10.0.0.9", {"Authorization": "Bearer tok"}) == 200


def test_graph_alias_resolution_invalidates():
    m = mk()
    m.graph.ingest("Bob", "lives_in", "Paris")
    m.add_alias("Robert", "Bob")
    m.graph.ingest("Robert", "lives_in", "Berlin")          # same entity → closes Paris
    current = [e for e in m.graph.edges() if e.subject == "Bob" and e.predicate == "lives_in"]
    assert len(current) == 1 and current[0].object == "Berlin"
    assert any(x["subject"] == "Bob" and len(x["history"]) == 2 for x in m.contradictions())


def test_graph_auto_merges_spacing_and_case():
    m = mk()
    m.graph.ingest("OpenAI", "released", "GPT")
    m.graph.ingest("Open AI", "valued_at", "Big")           # same node by normalization
    e = m.entity("open-ai")
    assert e["name"] == "OpenAI" and e["degree"] >= 2        # first-seen spelling is canonical


def test_graph_nodes_and_entity_view():
    m = mk()
    m.graph.ingest("Maya", "founded", "Acme")
    m.graph.ingest("Engineer", "reports_to", "Maya")
    maya = next(n for n in m.graph_nodes() if n["name"] == "Maya")
    assert maya["degree"] == 2
    e = m.entity("Maya")
    assert set(e["neighbors"]) == {"Acme", "Engineer"}


def test_entity_lists_aliases():
    m = mk()
    m.add_alias("Robert", "Bob")
    m.graph.ingest("Bob", "likes", "coffee")
    e = m.entity("Robert")                                   # resolves to Bob
    assert e["name"] == "Bob" and "Robert" in e["aliases"]


def test_alias_rows_are_not_edges():
    m = mk()
    m.add_alias("Robert", "Bob")
    m.graph.ingest("Bob", "likes", "coffee")
    assert len(m.graph.edges()) == 1                         # the alias row isn't an edge


def test_bm25_rewards_term_frequency_and_rarity():
    from logica_mind.stores.base import bm25_scores
    docs = ["alpha alpha alpha beta", "alpha gamma delta epsilon zeta eta theta"]
    s = bm25_scores("alpha", docs)
    assert s[0] > s[1]                                       # higher tf + shorter doc wins


def test_recall_uses_bm25_for_text_only_memories():
    m = LogicaMind(namespace="t", store=InMemoryStore())
    m.store.add([
        Memory(content="widgets widgets widgets matter", namespace="t", layer=MemoryLayer.SEMANTIC),
        Memory(content="a long note mentioning widgets once plus lots of other filler words today",
               namespace="t", layer=MemoryLayer.SEMANTIC),
    ])
    hits = m.recall("widgets")                               # no embeddings → BM25 path
    assert hits and hits[0].memory.content.startswith("widgets widgets widgets")


def test_ingest_document_uses_contextual_embedding():
    class CtxEmb(HashingEmbedder):
        def __init__(self):
            super().__init__()
            self.called = 0

        def embed_contextualized(self, chunks, input_type="document"):
            self.called += 1                                 # one call for the whole doc
            return [self.embed_one(c) for c in chunks]
    emb = CtxEmb()
    m = LogicaMind(namespace="t", store=InMemoryStore(), embedder=emb)
    created = m.ingest_document("A " * 1500, chunk_size=1000, overlap=100)
    assert emb.called == 1
    assert created and all("contextual" in (c.tags or []) for c in created)
    assert all(c.embedding for c in created)


def test_ingest_conversation_tags_source():
    m = mk()
    m.ingest_conversation([{"role": "user", "content": "oi"}, {"role": "assistant", "content": "olá"}],
                          source="cursor", derive=False)
    ep = m.store.all("t", [MemoryLayer.EPISODIC])
    assert ep and all((e.metadata or {}).get("source") == "cursor" for e in ep)


def test_mcp_captures_client_source():
    m = mk()
    srv = MCPServer(m)
    srv.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "clientInfo": {"name": "claude-code", "version": "1"}}})
    assert srv.source == "claude-code"                       # learned the connecting client
    srv.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "lm_remember", "arguments": {"text": "a durable fact"}}})
    sem = m.store.all("t", [MemoryLayer.SEMANTIC])
    assert any((s.metadata or {}).get("source") == "claude-code" for s in sem)


def test_mcp_source_falls_back_to_mcp_when_client_unnamed():
    srv = MCPServer(mk())
    srv.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})  # no clientInfo
    assert srv.source == "mcp"                               # still attributable as "via MCP"


def test_provenance_traces_sources():
    m = mk()
    src = m.log("user said: deploy on fridays", role="user")
    fact = Memory(content="ships on fridays", namespace="t", layer=MemoryLayer.SEMANTIC, source_ids=[src.id])
    m.store.add([fact])
    p = m.provenance(fact.id)
    assert p["from"] and "deploy on fridays" in p["from"][0]["content"]


def test_state_at_replay():
    m = mk()
    m.store.add([
        Memory(content="old", namespace="t", layer=MemoryLayer.SEMANTIC, created_at="2020-01-01T00:00:00Z"),
        Memory(content="new", namespace="t", layer=MemoryLayer.SEMANTIC, created_at="2026-01-01T00:00:00Z"),
    ])
    assert [x["content"] for x in m.state_at("2021-01-01T00:00:00Z")] == ["old"]


def test_knowledge_gap():
    a = LogicaMind(namespace="a", store=InMemoryStore())
    b = a.for_namespace("b")
    a.remember("a shared fact", extract=False)
    b.remember("a shared fact", extract=False)
    b.remember("only b knows this one", extract=False)
    gap = a.knowledge_gap("b")
    assert any("only b knows" in g["content"] for g in gap)
    assert not any("shared fact" in g["content"] for g in gap)


def test_stale_beliefs_flags_old_unrecalled():
    m = mk()
    m.store.add([Memory(content="ancient unrecalled belief", namespace="t", layer=MemoryLayer.SEMANTIC,
                        importance=0.3, created_at="2020-01-01T00:00:00Z")])
    stale = m.stale_beliefs(min_age_days=30)
    assert stale and stale[0]["content"].startswith("ancient")


def test_signed_bundle_roundtrip_and_tamper():
    import pytest
    src = LogicaMind(namespace="src", store=InMemoryStore())
    src.remember("a portable fact", extract=False)
    bundle = src.export_bundle(secret="key123")
    assert bundle["signature"]
    dst = LogicaMind(namespace="dst", store=InMemoryStore())
    assert dst.import_bundle(bundle, secret="key123") == 1
    assert any("portable fact" in x.content for x in dst.store.all("dst"))
    bundle["payload"]["memories"][0]["content"] = "tampered"      # break the signature
    with pytest.raises(ValueError):
        dst.import_bundle(bundle, secret="key123")


def test_infer_links_offline_is_noop():
    m = mk()
    m.graph.ingest("A", "rel", "B")
    m.graph.ingest("B", "rel", "C")
    assert m.infer_links() == 0                                   # no LLM → no synthesis


def test_infer_links_with_llm():
    class InferLLM(FakeLLM):
        def complete_json(self, prompt, system=None):
            if "inductive" in (system or "").lower():
                return ["A is connected to C"]
            return super().complete_json(prompt, system)
    m = LogicaMind(namespace="t", store=InMemoryStore(), llm=InferLLM())
    m.graph.ingest("A", "rel", "B")
    m.graph.ingest("B", "rel", "C")
    assert m.infer_links() >= 1
    assert any("connected to C" in x.content for x in m.store.all("t", [MemoryLayer.SEMANTIC]))


def test_redact_pii():
    out = LogicaMind.redact_pii("mail me at a@b.com or call +55 11 99999-8888")
    assert "[email]" in out and "[phone]" in out and "a@b.com" not in out


if __name__ == "__main__":
    # run without requiring pytest
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(fns)} passed")
    raise SystemExit(0 if passed == len(fns) else 1)
