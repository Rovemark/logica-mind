# Dashboard

A self-hosted web dashboard for browsing, searching, and curating everything in your memory store — across every namespace, with zero external dependencies.

The dashboard is a single-page app served by Python's standard-library `http.server`, backed by a live `LogicaMind` instance and its store. There is nothing to deploy and no cloud account to create: it reads the same SQLite file your app writes to, so by default (SQLite store + hashing embedder) it runs fully offline and zero-key.

![Overview](./img/overview-home.png)

## Running it

The dashboard is store-wide: it aggregates across all agents/clones in the store (the `__all__` view) and lets you drill into any single namespace.

### From the CLI

```bash
logica-mind ui
```

This launches the board, prints the URL, and opens your browser. Useful flags:

```bash
logica-mind ui --host 127.0.0.1 --port 8420   # defaults shown
logica-mind ui --no-open                       # don't open a browser
logica-mind ui --db ./memory.db --namespace research
```

`--db` and `--namespace` select the store and the starting namespace; if you omit them, the CLI uses the same shared store the session hooks capture into.

### From Python

```python
from logica_mind import LogicaMind

mind = LogicaMind(namespace="research")   # SQLite + hashing embedder by default
mind.serve()                              # blocking; Ctrl+C to stop
```

`mind.serve()` accepts `host`, `port`, and `open_browser`:

```python
mind.serve(host="127.0.0.1", port=8420, open_browser=True)
```

The default bind is `127.0.0.1:8420`. On startup the server prints the URL and the number of namespaces it can see:

```
🧠 Logica Mind dashboard → http://127.0.0.1:8420  (3 namespaces)
   Ctrl+C to stop.
```

### Empty store? Load the demo

A fresh store has nothing to show. The first time you open the dashboard, a banner offers to load a fictional demo dataset so you can explore every view before you have your own data:

```bash
logica-mind demo            # load the fictional demo dataset
logica-mind demo --serve    # load it and open the dashboard
logica-mind demo --clear    # remove the demo data
```

