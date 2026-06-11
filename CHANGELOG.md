# Changelog

All notable changes to Logica Mind. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versions are date-stamped.

## [0.3.4] — 2026-06-11

### Fixed
- **README images and links on PyPI**: relative paths became absolute GitHub
  URLs, so the project page renders the demo GIFs and benchmark links.
- **Leaner sdist** (30MB → ~2MB): documentation images are no longer packed
  into the source distribution.

## [0.3.3] — 2026-06-11

### MCP in cluster mode — full 32-tool parity against a remote brain
- **`LOGICA_MIND_URL` turns the MCP server into a cluster client**: every memory
  tool (27 of 32) is forwarded to the brain server's new `POST /api/mcp/dispatch`
  endpoint, which runs the exact same tool dispatch against the server's own
  store and embedder — so a workstation's Claude Code/Cursor sees the SAME brain
  as every other node, instead of an empty local store. The 5 coding-context
  devtools (`lm_execute`, `lm_scan`, `lm_git`, `lm_mcp`, `lm_budget`) keep
  running on the client machine, where the repo actually lives.
- Auth follows the per-request model: loopback callers trusted, remote callers
  send the `LOGICA_MIND_TOKEN` bearer automatically when set. The server refuses
  client-machine tools (defense in depth). Regression-tested end to end.

## [0.3.2] — 2026-06-10

### Fixed — memory writes behind a public bind (cluster mode)
- **Write endpoints were dead on any non-loopback bind**: `serve(host="0.0.0.0")`
  (the cluster/server topology, typically behind a reverse proxy) gated writes on
  the *bind host*, so every POST — including from the machine's own memory
  pipeline — got `403 writes disabled`, silently stalling ingestion. Writes are
  now authorized **per request**, exactly like reads: loopback callers are always
  trusted, remote callers need the `LOGICA_MIND_TOKEN` bearer.
  `allow_writes=False` remains a hard read-only switch. Regression-tested.

### Dimension labels in your language
- The 34-dimension taxonomy (plus the four life/work areas) is now translated in
  **all 15 UI languages** — graph facet sidebar, orbit/ring hub labels, legend
  and the Profile cards/map show e.g. *Saúde*, *Receita*, *Cronograma* instead
  of raw English ids. Ids the taxonomy doesn't know keep the prettified raw id.

## [0.3.1] — 2026-06-10

### Graph explorer
- **Facet filter is now a collapsible right sidebar** — the value chips
  (channels, agents, areas, types…) overflowed the toolbar on facets with many
  values and could collide with the button rows. They now live in an organized,
  scrollable panel anchored below the toolbar: one row per value (colour dot +
  label + count), same click-to-hide and shift+click-to-solo semantics, open/
  closed state persisted. The toolbar gains a compact toggle showing the
  visible/total count.
- New `close` UI string translated in all 15 languages.

### Docs
- Documentation screenshots are now captured exclusively from the bundled
  `logica-mind demo` dataset.

## [0.3.0] — 2026-06-10

### Graph-aware recall (retrieval 2.0)
- **Recall now uses the knowledge graph**: when the query names a graph entity,
  memories about its **1-hop neighbours** rank up too (`graph_boost`, on by
  default) — ask about *Voyspark* and the facts connected to it surface, not
  just the strings that literally match.
- **`context()` injects the graph's own knowledge**: a compact
  `## Knowledge graph` section with the query entities' strongest facts,
  budget-fitted, before the prose memories.

### Semantic embeddings without torch (`onnx`)
- New **`OnnxEmbedder`** (`pip install logica-mind[onnx]`): all-MiniLM-L6-v2
  via onnxruntime + tokenizers — ~50MB of wheels instead of ~2GB of torch,
  true semantic recall offline. Model auto-downloads once.
- New **`logica-mind reembed`** (and `mind.reembed()`): re-embeds every memory
  with the current embedder — the safe dimension migration when switching
  embedders (hashing 256d → onnx/local 384d → voyage 1024d).
- **Benchmarked** (see `bench/`): on full LoCoMo evidence-recall, `onnx` scores
  **+22% recall@5 / +20% recall@10** over the hashing default.

### Offline fact extraction
- The zero-key default extractor is now **HeuristicExtractor**: keyword voting
  against the taxonomy's own example categories (plus a pt-BR supplement) tags
  a life/work **dimension** per fact — offline clients get a living Profile and
  a coloured graph out of the box. Conservative: no evidence → no tag.

### Entity resolution & editing
- **Read-time entity resolution**: edge endpoints are canonicalized through the
  alias map, so casing/spacing variants (`LogicaOS` / `Logica OS`) and explicit
  merges collapse onto ONE node everywhere (viz, dimensions, co-mentions,
  facets) without rewriting stored rows.
- **Rename/merge in the dashboard**: every entity panel has a merge field, and
  the new `POST /api/entity/alias` endpoint (plus SDK method) does it
  programmatically. Non-destructive, alias-based.

### Benchmarks
- New **`bench/locomo.py`**: judge-free LoCoMo evidence-recall harness with a
  results table in `bench/README.md` (reproducible in one command).

### SDK & security
- **Official TypeScript client** (`clients/typescript`): tiny, dependency-free,
  typed — remember/log/recall/context/graph/entityAlias. (LangChain and
  LlamaIndex adapters already ship in `logica_mind.integrations`.)
