# Changelog

All notable changes to Logica Mind. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versions are date-stamped.

## [0.4.14] — 2026-06-17

### Translations & local-model detection
- **The LLM picker and Dream schedule UI are now translated** into all 14 dashboard
  languages (was English-only via fallback).
- **MLX detection**: the local-model probe now also covers the port MLX's
  `mlx_lm.server` 4-bit slot uses, so an MLX model served OpenAI-style is picked up
  alongside Ollama / LM Studio / llama.cpp / vLLM.

## [0.4.13] — 2026-06-16

### Pick the LLM that serves your memory — any model, no key required
- **Smart LLM auto-detection**: `auto_llm()` now finds a local open-source model
  behind an OpenAI-compatible server (Ollama, LM Studio, llama.cpp, vLLM, MLX) or
  a self-hosted Anthropic gateway, in addition to hosted keys and the Claude CLI.
  Zero-dependency HTTP transports (`OpenAICompatLLM`, `AnthropicCompatLLM`). It
  stays **network-free unless you configure an endpoint**, so `LogicaMind()`
  construction remains deterministic and never probes ports on its own.
- **Runtime LLM swap**: `mind.set_llm()` rewires the extractor, knowledge graph
  and user model live; `mind.with_llm()` returns a sibling view backed by a
  different LLM (so a keyless write path can still run an LLM-powered consolidation).
- **Dashboard LLM picker**: Settings → Integrations is now a working picker —
  tap a detected model to make it serve the whole mind (applied live via
  `POST /api/integrations`, persisted across restart). Tap the active one to go
  keyless.
- **Dream schedule controls**: the Dreams page exposes the cadence — how often it
  runs, how many turns it distills per cycle, and a pause toggle
  (`GET`/`POST /api/dream/config`).
- **Consolidation works without an LLM on the write path**: when the serving mind
  is keyless, `/api/dream` runs the consolidation through an auto-detected LLM on
  the same store — fast cheap writes, distilled facts at sleep-time.

## [0.4.12] — 2026-06-16

