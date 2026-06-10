"""Graph facet engine + perf-path regression tests — run with: pytest

All offline: SQLiteStore(:memory:) + HashingEmbedder, no API keys. Locks in the
behaviours the dashboard graph depends on:
  • all() is UNCAPPED enumeration (the max_candidates window is for search only —
    a capped all() silently dropped a third of the graph's edges at 7k+ rows)
  • tagged() whitelists metadata keys and feeds the facet voting
  • _entity_facets votes metadata.channel/source/… onto mentioned entities
  • graph_viz nodes carry type/dimension/channel and the change-token cache hits
  • mentions() is a SUPERSET pre-filter of the precise token match
"""
from logica_mind import LogicaMind, MemoryLayer
from logica_mind.stores import SQLiteStore
from logica_mind.stores.base import _tokset
from logica_mind.embeddings import HashingEmbedder


def _mind():
    return LogicaMind(store=SQLiteStore(":memory:"), embedder=HashingEmbedder(),
                      namespace="t")


def _edge(mind, s, p, o, st="Person", ot="Product"):
    mind.graph.ingest(s, p, o, subject_type=st, object_type=ot, single_valued=False)


def test_all_is_uncapped_enumeration():
    m = _mind()
    m.store.max_candidates = 10                     # tiny search window on purpose
    for i in range(25):
        _edge(m, f"A{i}", "uses", f"B{i}")
    rows = m.store.all("t", layers=[MemoryLayer.GRAPH])
    assert len(rows) >= 25, "all() must enumerate EVERYTHING, not the search window"
    assert len(m.graph.edges(include_history=True)) == 25


def test_tagged_whitelist_and_values():
    m = _mind()
    m.log("deploy aprovado pelo Astro", metadata={"channel": "whatsapp"})
    m.log("outra conversa", metadata={"channel": "telegram"})
    got = dict()
    for content, val in m.store.tagged("t", "channel"):
        got[val] = content
    assert set(got) == {"whatsapp", "telegram"}
    assert m.store.tagged("t", "definitely_not_whitelisted") == []


def test_entity_facets_vote_channel_onto_mentions():
    m = _mind()
    _edge(m, "Astro", "leads", "LogicaOS", st="Person", ot="Product")
    m.log("Astro confirmou o deploy do LogicaOS hoje", metadata={"channel": "whatsapp"})
    m.log("Astro de novo no mesmo canal", metadata={"channel": "whatsapp"})
    m.log("Astro apareceu uma vez aqui", metadata={"channel": "voice"})
    facets = m._entity_facets(["t"], ["Astro", "LogicaOS"], "channel")
    assert facets.get("Astro") == "whatsapp"        # 2 votos x 1
    assert facets.get("LogicaOS") == "whatsapp"


def test_graph_viz_nodes_carry_type_dimension_channel():
    m = _mind()
    _edge(m, "Astro", "leads", "LogicaOS", st="Person", ot="Product")
    m.log("Astro fechou contrato do LogicaOS", metadata={"channel": "telegram"})
    m.remember("Astro is focused on the LogicaOS launch", extract=False,
               metadata={"dimension": "project_status"})
    viz = m.graph_viz(namespace="t")
    nodes = {n["id"]: n for n in viz["nodes"]}
    assert nodes["Astro"]["type"] == "Person"
    assert nodes["LogicaOS"]["type"] == "Product"
    assert nodes["Astro"].get("channel") == "telegram"
    assert nodes["Astro"].get("dimension") == "project_status"


def test_graph_viz_cache_hits_and_invalidates():
    m = _mind()
    _edge(m, "A", "uses", "B")
    v1 = m.graph_viz(namespace="t")
    v2 = m.graph_viz(namespace="t")
    assert v2 is v1, "unchanged store must serve the cached payload"
    _edge(m, "C", "uses", "D")                      # write → token flips
    v3 = m.graph_viz(namespace="t")
    assert v3 is not v1
    assert len(v3["nodes"]) > len(v1["nodes"])


