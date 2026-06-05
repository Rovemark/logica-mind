# API Reference

A concise reference for the `LogicaMind` class — every public method, its real signature, and a one-line description.

`LogicaMind` is the single entry point. It ties together a store, an embedder, an optional LLM, a temporal knowledge graph and a dialectic user model. The defaults are fully offline and zero-key (`SQLiteStore` + `HashingEmbedder` + `NullLLM`), so everything on this page runs without any API key — methods that genuinely need an LLM (extraction, graph building, derivation, inference) degrade to a safe no-op offline and say so below.

```python
from logica_mind import LogicaMind, MemoryLayer

mind = LogicaMind(namespace="agent-a")
mind.remember("Acme Inc prefers concise answers.")
for hit in mind.recall("how should I reply to Acme?"):
    print(round(hit.score, 3), hit.memory.content)
```

---

## Constructor

```python
LogicaMind(
    namespace: str = "default",
    store: Optional[Store] = None,                  # default: SQLiteStore()
    embedder: Optional[Embedder] = None,            # default: HashingEmbedder()
    extractor: Optional[Extractor] = None,          # default: LLMExtractor if an LLM is available, else NoopExtractor
    llm: Optional[LLM] = None,                       # default: NullLLM()
    dedup_threshold: float = 0.92,
    weights: tuple = (0.60, 0.25, 0.15),             # (similarity, importance, recency)
    half_life_days: float = 7.0,
    track_access: bool = True,
    reranker: Optional[Reranker] = None,
    rerank_pool: int = 30,
    entity_boost: float = 0.0,
)
```

Construct a memory instance scoped to `namespace`. With no arguments it runs fully offline. See [./stores.md](./stores.md), [./embeddings-and-reranking.md](./embeddings-and-reranking.md) and [./concepts.md](./concepts.md) for the pluggable pieces.

The four memory layers are values of `MemoryLayer`: `EPISODIC`, `SEMANTIC`, `GRAPH`, `USER`.

---

## Write

| Method | Description |
| --- | --- |
| `remember(text, layer=MemoryLayer.SEMANTIC, importance=0.5, tags=None, metadata=None, session=None, extract=True, build_graph=False, category=None) -> List[Memory]` | Store a durable fact/note — runs extraction (add/update/delete/noop) + dedup, optionally builds graph edges, returns the memories created. |
| `log(text, role=None, importance=0.3, tags=None, metadata=None, session=None) -> Optional[Memory]` | Store a raw episodic turn/event with no extraction and no dedup. |
| `record_session(title, session_id=None, participants=None, status="completed", metrics=None, links=None, tags=None, summary=None, store_contributions=True, importance=0.7) -> Memory` | Record a rich, structured session/run as a first-class memory plus one linked memory per participant contribution. |
| `session_record(session_id) -> Optional[Dict[str, Any]]` | Return the structured session-record header (with its contributions) for a session id, or `None`. |
| `ingest_conversation(messages, session=None, extract=True, derive=True, source=None) -> Dict[str, int]` | Log a list of `{role/speaker, content}` turns, extract durable facts over the whole exchange, derive user observations; returns `{logged, facts, observations}`. |
| `ingest_document(text, chunk_size=1000, overlap=100, metadata=None, session=None, tags=None, build_graph=False, extract=False) -> List[Memory]` | Chunk a document and store each chunk as a memory (optional per-chunk fact/graph extraction). |
| `ingest_json(obj, session=None, tags=None, max_items=200) -> List[Memory]` | Flatten a JSON object/array into `path = value` facts and store them, deduped on exact normalized string. |
| `observe_user(text) -> Optional[Memory]` | Add one observation to the dialectic user model. |

```python
mind.remember("Maya's renewal date moved to March.", importance=0.8, tags=["account"])
mind.log("user: can you summarize the ticket?", role="user", session="s-42")
mind.record_session(
    title="Resolve ticket #812",
    participants=[
        {"name": "support", "role": "agent", "contribution": "Refunded the order."},
        {"name": "research", "role": "analyst", "metrics": {"sources": 4}},
    ],
    metrics={"resolution_minutes": 7},
)
```

---

## Read

