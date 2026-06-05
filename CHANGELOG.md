# Changelog

All notable changes to Logica Mind. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versions are date-stamped.

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
