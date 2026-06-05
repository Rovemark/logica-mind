# Core concepts

Logica Mind gives an agent four kinds of memory and a single recall pipeline that blends meaning, importance and recency — here's the mental model behind it.

Most memory libraries are a vector store with a friendly API: you write text, you search it back. Logica Mind keeps that simplicity for the common case, but underneath it organizes what an agent knows into **four layers**, and retrieves across them with a **hybrid score** that goes beyond raw similarity. This page builds the mental model; the API reference pages go deeper on each piece.

Everything here runs **offline with zero keys** by default: a local SQLite store and a deterministic hashing embedder. You only reach for Voyage, OpenAI, Postgres or Redis when you want them.

```python
from logica_mind import LogicaMind

mind = LogicaMind(namespace="my-app")   # SQLite + hashing embedder, no API key
```

## The unit: a `Memory`

Everything Logica Mind stores is a `Memory` — a plain dataclass (no third-party types). The fields you'll touch most often:

| Field | Type | Meaning |
| --- | --- | --- |
| `content` | `str` | The text itself. |
| `namespace` | `str` | Which agent/app owns it (default `"default"`). |
| `layer` | `MemoryLayer` | One of `EPISODIC`, `SEMANTIC`, `GRAPH`, `USER`. |
| `importance` | `float` | How much this matters, in `[0, 1]` (default `0.5`). |
| `embedding` | `list[float] \| None` | Optional vector. A memory can be **text-only** and still be found lexically, then back-filled with a vector later. |
| `metadata` | `dict` | Open bag — `session`, `category`, `role`, `source`, anything you filter on. |
| `tags` | `list[str]` | Free-form labels. |
| `created_at` | `str` | UTC ISO timestamp, set on creation. |
| `access_count` | `int` | Incremented when a recall surfaces it (usage signal). |
| `last_recalled_at` | `str \| None` | When it was last recalled (`None` = never). |
| `surprise_score` | `float` | `> 0` when this belief contradicted a prior, confident one. |

A recall returns `SearchResult` objects, each wrapping the `Memory` plus the final `score` and a `components` breakdown (`similarity`, `importance`, `recency`, …) so you can see *why* something surfaced:

```python
for hit in mind.recall("what does the user like?"):
    print(f"{hit.score:.2f}  {hit.memory.content}")
    print(hit.components)   # {'similarity': 0.71, 'importance': 0.5, 'recency': 0.98}
```

See [Types](./concepts.md) for the full `Memory` / `MemoryLayer` / `SearchResult` reference.

## The four memory layers

`MemoryLayer` is an enum with four values. Think of them as four answers to four different questions:

| Layer | Value | Answers | How it's written |
| --- | --- | --- | --- |
| **Episodic** | `episodic` | *What happened?* | `mind.log(...)`, `mind.ingest_conversation(...)` |
| **Semantic** | `semantic` | *What's true?* | `mind.remember(...)` |
| **Graph** | `graph` | *How do things relate, and when did that change?* | `mind.learn_graph(...)`, `remember(..., build_graph=True)` |
| **User** | `user` | *Who is this person, really?* | `mind.observe_user(...)`, `mind.derive(...)` |

All four live in the **same store** as `Memory` rows — the layer is just a column. That means recall, filtering, export and the dashboard work uniformly across them, while each layer has writers and readers tuned to its job.

### Episodic — raw turns and events

The log of what literally happened: conversation turns, tool calls, events. Episodic memories are stored **verbatim**, with **no extraction and no dedup** — the timeline is the point.

```python
mind.log("User asked how to reset their password.", role="user")
mind.log("Sent the reset link to maya@acme.example.", role="assistant")
```

Default `importance` for `log()` is `0.3` (raw activity is rarely the most valuable thing to recall).

### Semantic — distilled facts

The durable, de-duplicated facts an agent should *know*: preferences, attributes, decisions. This is what `remember()` produces.

```python
mind.remember("Maya prefers dark mode and concise answers.")
mind.remember("Acme Inc is on the enterprise plan.")
```

