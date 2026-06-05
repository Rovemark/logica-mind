# Graph intelligence

Most knowledge graphs draw a picture. Logica Mind's graph is an **instrument** — it reasons about its own structure. Because there's a real memory engine underneath (typed predicates, confidence, provenance, temporal validity, categorization, decay), the graph can do things a hand-linked note graph never can: explain how two things relate, find its own load-bearing connectors, and predict the links you're missing.

Everything here is pure-Python over the temporal graph (no LLM in the request path), exposed three ways: a `LogicaMind` method, a REST endpoint, and an MCP tool.

- [Connection layers](#connection-layers)
- [Node importance (centrality)](#node-importance-centrality)
- [How is A related to B?](#how-is-a-related-to-b)
- [Bridges](#bridges)
- [Suggested links](#suggested-links)
- [Unlinked mentions](#unlinked-mentions)
- [The dashboard](#in-the-dashboard)

---

## Connection layers

`graph_viz(layers=[…])` returns more than explicit relations. Every link carries a `kind`:

| Layer | What it is | Cost |
|---|---|---|
| **relation** | An explicit typed edge from the temporal graph. Always on. Carries `directed`, `weight` (= confidence), and a `pclass` — a predicate class (social / has / causal / locative / temporal / is_a) the canvas hues it by. | free |
| **co_mention** | An *emergent* link between two entities a single memory names together, with no explicit edge. One regex scan over the facts, capped per memory. The computed version of "unlinked mentions". | O(facts) |
| **semantic** | *Opt-in.* Entity pairs whose memory-neighbourhoods are close in vector space but unlinked. Built from **already-stored** embeddings only (never embeds in the request path), capped to the busiest entities. Meaningful with a real embedder; quietly thin with the offline hashing one. | capped |

```python
viz = mind.graph_viz(namespace="org:acme", layers=["relation", "co_mention", "semantic"])
for link in viz["links"]:
    link["kind"]      # 'relation' | 'co_mention' | 'semantic'
    link["weight"]    # confidence (relations) or co-occurrence count
    link.get("pclass")  # 'social' | 'has' | 'causal' | … (relations only)
```

## Node importance (centrality)

Every node carries a normalized **PageRank `centrality`** (and a raw `degree`). The dashboard sizes nodes by it, so hubs literally stand out, and offers a *Centrality* colour mode (cool → hot). Nodes that are structural **bridges** also get a `bridge: true` flag.

```python
viz["nodes"][0]   # {id, namespaces, dimension?, degree, centrality, bridge?}
```

## How is A related to B?

```python
mind.how_related("the billing service", "Priya Nair")
# {
#   "found": True,
#   "path": ["the billing service", "Acme Inc", "Priya Nair"],
#   "hops": [
#     {"subject": "the billing service", "predicate": "part_of", "object": "Acme Inc", "confidence": 1.0},
#     {"subject": "Priya Nair", "predicate": "works_at", "object": "Acme Inc", "confidence": 1.0},
#   ],
# }
```

A confidence-weighted shortest path (Dijkstra, cost = 1/confidence) returned as an ordered chain of **typed** hops. In the dashboard, **Path** mode traces it and spotlights it on the canvas — path nodes gold-ringed, path edges gold, everything else dimmed.

- REST: `GET /api/path?from=…&to=…&namespace=…`
- MCP: `lm_how_related`

## Bridges

```python
mind.bridges()   # [{"entity": "Jordan Lee", "degree": 3}, …]
```

The **articulation points** of the graph — entities whose removal would fragment it. These broker between otherwise-separate clusters, and are often *low-degree* nodes that pure centrality ranking misses. Flagged on nodes (`bridge: true`) and given a dashed ring on the canvas.

- REST: `GET /api/bridges?namespace=…`
- MCP: `lm_bridges`

## Suggested links

```python
mind.suggested_links()
# [{"a": "Maya Chen", "b": "the billing service", "common_neighbors": 3, "score": 1.2, "via": [...]}, …]
```

**Link prediction** by Adamic-Adar: entity pairs with no direct relation but a strong shared neighbourhood — *"these two probably relate, you just never said so."* A **Suggested** layer overlays them as dashed candidate edges. This is the sharpest "nobody has this" moment: note tools make you author every link; here the graph proposes the ones you're missing.

- REST: `GET /api/suggested?namespace=…`
- MCP: `lm_suggested_links`

## Unlinked mentions

```python
mind.entity_unlinked("Maya Chen")
# [{"entity": "Jordan Lee", "count": 2}, …]
```

Other graph entities that get **talked about together** with this one in some memory, yet have **no edge** to it. Obsidian's unlinked-mentions feature, except the graph already knows the entities. Surfaced as a dashed "Mentioned together, not linked" section in a node's detail panel.

## In the dashboard

The Graph view turns all of the above into a single, professional instrument:

- **Edge grammar** — relations hued by predicate class with arrows + confidence-weighted width; co-mentions dashed, suggested dotted-gold, superseded greyed.
- **Top filter bar** — colour by Namespace / Community / Life-area / Centrality; toggle the Co-mention / Semantic / Suggested layers; search-to-focus; a min-confidence declutter slider; per-predicate-class filters; and a highlight-by-query colour group.
- **Path mode** — "how is A related to B?", traced and spotlighted.
- **Local graph** — focus an entity to collapse the view to its neighbourhood, with a 1–3 hop depth slider.
- **Hover preview** — a node's top facts without a click.
- **Time scrubber** — replay the graph at any past date.

Every control has a hover tooltip, in every supported language.

## See also

- [Knowledge graph](./knowledge-graph.md) — the temporal graph these features run on.
- [Connections](./connections.md) — derived backlinks for a single memory.
- [Fact categorization](./categorization.md) — the life-area dimensions that colour the graph.
- [MCP server](./mcp.md) — `lm_how_related`, `lm_bridges`, `lm_suggested_links`.
