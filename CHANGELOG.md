# Changelog

All notable changes to Logica Mind. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versions are date-stamped.

## [0.2.0] — 2026-06-05

### Graph intelligence
- The knowledge graph became an instrument. Every link now carries a kind
  (relation / co-mention / semantic), direction, weight and predicate class;
  every node a PageRank **centrality** and a **bridge** flag. New connection
  **layers**: emergent **co-mentions** and opt-in **semantic** affinity.
- New reasoning: **`how_related(a, b)`** (narrated shortest path),
  **`bridges()`** (articulation points), **`suggested_links()`** (Adamic-Adar
  link prediction), and **`entity_unlinked()`** (unlinked mentions). Exposed
  as `lm_how_related` / `lm_bridges` / `lm_suggested_links` and `/api/path`,
  `/api/bridges`, `/api/suggested`. **MCP server is now 32 tools.**
- Dashboard graph: an **edge grammar** (hue by relation type, arrows, width by
  confidence, node size by centrality), a professional **top filter bar**
  (colour-by, layer toggles, search-focus, min-confidence + predicate filters,
  highlight-by-query), a **local/ego graph** with a depth slider, **hover
  previews**, and **Path mode** that traces & spotlights "how is A related to
  B?". Predicate labels localize (pt/es) with a graceful fallback.

### Internationalization & UX
- **15 languages, lazy-loaded** — added 中文, 日本語, 한국어, हिन्दी, বাংলা,
  العربية (RTL), Français, Deutsch, Italiano, Türkçe, Русский and Bahasa
  Indonesia to English / Português / Español, with full key parity (420 keys
  each). Each non-English dictionary is a separate chunk loaded on demand, so
  the main bundle stays lean. Even the graph's relationship labels localize.
  Arabic flips the layout to RTL; first visit auto-matches the browser language.
- **Clean URLs** — dropped the `#`: real history routing (`/graph/org:acme`),
  deep links and refresh work via the server's app-shell fallback.
- Hover tooltips on every graph control.

### Fact categorization
- Every durable fact is tagged with a **category** (an open label the LLM coins)
  and a **dimension** from a 34-dimension taxonomy across four groups — Personal
  (mapped to Maslow's hierarchy), Projects, Organization, and Business & Finance.
- `dimensions()` returns the full profile grouped by dimension + Maslow tier;
  category/dimension ride on every memory (`recall`/`remember`, `/api/memories`,
  ⌘K search) and the new `lm_dimensions` MCP tool.
- **Zero-key option** — categorization auto-detects an `ANTHROPIC_API_KEY` /
  `OPENAI_API_KEY`, or uses the local **Claude CLI** (`LOGICA_MIND_LLM=claude-cli`).

### Connections — derived backlinks
- `connections(id)` infers a memory's neighborhood with no manual `[[links]]`:
  the entities it mentions (typed, life-area coloured), the relations touching
  them, other memories that mention the same entities (auto-backlinks), and
  siblings sharing its category/dimension. Exposed as the `lm_connected` MCP tool
  and `/api/connected`. **MCP server is now 29 tools.**

### Dashboard
- Unified **Profile** view (cards + a clickable knowledge-map) tabbed by Person /
  Projects / Organization / Business, with the dialectic user model folded in.
- **Knowledge graph** gains colour-by-life-area + per-area filtering (entities
  carry a `dimension` in `graph_viz`).
- **Connected** panel in the note pane — walk note-to-note (with a back stack);
  `[[wikilinks]]` and Markdown render in memory content.
- Global ⌘K Spotlight, a Settings *page* with an Integrations panel, contextual
  help on every page, paginated lists, and a categorized sidebar.

## [0.1.0] — 2026-06-04

First complete release: a pluggable, multi-store memory library for AI agents
with episodic, semantic, temporal-graph and dialectic user memory in one library.

### Memory engine
- Four layers: episodic, semantic, temporal **graph**, and a dialectic **user model**.
- Hybrid recall (vector ⊕ lexical) with importance/recency blending, dedup, and
  optional rerankers (MMR, Voyage, NodeDistance, EpisodeMention, **RRF**).
- Automatic extraction (add/update/delete/noop) with dedup and custom categories.
- **Conversation ingestion** — `ingest_conversation(messages=[{role, content}…])`
  logs turns, extracts facts seeing the whole exchange, and derives observations.
- **Deriver** — `derive()` infers user observations from recent turns; runs eagerly
  from `ingest_conversation` and lazily inside `dream()`, so the user model builds
  itself from conversation (no manual `observe_user` required).

### Temporal knowledge graph
- Fact invalidation, point-in-time queries (`edges(at=)`), communities, confidence
  ratings, custom entity/edge types, provenance, BFS.
- Moats: `contradictions()` (time-machine), `diff()` (memory changelog),
  `transfer_to()` (cross-agent), `forget_about()`/`purge()` (GDPR erase).

### Multi-perspective peers
- `observe_peer` / `peer_card` / `peer_query` — directional theory-of-mind.

### Stores & embedders
- Stores: SQLite (default, thread-safe), InMemory, Obsidian, MultiStore,
  Supabase (pgvector RPC), Postgres, Redis.
- Embedders: Hashing (offline default, zero-key), Voyage, OpenAI, Local, Batched,
  VoyageMultimodal.

### Interfaces
- **MCP server** (27 tools) — memory, peers, reflect, contradictions, diff,
  conversation ingestion, plus coding-context devtools.
- **REST API** + **React/Vite/Tailwind dashboard** — Overview, animated graph
  explorer (canvas physics), Memories, Calendar (Obsidian-style heatmap), User
  model, Peers, Changes (contradictions + changelog), Insights, and write actions.
- Auto-capture **hooks** (SessionStart/UserPromptSubmit/Stop/PreCompact).
- Adapters for LangChain and LlamaIndex.

### Quality
- 103 offline tests (no API keys). Multiple adversarial review passes.
- Fully offline by default (SQLite + hashing embedder + no LLM); real providers
  are opt-in.

[0.1.0]: #
