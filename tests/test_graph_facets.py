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