Default `importance` is `0.5`. Unlike `log()`, `remember()` runs **extraction** and **dedup** (see below).

### Graph — temporal knowledge graph

Entities and the relationships between them, where **each edge is valid over a time range**. This is what makes Logica Mind a time machine rather than a flat fact list: when a relationship changes, the old edge is invalidated rather than overwritten, so you can replay the state of the world at any past instant.

```python
mind.learn_graph("Maya joined Acme as a designer in 2024.")
mind.remember("Maya was promoted to design lead.", build_graph=True)
mind.entity("Maya")          # canonical name, type, aliases, edges, neighbours
```

The graph needs an LLM to *extract* triples from prose, so `learn_graph()` and `build_graph=True` are **no-ops offline**. See [The temporal graph](./knowledge-graph.md).

### User — the dialectic user model

An evolving, theory-of-mind model of *who the user is* — built from observations, not just facts. Where semantic memory stores "the user said X", the user layer reasons about the user as a person ("tends to prefer brevity", "works in fintech").

```python
mind.observe_user("Seems to value speed over hand-holding.")
print(mind.user_profile())
print(mind.ask_about_user("How should I communicate with them?"))
```

Observation storage works offline; the higher-level *deriving* of new traits from a conversation (`derive()` / `ingest_conversation(..., derive=True)`) needs an LLM. See [The user model](./user-model-and-peers.md).

## `remember()` vs `log()`

These are the two write paths, and choosing between them is the single most important decision when wiring up memory.

| | `remember()` | `log()` |
| --- | --- | --- |
| Default layer | `SEMANTIC` | `EPISODIC` (fixed) |
| Extraction | **Yes** (with an LLM) | No |
| Dedup | **Yes** | No |
| Conflict resolution | **Yes** (add / update / delete) | No |
| Default `importance` | `0.5` | `0.3` |
| Use it for | Durable knowledge | Raw history |

**`log()`** is a faithful recorder. It stores the text exactly as given on the episodic layer, attaches `role`/`session`/`metadata`, and returns. Nothing is merged or dropped.

**`remember()`** is opinionated. With an LLM extractor configured, it reads the text *and the existing related memories*, then decides what to do emitting one or more operations:

- **add** a genuinely new fact,
- **update** an existing one that changed (the old row is replaced, a `supersedes` link and a snapshot of the prior belief are kept for provenance),
- **delete** a fact that's now false,
- **noop** when nothing's new.

Offline (no LLM), `remember()` skips extraction and stores the text as a single semantic fact, but **still runs dedup**. You can force this behavior explicitly:

```python
mind.remember("Maya prefers dark mode.", extract=False)   # store verbatim, no LLM
```

> Stored `importance` is `max(importance, fact.importance)` — the extractor can raise a fact's importance above the call's default, never silently lower it.

## Dedup

Before a fact is persisted, `remember()` searches the same namespace and layer for the most similar existing memory. If that best match scores **≥ `dedup_threshold`** (default `0.92`), the write is treated as a duplicate and skipped — so logging the same preference twice doesn't create two rows.

```python
mind = LogicaMind(dedup_threshold=0.95)   # stricter: only near-identical text dedups
```

Dedup is **session-scoped when you pass a `session`**: the same fact captured under a different session is still stored (different context), while session-less writes dedup globally. Document ingestion (`ingest_document`) relies on the same mechanism so re-ingesting an unchanged file is cheap.

`recall()` applies a second, lighter dedup on the way out: near-identical content (for example the same fact both `log()`-ged and `remember()`-ed, or mirrored across stores) is collapsed, keeping the highest-scored instance.

## Hybrid recall

`recall()` is the heart of the read path. The pipeline:

1. **Embed the query** (offline: the hashing embedder; otherwise your configured embedder).
2. **Hybrid store search** — overfetch a candidate pool, optionally scoped by `session`, `category` or any `metadata_filter`. For each candidate the store computes a **similarity in `[0, 1]`**:
   - **vector path** — cosine similarity, when both the query and the memory have vectors *of matching dimension*;
   - **lexical path** — a term-overlap score, used when a memory has no vector, or when vector dimensions don't match (e.g. you swapped embedders on existing data). The lexical fallback keeps recall working during a migration instead of returning zeros.