| Method | Description |
| --- | --- |
| `recall(query, layers=None, limit=8, session=None, metadata_filter=None, min_importance=0.0, category=None) -> List[SearchResult]` | Retrieve the most relevant memories — embed query, hybrid store search, blend similarity·importance·recency, dedup, optional reranker. |
| `recall_across(query, namespaces=None, layers=None, limit=8) -> List[SearchResult]` | Recall across many namespaces (or all) and merge the rankings. |
| `get(memory_id) -> Optional[Memory]` | Fetch a single memory by id from this namespace. |
| `context(query, token_budget=1500, layers=None, session=None, include_user=True) -> str` | Assemble a ready-to-inject context block for `query`, fitted to a token budget (user model first, then top memories). |
| `session_brief(limit=10, token_budget=1200) -> str` | A session-start digest: what we know about the user plus the most important facts and recent activity, fitted to a budget. |
| `user_profile() -> str` | Return the synthesized profile string from the dialectic user model. |
| `ask_about_user(question, k=8) -> str` | Dialectic query — answer a question about the user, reasoning over the profile plus relevant observations. |
| `stats() -> Dict[str, int]` | Per-layer memory counts for this namespace, plus `total`. |

```python
hits = mind.recall("renewal date for Maya", layers=[MemoryLayer.SEMANTIC], limit=5)
block = mind.context("brief me on Acme Inc", token_budget=800)
```

Each `SearchResult` exposes `.score`, `.components` (the `similarity` / `importance` / `recency` breakdown) and `.memory`.

---

## Knowledge graph

| Method | Description |
| --- | --- |
| `learn_graph(text) -> list` | Extract entity/relationship triples from `text` into the temporal graph (needs an LLM; no-op offline); returns the new edges. |
| `add_alias(variant, canonical) -> None` | Declare two entity spellings are the same node (e.g. `"Robert" → "Bob"`) so the graph doesn't fragment. |
| `entity(name, include_history=False) -> Dict[str, Any]` | First-class entity view: canonical name, type, aliases, edges and neighbours. |
| `graph_nodes(include_history=False) -> List[Dict[str, Any]]` | Every entity with its degree (edge count), busiest first. |
| `graph_viz(namespace=None, include_history=True, at=None) -> Dict[str, Any]` | Graph payload for the UI — one namespace, or the general cross-namespace graph; `at` gives a point-in-time view. |
| `graph_communities(summarize=False, include_history=False)` | Clusters of related entities; with `summarize=True` each community gets an LLM-written summary. |

See [./knowledge-graph.md](./knowledge-graph.md) for the temporal model.

---

## Namespacing

| Method | Description |
| --- | --- |
| `for_namespace(namespace) -> LogicaMind` | A sibling view on the same store/providers, scoped to another namespace (e.g. one per agent). |
| `list_namespaces() -> List[Dict[str, Any]]` | Every namespace in the store with per-layer counts and totals. |

```python
research = mind.for_namespace("research")
research.remember("Competitor X shipped a new pricing tier.")
```

---

## User model & peers

| Method | Description |
| --- | --- |
| `derive(transcript=None, session=None, window=20) -> int` | Infer durable observations about the user from a conversation and feed the dialectic model (no-op offline); returns the count of new observations. |
| `observe_peer(observer, observed, text, importance=0.6) -> Optional[Memory]` | Record a directional `observer → observed` observation, so each peer builds its own theory of another. |
| `peer_card(observer, observed) -> str` | A directional card: what `observer` knows about `observed`. |
| `peer_query(observer, observed, question) -> str` | Ask what `observer` would say about `observed` (theory-of-mind query). |

See [./user-model-and-peers.md](./user-model-and-peers.md).

---

## Reflection & dreaming

