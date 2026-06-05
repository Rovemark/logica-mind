# Logica Mind

**Pluggable, multi-store memory for any AI system.**

One library that gives any agent four kinds of long-term memory, with storage
backends and embedding providers you switch by config — not by rewrite.

Logica Mind is the memory layer you drop in once. It owns *remember / recall /
forget* and an evolving model of the user, while you toggle **where it stores**
(SQLite, Postgres, Redis, Supabase, Obsidian, in-memory, or several at once) and
**how it embeds** (offline hashing, Voyage, OpenAI, or a local model). It runs
**out of the box with zero API keys and zero third-party dependencies** — the
default is a local SQLite store plus an offline hashing embedder. Plug in a real
embedder, a database, or an LLM and the matching feature lights up.

> Originally extracted from an internal multi-agent system, now a standalone
> Apache-2.0 library.

---

## Install

```bash
pip install logica-mind              # core only (stdlib, fully offline)
pip install "logica-mind[voyage]"    # + Voyage embeddings
pip install "logica-mind[openai]"    # + OpenAI embeddings + LLM extraction
pip install "logica-mind[local]"     # + local sentence-transformers embedder
pip install "logica-mind[postgres]"  # + Postgres store
pip install "logica-mind[redis]"     # + Redis store
pip install "logica-mind[all]"       # everything
```

Requires Python 3.9+.

## 30-second Quickstart

No API keys, no extra dependencies — local SQLite + offline embedder by default.

```python
from logica_mind import LogicaMind

mind = LogicaMind(namespace="my-agent")

# Remember durable facts (plug in your own content).
mind.remember("The user prefers short, direct answers.")
mind.remember("The user works in the Pacific time zone.")

# Recall the most relevant memories for a query.
for hit in mind.recall("how should I phrase my replies?"):
    print(round(hit.score, 3), hit.memory.content)
```

To light up real semantic search, swap in an embedder and a store — the rest of
your code stays the same:

```python
from logica_mind import LogicaMind
from logica_mind.embeddings import VoyageEmbedder
from logica_mind.stores import SupabaseStore

mind = LogicaMind(
    namespace="my-agent",
    embedder=VoyageEmbedder(model="voyage-3-lite"),  # reads VOYAGE_API_KEY
    store=SupabaseStore(),                            # reads SUPABASE_URL / KEY
)
```

Or write to several backends at once — fast local recall plus a human-readable
audit trail:

```python
from logica_mind.stores import MultiStore, SQLiteStore, ObsidianStore

mind = LogicaMind(
    namespace="my-agent",
    store=MultiStore([
        SQLiteStore("mind.db"),
        ObsidianStore("~/vault/memories"),
    ]),
)
```

## The four memory layers

| Layer | What it holds |
|-------|---------------|
| **episodic** | Raw turns and events, logged as they happened. |
| **semantic** | Distilled, de-duplicated facts ("the user prefers X"). |
| **graph** | A temporal knowledge graph: entities and relationships, each edge valid over a time range. |
| **user** | A dialectic, evolving model of who the user is. |

A single `recall()` searches across layers with **hybrid retrieval** — vector
similarity combined with lexical matching, scored by importance and recency,
de-duplicated, and optionally reranked. When no embedder key is configured, recall
degrades gracefully to lexical search instead of failing.

## What makes it different

Beyond store-and-retrieve, Logica Mind models how memory actually behaves over
time:

- **Ebbinghaus forgetting curve** — beliefs decay on a configurable half-life;
  surface what's about to be forgotten, or reinforce what keeps getting recalled.
- **Contested beliefs** — when a new belief supersedes a high-confidence old one,
  the system records the contest instead of silently overwriting it.
- **Surprise scoring** — flags paradigm shifts where a new belief diverges sharply
  from a prior high-confidence one (`surprise = old_importance × cosine_distance`).
- **Dreaming** — a sleep-time consolidation cycle that distills episodic turns into
  semantic facts, reinforces frequently-recalled memories, prunes stale traces,
  derives user observations, and can infer new links.
- **Temporal knowledge graph** — entity aliasing (variants resolve to a canonical
  name) and point-in-time queries (`state_at`) reconstruct what was true at any
  past moment.