- **At-rest encryption (optional)**: `SQLiteStore(encryption_key=…)` via
  SQLCipher (`pip install logica-mind[sqlcipher]`).

### Explorer polish
- Facet hubs keep a minimum on-screen size zoomed out (collapse-to-hubs
  overview) and stay clickable; a one-time first-visit hint points at the
  layout/facet superpowers; new strings translated in all 15 languages.

## [0.2.31] — 2026-06-10

### Performance (the graph opens ~50× faster warm)
- **Read-side cache for `/api/graph`** keyed by a cheap store change-token —
  unchanged data serves the cached payload (~80ms over the wire, was ~4s every
  time); any write flips the token.
- **`store.all()` is now uncapped enumeration** — the search candidate window no
  longer applies to it, fixing a silent bug where a namespace with more graph
  rows than the window dropped its OLDEST edges from the graph, dimensions and
  co-mentions (seen live: 2,471 of 7,471 edges invisible).
- Graph paths skip embedding parsing entirely (`with_embeddings=False`), the
  co-mention scan swapped its giant alternation regex for the sliding n-gram +
  set-membership matcher (~60× faster, punctuated names now match), entity
  dimension voting reuses the node list instead of re-reading the graph layer,
  and **partial expression indexes** back every facet query.

### Facets & explorer
- **New colour/organisation facets: source, project, squad** — same generic
  metadata voting as channel; options grey out without data, legends show
  per-value counts everywhere.
- **Facet votes are global**: tags on any namespace's memories colour the
  entity in every view (a squad tag written by one agent lights the entity up
  in another agent's graph).
- **Shift+click = SOLO** on filter chips and on hub discs ("only telegram" in
  one click); **Esc** clears filters/highlights/spotlights; `l`/`c`/`f` toggle
  the layout/colour/filter menus; colour facet is persisted like the layout.
- Click-spotlight now takes precedence over Path mode; single-member hubs keep
  a small disc; the facet-less periphery spreads over multiple rims instead of
  one giant circle; the hub ring scales with the dominant group so orbits stay
  readable; stale focus/path state auto-clears when nodes leave the view.
- Hub labels get zero-asset icon cues (entity types, channels, agents) and the
  orbit centre shows the active namespace.
- The 17 new UI strings are translated in **all 15 languages**.

### Tests
- New `tests/test_graph_facets.py` locks in uncapped enumeration, the tagged()
  whitelist, facet voting, node facets in `/api/graph`, cache hit/invalidation
  and the mentions() superset guarantee. Full suite: 195 passed.

## [0.2.30] — 2026-06-10

### Facet filters
- **Generic facet-value filter chips** on the graph: one chip per value of the
  active colour facet (channels, agents, life-dimensions, entity types) with
  node counts. **Multi-select toggles** — switch values off to keep only the
  ones you want (e.g. only `telegram` + `whatsapp`); a *show all* chip resets.
  Replaces the old single-select, area-only filter. Chips share the graph's
  golden-angle colours and scroll when a facet has many values.

## [0.2.29] — 2026-06-10

### Graph explorer: layouts, facets & spotlight
- **Three organisation modes** (new "Organize" control, persisted): organic
  **Web** (force), **Orbits** — facet hubs on a circle with their members
  orbiting them, a centre disc for the namespace and facet-less nodes on the
  outer rim (the org-map look) — and **Rings** — concentric tiers by PageRank
  importance, sliced into one angular sector per facet. Switching layouts
  morphs smoothly instead of teleporting.
- **Facet colour engine**: stable golden-angle colours per distinct value — all
  **34 life-dimensions** (was 4 area buckets), one colour per namespace (was 10
  cycled), a new **entity type** mode (covers every graph node) and a new
  **channel** mode. Legends adapt per mode; modes grey out without data.
- **Channel facet (generic)**: any memory tagged `metadata.channel` (whatsapp,
  telegram, voice, sessions, …) votes its channel onto the entities it mentions
  — `store.tagged(ns, key)` + `LogicaMind._entity_facets` accept any metadata
  key (project/squad/skill/source ready). Nodes carry `channel` in `/api/graph`.
- **Click-spotlight**: clicking a node dims everything except it + its direct
  neighbours; clicking a **facet hub** spotlights the whole group (only that
  channel's / agent's participants stay lit). Hubs are clickable and the
  selected hub gets a ring.
- Graph nodes now expose their **entity `type`** (Concept / Product / Person /
  Organization / Place / Project) in `/api/graph` (per-namespace and `__all__`).

### Performance
- `/api/node` (hover preview + entity detail) no longer scans the whole
  namespace: new SQL `store.mentions()` pre-filter, a light `preview=1` path
  and **lazy unlinked-mentions** (`unlinked=1`). Hover ~23× faster and click
  ~4× on busy entities; `entity_unlinked()` uses the same pre-filter.
- Profile / dimensions / calendar / session queries moved to uncapped SQL
  (`day`, `dimension_counts`, `filter_memories`, `dimensioned`) so older data
  is never silently truncated by the in-memory candidate window.

### User model
- `observe_user` on long documents: stores the full source, extracts atomic
  observations section-by-section **in the document's language**, then
  synthesizes the profile — no more lossy single-blob ingestion.

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