3. **Blend** similarity with importance and recency into the final score (next section).
4. **Dedup** near-identical content.
5. **Optional rerank** — if you configured a `reranker`, it re-scores the top pool and owns the final order. See [Rerankers](./embeddings-and-reranking.md).

```python
# scope a recall to one session and drop low-rated facts
hits = mind.recall(
    "what did we decide?",
    session="run-42",
    min_importance=0.4,    # fact-rating threshold
    limit=5,
)
```

You can restrict which layers to search:

```python
from logica_mind import MemoryLayer

facts = mind.recall("user preferences", layers=[MemoryLayer.SEMANTIC])
```

### The blend: importance and recency

A pure-similarity search surfaces the *most textually relevant* memory — which isn't always the *most useful* one. Logica Mind blends three signals into the final score:

```
score = w_sim · similarity  +  w_imp · importance  +  w_rec · recency
```

The default weights are `(0.60, 0.25, 0.15)` — similarity leads, but a high-importance or fresh memory can edge out a slightly-more-similar stale one. You set them at construction:

```python
mind = LogicaMind(weights=(0.7, 0.2, 0.1))   # lean harder on similarity
```

**Importance** is the memory's own `importance` field (you set it on write; the extractor can raise it).

**Recency** is an Ebbinghaus-style exponential decay in `(0, 1]`, controlled by `half_life_days` (default `7.0`):

```
recency = 0.5 ** (age_seconds / (half_life_days · 86400))
```

A brand-new memory scores `1.0`; after one half-life it's `0.5`; after two, `0.25`. A longer half-life makes recall more stable over time; a shorter one favors the latest information.

```python
mind = LogicaMind(half_life_days=30.0)   # memories stay "fresh" much longer
```

Because the store returns raw similarity and the core does the blending, the weighting is **identical across every backend** — SQLite, Postgres, Redis or Supabase all rank consistently.

### Usage tracking

By default (`track_access=True`), every memory a recall surfaces gets its `access_count` bumped and `last_recalled_at` updated. This is an update-only operation — it never re-inserts a memory into a backend that didn't have it — and it gives later features (and the dashboard) a signal for which memories actually earn their keep. Turn it off with `track_access=False`.

## Putting it together

A typical session touches all four layers without you thinking about it:

```python
from logica_mind import LogicaMind, MemoryLayer

mind = LogicaMind(namespace="support")

# episodic: log the raw exchange
mind.log("Hi, I can't log in.", role="user")
mind.log("Let's reset your password.", role="assistant")

# semantic: distill a durable fact
mind.remember("Maya had a login issue resolved via password reset.")

# user: model the person
mind.observe_user("Gets frustrated quickly with friction in auth flows.")

# recall blends meaning + importance + recency across layers
for hit in mind.recall("what's Maya's history with login?"):
    print(hit.memory.layer.value, hit.score, hit.memory.content)
```

From the terminal, the same ideas are one command away:

```bash
logica-mind remember "Maya prefers dark mode."
logica-mind recall "what does the user like?"
logica-mind stats          # per-layer counts
```

## See also

- [Quickstart](./quickstart.md) — install and run in 30 seconds.
- [Types](./concepts.md) — `Memory`, `MemoryLayer`, `SearchResult` reference.
- [Stores](./stores.md) — SQLite, Postgres, Redis, Supabase and more.
- [Embedders](./embeddings-and-reranking.md) — the offline hashing embedder and pluggable providers.
- [The temporal graph](./knowledge-graph.md) — entities, edges and point-in-time replay.
- [The user model](./user-model-and-peers.md) — the dialectic, theory-of-mind layer.
- [Rerankers](./embeddings-and-reranking.md) — a second-pass scorer over the recall pool.
- [CLI](./cli.md) — `remember`, `recall`, `dream`, `stats`, `ui` and more.