- **Dialectic user model** — answers questions *about* the user by reasoning over
  accumulated observations, not just string matching.
- **Peers** — directional, theory-of-mind observations: what one party knows or
  believes about another.
- **Multi-agent shared-entity graph** — multiple agents contribute to and query the
  same entity graph.
- **Structured session/run records** — capture an orchestrated run (participants,
  per-participant contributions, aggregate metrics, status, links) as queryable,
  recallable history. Framework-agnostic.
- **HMAC-signed portable memory bundles** — export your memory and move it between
  apps or vendors, optionally signed so the destination can verify integrity.

## Rerankers

Recall over-fetches a candidate pool, then optionally reranks it. Built-in
rerankers: **MMR** (relevance vs. diversity), **Voyage** (cross-encoder),
**RRF** (reciprocal rank fusion), **node-distance** (graph proximity), and
**episode-mention** (recency of entity mentions in episodic memory).

## Stores and embedders

**Stores (7):** `SQLiteStore`, `InMemoryStore`, `ObsidianStore`, `MultiStore`,
`SupabaseStore`, `PostgresStore`, `RedisStore`.

**Embedders (6):** `HashingEmbedder` (offline default), `VoyageEmbedder`,
`OpenAIEmbedder`, `LocalEmbedder` (sentence-transformers), `BatchedEmbedder`
(batching wrapper), `VoyageMultimodalEmbedder`.

## Framework adapters and SDKs

- **LangChain** — `logica_mind/integrations/langchain.py`
- **LlamaIndex** — `logica_mind/integrations/llamaindex.py`
- **TypeScript SDK** — a thin REST client in [`sdk-ts/`](sdk-ts/), published as
  `@logica-mind/sdk`.
- **Provider adapter** — [`examples/provider_adapter.py`](examples/provider_adapter.py)
  shows how any host maps its `recall()` / `save()` calls onto Logica Mind through a
  small, framework-agnostic interface.

See [`examples/quickstart.py`](examples/quickstart.py) for the minimal end-to-end
example.

## Automatic capture (hooks)

Don't want to call a tool to remember? Hooks capture sessions on their own, running
on your agent's lifecycle events (Claude Code and any host with the same contract):

| Event | What happens |
|-------|--------------|
| **SessionStart** | Injects a brief: what we know about the user + recent activity. |
| **UserPromptSubmit** | Recalls memory relevant to the prompt, then saves the prompt. |
| **Stop** | Saves what the assistant did on the last turn. |
| **PreCompact** | Consolidates before the context window is compacted. |

```bash
logica-mind install-hooks    # writes the hooks into your host's settings
```

Each hook is a fast, fail-safe subprocess that reads the host's JSON event on
stdin and returns additional context on stdout. It uses Voyage/OpenAI embeddings
automatically when a key is set, else the offline default.

## MCP server

`logica-mind mcp` runs a stdio MCP server exposing **27 tools**, so any MCP client
(Claude Code, Cursor, Windsurf) gets a deep memory brain plus a set of
token-saving coding-context tools — memory (`lm_remember`, `lm_recall`,
`lm_context`, `lm_forget`, `lm_dream`, …), user/peer modeling, temporal queries,
team knowledge base, and dev utilities (`lm_execute`, `lm_scan`, `lm_git`,
`lm_mcp`, `lm_budget`).

Add it to your MCP client config:

```json
{ "logica-mind": { "type": "stdio", "command": "logica-mind", "args": ["mcp"] } }
```

## Dashboard

A self-hosted web dashboard browses and inspects your memory. The published wheel
ships the pre-built dashboard, so end users only need:

```bash
logica-mind ui    # serves the dashboard on http://localhost:8420
```

To build the dashboard from source (Node 18+):

```bash
cd logica_mind/web/app
npm ci
npm run build
```

Then launch it with `logica-mind ui` as above.

## Status

`v0.1.0` — alpha. Episodic, semantic, multi-store, and pluggable embeddings are
solid. The temporal graph and dialectic user model are functional and deepening.

## License

Apache-2.0 — © 2026 Rovemark. See [LICENSE](LICENSE).
