# MCP server

Run Logica Mind as a Model Context Protocol (MCP) server so any MCP client — Claude Code, Cursor, Windsurf — can use it as durable, queryable memory.

Logica Mind ships a full MCP server that exposes its memory verbs as **27 tools**. It speaks JSON-RPC 2.0 over stdio (newline-delimited) using only the Python standard library — no extra dependencies, no network service. Point an MCP client at it and your assistant gets long-term memory, a temporal knowledge graph, peer modeling, sleep-time consolidation and structured run history.

Like the rest of the library, the default setup is offline and zero-key: a SQLite store plus the built-in hashing embedder, no API keys required. See [Installation](./installation.md) for the dependency-free install.

## Running the server

Start the server over stdio with the `mcp` subcommand:

```bash
logica-mind mcp
```

The server reads JSON-RPC requests on stdin and writes responses on stdout, one JSON object per line. You normally don't run this by hand — an MCP client launches it for you (see [Wiring it into a client](#wiring-it-into-a-client)).

The global `--db` and `--namespace` flags select which store and namespace the tools read and write. They come *before* the subcommand:

```bash
logica-mind --db mind.db --namespace research mcp
```

- `--db` — path to the SQLite database. Defaults to the shared hook store under `~/.logica-mind`.
- `--namespace` — the memory namespace. Defaults to one derived from the current directory.

With no flags, the server uses the same store and namespace the session hooks capture into, so tools like `lm_recall` and `lm_stats` see whatever was auto-captured. See [Stores](./stores.md) for how persistence works.

> Diagnostics from the library (embedder/graph chatter) are redirected to stderr, so they never pollute the JSON-RPC stream on stdout.

## Wiring it into a client

Most MCP clients take a small JSON block that tells them how to launch the server. Add an entry under `mcpServers` with the command and its arguments.

### Claude Code

```json
{
  "mcpServers": {
    "logica-mind": {
      "command": "logica-mind",
      "args": ["mcp"]
    }
  }
}
```

### Cursor

Cursor uses the same shape. To pin a specific database and namespace, pass them as arguments before `mcp`:

```json
{
  "mcpServers": {
    "logica-mind": {
      "command": "logica-mind",
      "args": ["--db", "mind.db", "--namespace", "research", "mcp"]
    }
  }
}
```

After the client connects, the 27 tools below appear in its tool list. Both clients speak protocol version `2024-11-05`, which the server supports; if a client requests a version the server doesn't implement, the server advertises its own latest version and lets the client decide.

## Source attribution

Every memory captured through the MCP server is tagged with the client that produced it, so you can later audit *what* wrote *what*.

The server learns the client name from the standard MCP `initialize` handshake: any spec-compliant client sends `clientInfo.name` automatically (for example `claude-code`, `cursor`, `windsurf`). The server records that name and stamps it as the `source` on captured memories. Tools that write memory — `lm_remember` and `lm_ingest_conversation` — carry this attribution through.

If a client omits `clientInfo.name`, the source falls back to the generic `mcp`, so the capture is still marked as having come in over MCP. You can also force a source explicitly by setting the `LOGICA_MIND_SOURCE` environment variable, which takes precedence over the handshake value.

```json
{
  "mcpServers": {
    "logica-mind": {
      "command": "logica-mind",
      "args": ["mcp"],
      "env": { "LOGICA_MIND_SOURCE": "acme-app" }
    }
  }
}
```

## The 27 tools

All tools are namespaced with the `lm_` prefix. Required arguments are noted; everything else is optional with sensible defaults.

### Memory

Core store, recall and maintenance of long-term memory.