See [Demo banner](#demo-banner) below for the in-app controls.

## The fourteen views

The sidebar exposes fourteen views. Each reads from the active namespace, or aggregates across all namespaces when you pick **All** (`__all__`).

| View | What it shows | Backing endpoint(s) |
| --- | --- | --- |
| **Overview** | Per-layer counts, a one-line reflection insight, and the most recent memories | `/api/stats`, `/api/reflect`, `/api/memories` |
| **Analytics** | Usage and reliability: memories over time, distribution by layer / source / agent, real request latency and error rate, and the typed Memory lake | `/api/analytics` |
| **Context block** | Smart context assembly — ranked candidates fitted to a token budget, the per-section token cost, and the prompt-ready block | `/api/context` |
| **Graph** | The interactive knowledge graph of entities and relations, with history and a point-in-time scrubber | `/api/graph`, `/api/timerange` |
| **Memories** | The raw memory list, filterable by layer, each row openable and deletable | `/api/memories`, `/api/forget` (delete) |
| **Calendar** | An Obsidian-style month heatmap of daily activity; pick a day to read its memories | `/api/calendar`, `/api/day` |
| **Sessions** | Distinct conversation/run sessions with counts, time spans, and structured records | `/api/sessions`, `/api/session`, `/api/sessions/rename` |
| **User** | The dialectic user-model profile, with a free-text "ask about this user" box | `/api/user`, `/api/ask_user` |
| **Peers** | Directional, multi-perspective beliefs — what one peer believes about another | `/api/peers`, `/api/peer_card` |
| **Observations** | Structural patterns over the graph: entities that recur together (co-occurrence) and the hubs everything connects to | `/api/observations` |
| **Changes** | A changelog of what was learned plus contradictions (values that changed over time, with the old value invalidated, not deleted) | `/api/diff`, `/api/contradictions` |
| **Insights** | A reflection, knowledge communities, and beliefs flagged to re-verify | `/api/reflect`, `/api/communities`, `/api/stale` |
| **Workspace** | "Project DNA" — scan any folder and read its languages, frameworks, and key files | `/api/scan` |
| **Dreams** | The dream journal (consolidation cycles), the forget curve, contested beliefs, and surprises | `/api/dreams`, `/api/forget_curve`, `/api/contested`, `/api/surprises` |

### Overview

The landing view. It pulls per-layer counts and a total from `/api/stats`, a one-sentence "what's notable" insight from `/api/reflect`, and the eight most recent memories from `/api/memories`. It is the fastest way to confirm the store has what you expect.

### Analytics

![Analytics](./img/dashboard-analytics.png)

Usage, activity and reliability in one place, all from `/api/analytics`: a stat strip (memories, agents, entities, relations, sessions, contradictions, average request latency, error rate), distribution charts (added-over-time, by layer, by source, by agent), and the **Memory lake** — a typed catalog of every namespace (`user` / `org` / `agent`), each row carrying its entity / fact / relation counts, an activity sparkline, and a governance footer (provenance-tracked, source-attributed, versioned, erasable on request). Latency and error rate are measured by the server itself, not estimated.

### Context block

![Context block](./img/dashboard-context.png)

Smart context assembly for a query. `/api/context` ranks candidate memories, then fits the most relevant into a token budget and returns both halves of the story: the ranked pool (with which candidates made the cut) and the assembled, prompt-ready block — split into sections (User, Relevant memory) each with its own token estimate, against a budget meter you control (600 / 1,200 / 2,000 / 4,000 tokens). This is the same assembly exposed by the `lm_context` MCP tool, made visible.

### Graph

![Graph](./img/dashboard-graph.png)

The interactive knowledge graph. Nodes are entities, links are relations. You can toggle history (to include superseded edges), colour by community, and open a time scrubber that re-fetches the graph as of a point in time (using the true min/max range from `/api/timerange`). Clicking a node opens an entity detail panel listing every memory that mentions it. See [Knowledge graph](./knowledge-graph.md).

### Memories

The raw list of stored memories, sorted newest-first and filterable by layer (episodic, semantic, graph, user). Internal bookkeeping rows (entity aliases) are hidden. Each row is openable for detail and can be deleted, which calls `/api/forget` and updates the sidebar counts.

### Calendar

A month-grid heatmap where darker cells mean more activity that day, driven by per-day counts from `/api/calendar`. Selecting a day loads just that day's memories from `/api/day` in the pane beside the grid.

### Sessions

Lists distinct sessions discovered across memories — each with its message count, time span, dominant source, and (if present) a structured session record (title, status, participants, metrics, links). You can rename a session, and import session titles from local Claude Code session files via `/api/sessions/claude-import`.

### User

Renders the dialectic user-model profile for one namespace from `/api/user`. The "ask about this user" box sends a free-text question to `/api/ask_user` and shows the synthesized answer. Feed the model with `observe_user(…)`. See [User model and peers](./user-model-and-peers.md).

### Peers

Multi-perspective memory: pick a peer relationship and read the directional profile — what one peer believes about another — built from `/api/peers` (the relationship list) and `/api/peer_card` (the directional card).

### Observations

![Observations](./img/dashboard-observations.png)

Patterns that live across many facts, not inside any single one. `/api/observations` reads the temporal graph structurally and surfaces two kinds: **recurring pairs** (entities that keep landing in the same neighbourhood — co-occurrence) and **central entities** (the hubs everything else connects to, by degree). It recomputes as the graph grows, so the patterns track reality rather than being hand-authored.

### Changes

An audit of how beliefs evolved. It shows a changelog of what was learned within a time window (`/api/diff`) and a list of contradictions — facts whose value changed over time (`/api/contradictions`). When a value changes, the old one is **invalidated, not deleted**: the current belief is highlighted, and each superseded value stays listed with its validity window, so point-in-time history remains queryable.

### Insights

A reflection over recent memory (`/api/reflect`), the knowledge communities detected in the graph (`/api/communities`), and "beliefs to re-verify" — old, never-recalled, low-confidence items surfaced by `/api/stale`.

### Workspace

Project DNA. Point it at any folder and `/api/scan` reads the directory's structure, reporting detected languages, frameworks, and key files. Leave the path blank to scan the server's working directory.

### Dreams

The dream journal: a record of consolidation cycles loaded from `/api/dreams`, alongside the forget curve (`/api/forget_curve`), contested beliefs (`/api/contested`), and surprise events (`/api/surprises`). Run `mind.dream()` to produce new cycles. See [Dreaming](./dreaming.md).

## Search, composer, and settings

Beyond the fourteen views, the top bar and side panels add a few cross-cutting tools:

- **Recall search** — a ranked search box that queries `/api/recall` (one namespace) or recalls across all namespaces, blending semantic and lexical scoring.
- **Composer** — add a durable memory (`/api/remember`) or a user observation (`/api/observe_user`) directly from the UI.
- **Export** — download a namespace (or the whole store) as JSON via `/api/export`, or a portable signed bundle via `/api/bundle`.
- **Danger zone** — in Settings, clear memories by layer, by age, by staleness, or reset a namespace entirely (`/api/clear`).

## Themes and language

The dashboard ships with **dark** and **light** themes plus an **auto** mode that follows the operating system's colour-scheme preference. The choice is persisted in the browser and applied as a `data-theme` attribute; the default is dark.

The interface is translated into **15 languages** — English (`en`), Português (`pt`), Español (`es`), Français (`fr`), Deutsch (`de`), Italiano (`it`), Türkçe (`tr`), Bahasa Indonesia (`id`), Русский (`ru`), 한국어 (`ko`), 中文 (`zh`), 日本語 (`ja`), हिन्दी (`hi`), বাংলা (`bn`) and العربية (`ar`, right-to-left). Each is lazy-loaded as its own chunk. Arabic flips the whole layout to RTL, and even the graph's relationship labels are localized. On a first visit the UI auto-matches the browser language; missing keys fall back to English. The choice is remembered in the browser. Switch both theme and language from the **Settings** panel. See [Internationalization](./internationalization.md).

## Demo banner

The demo banner is how the dashboard handles an empty store and the demo dataset — nothing is ever seeded automatically.

- **Load** — when the store has no demo data, the banner offers to load a fictional demo dataset. This calls `POST /api/demo/seed`.
- **Keep** — once the demo is loaded, you can keep it; the banner goes quiet (the choice is remembered locally).
- **Clear** — or you can clear it. This calls `POST /api/demo/clear`, which removes only the demo-tagged rows — never anything you added yourself.

The banner checks the current demo state with `GET /api/demo`.

## Authentication and remote access

The dashboard is built to be safe on `localhost` with zero configuration, and explicit about what it takes to expose it beyond the loopback interface.

**Loopback is trusted.** Requests from `127.0.0.1` / `::1` are treated as authorized, so the local dashboard works out of the box with no token. The SPA shell and static assets are always served. The only anonymous `/api` reads are `/api/namespaces` and `/api/health` (counts only, no memory content).

**Remote requires a bearer token.** Any non-loopback caller must present a valid bearer token, set via the `LOGICA_MIND_TOKEN` environment variable:

```bash
export LOGICA_MIND_TOKEN="a-long-random-secret"
logica-mind ui --host 0.0.0.0 --port 8420
```

```http
Authorization: Bearer a-long-random-secret
```

Tokens are compared in constant time. Two guard rails protect remote binds:

- Write endpoints are enabled by default only on loopback. Binding to a non-loopback host **without** `LOGICA_MIND_TOKEN` set refuses to start with write endpoints exposed.
- When you bind to a non-loopback host without a token, the server warns that every `/api` read will return `401` — reads are auth-gated too, so a remote board needs the token to function.

> Tip: the dashboard speaks plain HTTP. To reach it over the network, prefer an SSH tunnel or a TLS-terminating reverse proxy in front of it, and always set `LOGICA_MIND_TOKEN`.

## See also

- [Quickstart](./quickstart.md) — get a store running in a few lines
- [Installation](./installation.md) — install the package and optional extras
- [Stores](./stores.md) — the SQLite store and other backends
- [Knowledge graph](./knowledge-graph.md) — the entities and relations behind the Graph view
- [User model and peers](./user-model-and-peers.md) — the data behind the User and Peers views
- [Dreaming](./dreaming.md) — the consolidation cycles behind the Dreams view