### Language-neutral retrieval gate
- **No hardcoded locale in the shipped library**: the force-recall list is now
  English only (the library's lingua franca) and reads extra terms from
  `LOGICA_MIND_FORCE_TERMS` (a regex alternation, e.g. `lembr\w*|sobre mim`). The
  previous gate baked Portuguese keywords into an i18n library; deployments now
  extend it for their own language via env instead of forking. A malformed
  override falls back to the base list rather than breaking the gate. The
  language-agnostic default (recall on any non-trivial prompt) is unchanged, so
  this only affects which *short* prompts force recall.

## [0.4.11] — 2026-06-16

### Recall fires when you ask about memory
- **Stronger retrieval gate**: prompts like "what do you know about me", "summarize
  me", "look at your memory", "remind me what we were doing" now reliably *force*
  recall+injection. The gate also matches inflected forms (`lembra`/`lembrar`,
  `resuma`/`resumir`) that the old word-boundary pattern missed. Memory-about-the-user
  requests were the most likely to silently skip injection; now they don't.

## [0.4.10] — 2026-06-16

### Dashboard & server robustness
- **Session names persist with a MultiStore**: renaming a session (and the
  "import from Claude Code" naming button) silently no-op'd when the dashboard
  ran on a `MultiStore` (e.g. SQLite + Obsidian), because the names file was
  derived from `store.path`, which a MultiStore does not have. It now falls back
  to the first child store that has a path, so names save next to the db.
- **A dropped client can't crash the server**: the response writer now swallows
  `BrokenPipeError` / `ConnectionReset` / `ConnectionAborted`, so a caller that
  hangs up mid-response (closed tab, timed-out request) no longer raises out of
  the worker thread.

## [0.4.9] — 2026-06-16

### Capture that heals itself
- **Self-healing `Stop` reconcile**: the `Stop` hook no longer just saves the last
  assistant message — it reconciles the recent transcript against the store and
  captures every user/assistant turn that is missing, deduplicated by normalized
  content. A turn whose live capture failed (store briefly unreachable), or a whole
  session where hooks were enabled midway, is now recovered at the end of the turn
  instead of being lost forever.
- **Failures are logged, not swallowed**: capture is still fail-soft, but every
  failure is now appended to `~/.logica-mind/capture.log` with a timestamp, so a
  broken capture path is visible instead of silently dropping memory.
- **`logica-mind backfill <path>`**: import past transcripts (a file or a folder
  scanned recursively) that predate the hooks. Idempotent and dedup-aware, it lands
  each turn in the namespace the live hook would have used (read from the
  transcript's recorded working directory). New `hooks.backfill()` API.

## [0.4.8] — 2026-06-16

### Measuring the injection path
- **Context-mode judge harness**: `bench/locomo_judge.py` gained
  `--via context --profile {speed,balanced,deep}`, so the benchmark can grade the
  *assembled* `context()` block a hook injects — not only `recall()`. The 0.4.x
  injection work (profiles, the `safe=True` instruction frame, pin/snooze, the
  ratio cutoff) shapes that block; without this path those changes were invisible
  to the score. First result on a keyless control (180 paired questions): the
  injection path is statistically indistinguishable from raw recall (McNemar
  p≈0.44) at **~27% fewer context tokens** — the safety frame and tail cutoff are
  a free token saving, not an accuracy tax.
- **Keyless benchmark reproduction**: the J harness now drives any Anthropic
  Messages-compatible endpoint via `BENCH_LLM=anthropic` (answerer + judge,
  honouring `ANTHROPIC_BASE_URL` for self-hosted or proxy gateways), so the J
  score is reproducible with no OpenAI key. The published rows still use the
  gpt-4o-mini protocol; this only lowers the barrier to re-run it.
- **Docs**: new [Retrieval profiles, injection safety & lifecycle](docs/retrieval-and-injection.md)
  guide covering profiles, hooks-first hardening, pin/snooze, type-aware
  forgetting, neighbor evolution, the anti-contamination guardrail and read/write
  context isolation. BENCHMARKS.md now documents the two retrieval paths.

## [0.4.7] — 2026-06-12

### Self-organizing memory (Wave 3)
- **Neighbor evolution** (`dream(evolve=True)`): an undimensioned memory inherits
  its life/work dimension from a majority vote of its confident nearest
  neighbours. Fully offline and deterministic, so the keyless path gradually
  acquires categorization without any LLM. Off by default; fail-soft.

## [0.4.6] — 2026-06-12

### Safer synthesis (Wave 3)
- **Anti-contamination guardrail on inductive inference**: `infer_links()` now
  drops any synthesized fact that introduces a proper noun absent from the source
  facts (fail-closed), blocking the most dangerous failure mode of generative
  memory — the LLM hallucinating a new entity into a conclusion. Legitimate
  inferences built only from known entities are kept.

## [0.4.5] — 2026-06-12

### Relational recall (Wave 3)
- **Bounded beam search over the graph**: the `deep` profile expands two hops out
  through a bounded beam (beam width, total node budget), so relational questions
  ("how does A connect to C?") reach facts two hops away without the cost
  exploding. The default 1-hop path is unchanged, so the published benchmark is
  unaffected; deep is opt-in.

## [0.4.4] — 2026-06-12

### Lifecycle & ranking (Wave 2)
- **Content-type-aware forgetting**: the dream cycle now decays memories on a
  half-life that depends on their type (decisions/identity never decay; handoffs
  in 30 days; transient in 7), and frequent recall extends a memory's life up to
  3x (access-reinforcement). Replaces the single global half-life in pruning.
- **Score-formula additions** (no-op on a fresh store, so the benchmark is
  unaffected): a recency-intent weight swap when the query asks for the "latest"
  state, and a log-leveled frequency boost for often-recalled memories.
- **Read/write context isolation**: `LOGICA_MIND_CONTEXT=secondary` lets a cron or
  background subagent READ shared memory without writing to the dialectic user
  model, so automated turns can't drown the real owner's profile.

## [0.4.3] — 2026-06-12

### Lifecycle controls + cleaner injection
- **Pin / snooze**: `mind.pin(id)` floats a memory to the top of recall;
  `mind.snooze(id, until)` hides it until a date; `unpin`/`unsnooze` reverse them.
  Exposed as `lm_pin` / `lm_snooze` MCP tools.
- **Adaptive ratio threshold in `context()`**: injected memories are kept relative
  to the top hit's score (not an absolute floor), fixing the hashing-vs-OpenAI
  score-scale mismatch and trimming the irrelevant tail from injected context.
  `recall()` is untouched, so the published benchmark is unaffected.

## [0.4.2] — 2026-06-12

### Retrieval & cost
- **Lexical MMR fallback**: when there's no query embedding (the keyless/hashing
  path), the MMR reranker now de-duplicates via bigram-Jaccard diversity instead
  of passing candidates through unchanged — no more three phrasings of the same
  fact in the keyless default.
- **`compact` on `lm_recall`**: returns bare content lines (~3x cheaper tokens for
  the agent). `lm_context` gained the `profile` arg (speed/balanced/deep).

## [0.4.1] — 2026-06-12

### Performance profiles for context()
- `context(query, profile=...)`: **speed** skips the knowledge-graph hop and
  retrieves fewer memories (sub-second on large stores — right for per-prompt
  hook injection), **balanced** is the default (graph + 20 memories), **deep**
  widens the pool. On a 12k-memory store, speed cut context assembly ~2.3x.
- `GET /api/context?profile=speed` skips the dashboard's extra candidate recall,
  halving latency on the injection path.

## [0.4.0] — 2026-06-12

### Injection hardening (security) — memory can't become a system instruction
- Auto-injected context (`context()`, `session_brief()`, the session hooks) is now
  **sanitized and wrapped in an instruction frame** by default (`safe=True`). A
  poisoned memory ("ignore previous instructions, you are now…") can no longer act
  as a prompt-injection vector: invisible/bidi control chars are stripped, fake
  role markers and ChatML tokens are neutered, override phrasings are defanged, and
  stored text can't smuggle the frame's own closing tag to escape the sandbox.
  Pass `safe=False` for the raw block. Zero dependencies, pure stdlib.
- **Retrieval gate** in the `UserPromptSubmit` hook: trivial turns (greetings,
  "ok", shell commands, emoji) no longer trigger an embed+recall+inject, and
  memory-referencing turns ("what's my name", "yesterday", "we discussed…") force
  retrieval. Saves tokens and stops noise injection on every turn.
- New `logica_mind.guard` module: `sanitize()`, `frame()`, `should_retrieve()`.

## [0.3.9] — 2026-06-12

### Improved
- **Dashboard language detection** now reads the browser's full ordered
  `navigator.languages` list (not just `navigator.language`) and picks the first
  supported language — a user whose top preference isn't one of the 15 UI
  languages still gets their next preference instead of falling straight to English.
- `HeuristicExtractor` is now exported from `logica_mind.extract` (was only
  reachable via the submodule path).

## [0.3.8] — 2026-06-11

### Hardened public mode
- In `LOGICA_MIND_PUBLIC` mode, writes now require an explicit bearer token and
  **loopback is no longer trusted for writes** — a reverse proxy (HF Spaces,
  nginx) forwards traffic and can appear as a local peer, so a public read-only
  deployment without a token is now genuinely unwriteable. Reads stay open.

## [0.3.7] — 2026-06-11

### Public read-only mode (shareable live dashboard)
- **`LOGICA_MIND_PUBLIC=1`** opens every `GET /api/*` so the dashboard can be
  served as a public live demo or a read-only board, while **writes stay gated**
  exactly as before (remote POSTs still get 401). Off by default — opt-in for a
  deployment you want to share. This is what powers the hosted demo.

## [0.3.6] — 2026-06-11

### Language detection reinforces the extractor
- A **deterministic, zero-dependency language detector** (Unicode-script +
  stop-word voting, stdlib only) now names the message's language explicitly in
  the extraction prompt — so even a short or ambiguous sentence is pinned to the
  right language instead of drifting to English. When detection isn't confident
  it stays silent and the LLM's own "preserve the language" instruction (0.3.5)
  takes over. Covers Latin-script (pt/en/es/fr/de/it…) and non-Latin scripts
  (Japanese, Chinese, Korean, Russian, Arabic, Hindi, Hebrew, Greek, Thai).

## [0.3.5] — 2026-06-11

### Fixed — memory now speaks the user's language
- **Extraction kept its language**: the LLM extractor and the four sleep-time
  generators (inference, user-model derivation, insight synthesis, peer cards)
  normalized everything to English. They now write `content`/`category` and all
  generated strings in the **same language as the source** — a Portuguese
  conversation produces Portuguese facts, German produces German, etc. The
  `dimension` id stays a fixed key (the dashboard already localizes it to all
  15 UI languages).

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