def test_graph_aware_recall_boosts_neighbour_memories():
    m = _mind()
    _edge(m, "Voyspark", "focuses_on", "SEO")
    m.remember("SEO strategy needs better backlinks", extract=False)
    m.remember("nota completamente alheia sobre macarrão", extract=False)
    hits = m.recall("me fala do Voyspark", limit=5)
    by = {h.memory.content: h for h in hits}
    seo = next(v for k, v in by.items() if "SEO" in k)
    # a memória do VIZINHO (SEO) recebe o graph_boost — recall é graph-aware
    assert "graph_boost" in seo.components or "entity_boost" in seo.components
    pasta = next(v for k, v in by.items() if "macarrão" in k)
    assert "graph_boost" not in pasta.components and "entity_boost" not in pasta.components


def test_context_includes_knowledge_graph_facts():
    m = _mind()
    _edge(m, "Voyspark", "focuses_on", "SEO")
    m.remember("SEO strategy doc", extract=False)
    block = m.context("qual o status do Voyspark", token_budget=800)
    assert "## Knowledge graph" in block
    assert "Voyspark focuses on SEO" in block


def test_offline_heuristic_extractor_tags_dimensions():
    from logica_mind.extract.heuristic import HeuristicExtractor, guess_dimension
    m = _mind()                                     # sem LLM → heurístico é o default
    assert isinstance(m.extractor, HeuristicExtractor)
    created = m.remember("I love coffee and jazz music, my favorite brand is Moka")
    assert created and created[0].metadata.get("dimension") == "preference"
    # pt-BR também
    assert guess_dimension("o prazo do cronograma do projeto estourou") in ("project_timeline", "project_status")
    assert guess_dimension("minha família e meu filho vêm jantar") == "relationship"
    # sem evidência → sem chute (conservador, igual ao comportamento antigo)
    assert guess_dimension("xyzzy plugh") is None


def test_alias_merges_existing_nodes_at_read_time():
    m = _mind()
    _edge(m, "Logica OS", "uses", "SQLite")
    _edge(m, "LogicaOS", "ships", "Dashboard")      # variação de grafia → MESMO nó
    subs = {e.subject for e in m.graph.edges(include_history=True)}
    logica = [s for s in subs if "logica" in s.lower().replace(" ", "")]
    assert len(set(logica)) == 1, f"variações deviam colapsar num nó só: {logica}"
    # rename/merge explícito: tudo resolve pro novo nome canônico
    m.graph.add_alias(logica[0], "Logica Mind OS")
    subs2 = {e.subject for e in m.graph.edges(include_history=True)}
    assert "Logica Mind OS" in subs2


def test_reembed_migrates_embedding_dimension():
    from logica_mind.embeddings.base import Embedder

    class Fake8(Embedder):
        name = "fake8"
        dim = 8
        def embed(self, texts):
            return [[0.5] * 8 for _ in texts]

    m = _mind()
    m.remember("primeira memória de teste", extract=False)
    m.remember("segunda memória de teste", extract=False)
    m.embedder = Fake8()                            # troca de embedder (dimensão nova)
    done = m.reembed(namespaces=["t"])
    assert done["t"] >= 2
    dims = {len(r.embedding) for r in m.store.all("t") if r.embedding is not None}
    assert dims == {8}, f"todas as memórias deviam estar em 8d: {dims}"


def test_mentions_is_superset_of_precise_match():
    m = _mind()
    _edge(m, "Voyspark", "ships", "Artigos")
    m.log("o Voyspark publicou dez artigos hoje")
    m.log("conversa que não menciona nada disso")
    cands = m.store.mentions("t", "Voyspark")
    et = _tokset("Voyspark")
    precise = [x for x in m.store.all("t", with_embeddings=False)
               if et and et <= _tokset(x.content)]
    cand_ids = {c.id for c in cands}
    assert all(p.id in cand_ids for p in precise), "pre-filter must never drop a true mention"