| Tool | Purpose |
|---|---|
| `lm_remember` | Store a durable fact/note in long-term memory. |
| `lm_recall` | Retrieve the most relevant memories for a query. |
| `lm_context` | Assemble a context block (user model + relevant memory) within a token budget. |
| `lm_ingest_conversation` | Ingest a full conversation: logs turns, extracts facts, derives user observations. |
| `lm_reflect` | Synthesize insights from recent memories (what changed / what's notable). |
| `lm_contradictions` | Facts whose object changed over time (a subject+predicate with more than one value in its history). |
| `lm_diff` | Memory changelog — what was learned within a time window `[since, until]`. |
| `lm_forget` | Delete memories by id or by semantic query. |
| `lm_forget_about` | GDPR-native erase: delete every memory mentioning a given entity across all layers and the graph. |
| `lm_stats` | Per-layer counts of stored memories. |

### User model & peers

The dialectic model of who the user is, plus directional theory-of-mind between peers. See [User model & peers](./user-model-and-peers.md).

| Tool | Purpose |
|---|---|
| `lm_ask_about_user` | Answer a question about the user, reasoning over the dialectic user model. |
| `lm_observe_user` | Record an observation about the user (feeds the dialectic user model). |
| `lm_observe_peer` | Record what one peer (observer) learned about another (observed) — directional theory-of-mind. |
| `lm_peer_card` | What `observer` knows/believes about `observed` (a directional profile). |
| `lm_peer_query` | Ask what `observer` would say about `observed` (theory-of-mind query). |

### Dreaming & moats

Sleep-time consolidation plus the epistemic features that surface uncertainty and change.

| Tool | Purpose |
|---|---|
| `lm_dream` | Run a sleep-time consolidation cycle: consolidate episodic→semantic, reinforce, prune stale, derive observations, infer links. |
| `lm_forget_curve` | Ebbinghaus forgetting curve: beliefs predicted to decay in the next 7 days, sorted most-at-risk first. |
| `lm_contested_beliefs` | Pairs of beliefs where both sides had high confidence when one superseded the other — epistemic contests. |
| `lm_surprise_events` | Paradigm shifts: beliefs that contradicted prior high-confidence beliefs with large divergence. |
| `lm_record_session` | Record a structured multi-agent/multi-step run as a rich, recallable memory (participants, metrics, status, links). |

See [Dreaming](./dreaming.md) for the consolidation cycle these tools build on.

### Devtools

A coding-context toolkit for assistants working inside a repository.

| Tool | Purpose |
|---|---|
| `lm_execute` | Run a command and return a token-saving summary (truncated output). |
| `lm_scan` | Project DNA — detect languages, frameworks, key files, structure. |
| `lm_git` | Git-aware status — branch, ahead/behind, staged files, recent commits, diff. |
| `lm_mcp` | List active MCP servers and estimate their context cost. |
| `lm_budget` | Render a context-budget meter from token counts. |

### Team

A shared knowledge base across machines or teammates.

| Tool | Purpose |
|---|---|
| `lm_team_push` | Push knowledge to the shared team knowledge base. |
| `lm_team_search` | Search the shared team knowledge base. |

> The team tools use the local `team` namespace by default. A shared, cross-machine team store activates only when `SUPABASE_URL` plus a service key are set **and** a production embedder is configured (`VOYAGE_API_KEY` or `OPENAI_API_KEY`). With the offline hashing embedder, the server refuses the shared store — to avoid mixing vector dimensions — and uses the local team namespace instead.

## Calling a tool

Tools follow the standard MCP `tools/call` shape. For example, to store a fact:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "lm_remember",
    "arguments": { "text": "Maya prefers email over phone calls." }
  }
}
```

The server replies with a text content block:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [{ "type": "text", "text": "{\"stored\": [...], \"count\": 1}" }],
    "isError": false
  }
}
```

Missing required arguments and tool failures come back as content with `isError: true` rather than as JSON-RPC errors, so a single bad call never breaks the session.

## See also

- [Installation](./installation.md) — the zero-key, offline-first install.
- [Quickstart](./quickstart.md) — the same memory verbs from Python.
- [Stores](./stores.md) — where the MCP tools persist memory (SQLite by default).
- [User model & peers](./user-model-and-peers.md) — the model behind the user and peer tools.
- [Dreaming](./dreaming.md) — the consolidation cycle behind `lm_dream`.
- [Knowledge graph](./knowledge-graph.md) — the temporal graph that contradictions and erase tools touch.