| Method | Description |
| --- | --- |
| `reflect(window=30, store_result=True) -> str` | Synthesize insights from recent memories (what changed / what's notable); offline it returns the recent digest. |
| `dream(**kwargs)` | Run a sleep-time consolidation cycle (delegates to `logica_mind.dreaming.Dreamer`). |
| `infer_links(max_new=5) -> int` | Inductive dreaming — connect existing graph facts into new inferred facts via the LLM (no-op offline); returns the count of new inferences. |

See [./dreaming.md](./dreaming.md) for the full cycle and `dream()` options.

---

## Forgetting

| Method | Description |
| --- | --- |
| `forget(memory_id=None, query=None, threshold=0.9, layers=None) -> int` | Delete a memory by id, or every memory matching `query` above `threshold`; returns the number removed. |
| `forget_about(entity) -> int` | GDPR-style erase — delete every memory mentioning `entity` (any layer) and every graph edge touching it. |
| `forget_curve(days_halflife=30.0, apply=False, limit=20) -> List[Dict[str, Any]]` | Ebbinghaus retention — list beliefs sorted by how much they'll decay in the next 7 days; with `apply=True`, lower their importance. |
| `purge() -> int` | Delete every memory in this namespace (a hard reset). |

```python
removed = mind.forget_about("Maya")            # erase everything about Maya
at_risk = mind.forget_curve(apply=False)       # preview what is decaying
```

---

## Epistemics & provenance

These are the temporal/"moat" methods — they surface *how* and *when* beliefs were formed, changed or contradicted.

| Method | Description |
| --- | --- |
| `provenance(memory_id) -> Dict[str, Any]` | "Why do I believe this?" — trace a memory back to its source turns/documents and what it superseded. |
| `state_at(at, layers=None) -> List[Dict[str, Any]]` | Memory replay — everything the agent knew at a past ISO instant (graph edges respect their valid window). |
| `diff(since, until=None, layers=None) -> List[Dict[str, Any]]` | What was learned in a time window `[since, until]` — a memory changelog. |
| `contradictions() -> List[Dict[str, Any]]` | Graph slots `(subject, predicate)` that had multiple objects over time, with the full temporal history. |
| `contested_beliefs(confidence_threshold=0.65) -> List[Dict[str, Any]]` | Pairs of contradicting beliefs that both had high confidence — conflicts neither side can dismiss. |
| `surprise_events(since=None, limit=20) -> List[Dict[str, Any]]` | Beliefs that surprised the system when stored (`surprise_score = old_confidence × cosine_distance`). |
| `stale_beliefs(min_age_days=30.0, limit=20) -> List[Dict[str, Any]]` | Old, never-recalled, decayed facts the agent should re-verify. |
| `knowledge_gap(other, limit=50) -> List[Dict[str, Any]]` | What another mind/namespace knows that this one doesn't, content-keyed. |
| `redact_pii(text) -> str` | Mask emails / phone numbers / long digit runs in a string (static method). |

```python
gap = mind.knowledge_gap("research")           # what research knows that agent-a doesn't
shaky = mind.stale_beliefs(min_age_days=60)    # beliefs to re-verify
print(LogicaMind.redact_pii("call maya@acme.com or +1 415 555 0100"))
```

---

## Transfer, export & import

| Method | Description |
| --- | --- |
| `transfer_to(dst, query, limit=10) -> int` | Cross-agent knowledge transfer — copy facts matching `query` into another mind/namespace, tagged with their origin. |
| `export(layers=None) -> List[Dict[str, Any]]` | Dump this namespace's memories as plain dicts (for backup/transfer). |
| `import_memories(records) -> int` | Load memories from dicts (as produced by `export()`) into the store; returns the count loaded. |
| `migrate_to(dst_store, layers=None) -> int` | Copy this namespace's memories into another store (e.g. SQLite → Postgres). |
| `export_bundle(secret=None, layers=None) -> Dict[str, Any]` | Build a portable, optionally HMAC-signed memory bundle to move memory between apps/vendors. |
| `import_bundle(bundle, secret=None, verify=True) -> int` | Import a (signed) memory bundle into this namespace, re-embedding missing vectors; returns the count. |

```python
bundle = mind.export_bundle(secret="shared-secret")
mind.for_namespace("agent-b").import_bundle(bundle, secret="shared-secret")
```

---

## Async wrappers

Thin wrappers that run the blocking verbs in a thread, so `LogicaMind` can be used from async apps without holding the event loop.

| Method | Description |
| --- | --- |
| `aremember(*args, **kwargs) -> List[Memory]` | Async wrapper for `remember`. |
| `alog(*args, **kwargs) -> Optional[Memory]` | Async wrapper for `log`. |
| `arecall(*args, **kwargs) -> List[SearchResult]` | Async wrapper for `recall`. |
| `aforget(*args, **kwargs) -> int` | Async wrapper for `forget`. |
| `acontext(*args, **kwargs) -> str` | Async wrapper for `context`. |
| `aask_about_user(*args, **kwargs) -> str` | Async wrapper for `ask_about_user`. |

```python
hits = await mind.arecall("what does the user prefer?")
```

---

## Lifecycle & dashboard

| Method | Description |
| --- | --- |
| `serve(host="127.0.0.1", port=8420, open_browser=True)` | Launch the self-hosted dashboard (blocking). |
| `close() -> None` | Close the underlying store. |

```python
mind.serve()                                   # open the live dashboard
```

---

## See also

- [./quickstart.md](./quickstart.md) — install and run your first memory in minutes.
- [./concepts.md](./concepts.md) — the four memory layers and how they fit together.
- [./stores.md](./stores.md) — SQLite, Postgres, Redis, Supabase and other backends.
- [./embeddings-and-reranking.md](./embeddings-and-reranking.md) — embedders, rerankers and the scoring blend.
- [./knowledge-graph.md](./knowledge-graph.md) — the temporal knowledge graph and entity views.
- [./user-model-and-peers.md](./user-model-and-peers.md) — the dialectic user model and peer observations.
- [./dreaming.md](./dreaming.md) — sleep-time consolidation, `dream()` and inferred links.
- [./installation.md](./installation.md) — optional extras and provider setup.
