# Command-Line Interface

The `logica-mind` command lets you store, retrieve, and consolidate memories, launch the dashboard, run as an MCP server, and wire up automatic session capture — all from your terminal.

Every subcommand works fully offline with zero configuration: the default store is local SQLite and the default embedder is a deterministic hashing embedder, so nothing leaves your machine and no API key is required. Set `VOYAGE_API_KEY` or `OPENAI_API_KEY` to upgrade recall quality (see [Embeddings and reranking](./embeddings-and-reranking.md)).

```bash
logica-mind --help
```

## Installation check

The command is installed as a console script with the package:

```bash
pip install logica-mind
logica-mind stats
```

If the `logica-mind` script is not on your `PATH`, the same CLI is available as a module:

```bash
python -m logica_mind stats
```

See [Installation](./installation.md) for details.

## Global options

These options apply to most subcommands and are passed **before** the subcommand name.

| Option | Default | Description |
| --- | --- | --- |
| `--db PATH` | the shared store under `~/.logica-mind` | Path to the SQLite database file to use. |
| `--namespace NS` | derived from the current directory | The memory namespace to read from and write to. |

```bash
logica-mind --db ./acme.db --namespace research recall "deployment process"
```

By default the CLI points at the **same** store, embedder, and namespace that the session hooks capture into, so `recall`, `stats`, `ui`, and `mcp` see whatever was automatically captured. The default database lives at `~/.logica-mind/memory-<fingerprint>.db`, where the fingerprint matches the active embedder (for example `memory-hashing-256.db` in the offline default). The default namespace is derived from your current working directory (the project root, when one is detected). Pass `--db` and/or `--namespace` to override either of these.

> The `hook` and `install-hooks` subcommands manage their own store and namespace per the host's working directory. `--db` and `--namespace` still override them when provided.

## Subcommands

### `ui` — launch the web dashboard

Starts the self-hosted dashboard and (by default) opens it in your browser.

| Flag | Default | Description |
| --- | --- | --- |
| `--host HOST` | `127.0.0.1` | Interface to bind. |
| `--port PORT` | `8420` | Port to listen on. |
| `--no-open` | off | Do not open the browser automatically. |

```bash
# open the dashboard on the default http://127.0.0.1:8420
logica-mind ui

# bind a custom port and skip auto-opening the browser
logica-mind ui --port 9000 --no-open
```

The dashboard is a blocking process; press `Ctrl+C` to stop it.

### `remember` — store a fact

Stores a durable fact or note. The text is run through extraction and de-duplication, then persisted into the semantic layer. It prints each memory that was created.

```bash
logica-mind remember "Maya prefers dark mode in the dashboard."
```

```text
stored 1 memory:
  · [semantic] Maya prefers dark mode in the dashboard.
```

Use `--namespace` to write into a specific agent's memory:

```bash
logica-mind --namespace support remember "Acme Inc is on the enterprise plan."
```

### `recall` — retrieve memories

Retrieves the most relevant memories for a query and prints each result with its score and layer.

| Flag | Default | Description |
| --- | --- | --- |
| `--limit N` | `8` | Maximum number of results to return. |

```bash
logica-mind recall "what does Maya prefer?" --limit 5
```

```text
0.489  [semantic]  Maya prefers dark mode in the dashboard.
```

> Scores depend on the active embedder. The offline hashing embedder produces lower absolute scores than a managed provider like Voyage or OpenAI; what matters is the relative ranking.

### `dream` — run a consolidation cycle

Runs a sleep-time consolidation cycle: distills raw episodic activity into semantic facts, reinforces what matters, and prunes stale entries. It prints the resulting report as a dictionary.

```bash
logica-mind dream
```

```text
💤 dreaming…
{'episodic_processed': 12, 'distilled': 3, 'graph_edges': 0, 'reinforced': 2, 'forgotten': 1, 'derived': 0, 'inferred': 0, 'user_synthesized': False, 'timestamp': '2026-06-04T18:00:00Z', 'namespace': 'research-1a2b3c4d'}
```

See [Dreaming](./dreaming.md) for what each field means.

### `stats` — show per-layer counts

Prints how many memories exist in each layer of the active namespace, plus a total.

```bash
logica-mind stats
```

```text
     total: 21
  episodic: 8
  semantic: 11
     graph: 1
      user: 1
```

### `mcp` — run as an MCP server over stdio

Runs Logica Mind as a [Model Context Protocol](./mcp.md) server, speaking JSON-RPC over standard input and output. This is the entry point you register with an MCP-capable host so it can call memory tools directly.

```bash
logica-mind mcp
```

Point it at a specific store and namespace just like any other command:

```bash
logica-mind --db ./acme.db --namespace research mcp
```

### `demo` — load a fictional demo dataset

Populates the store with a rich, fully fictional dataset spanning several agents (`research`, `marketing`, `engineering`, `finance`, `product`, `support`) and several weeks of activity — useful for exploring the dashboard and recall behavior. Everything is tagged so it can be cleanly removed later.

| Flag | Default | Description |
| --- | --- | --- |
| `--clear` | off | Remove the demo data instead of loading it. |
| `--serve` | off | Open the dashboard after loading. |

```bash
# load the demo dataset
logica-mind demo

# load it and open the dashboard immediately
logica-mind demo --serve

# remove all demo data afterwards
logica-mind demo --clear
```

```text
🌱 loaded 159 fictional demo memories across 6 agents
   clear anytime with:  logica-mind demo --clear
```

### `hook` — run a session hook

Runs a single session hook. It reads the host's JSON event on standard input and prints the host's hook output (when there is any) on standard output. You normally do **not** run this by hand — your editor or agent host invokes it on lifecycle events after you run `install-hooks`.

The `event` argument is one of:

| Event | When the host fires it |
| --- | --- |
| `sessionstart` | A session starts — injects a brief of what is known so far. |
| `userpromptsubmit` | You submit a prompt — captures it and injects relevant memory. |
| `stop` | The assistant finishes a turn — captures what it did. |
| `precompact` | Before the context window is compacted — consolidates first. |

```bash
# how a host calls it (event JSON arrives on stdin)
echo '{"prompt": "deploy the app", "cwd": "/path/to/project"}' | logica-mind hook userpromptsubmit
```

Hooks never raise and never write anything but their final JSON to stdout, so a memory hiccup can't break your session. See [Session hooks](./hooks.md) for the full lifecycle.

### `install-hooks` — install session hooks

Merges the session hooks (`SessionStart`, `UserPromptSubmit`, `Stop`, `PreCompact`) into a host `settings.json`. The merge is idempotent — running it twice changes nothing — and it refuses to overwrite a file that already contains invalid JSON.

| Flag | Default | Description |
| --- | --- | --- |
| `--settings PATH` | `~/.claude/settings.json` | Target `settings.json` to merge the hooks into. |

```bash
# install into the default location
logica-mind install-hooks

# install into a specific settings file
logica-mind install-hooks --settings ./my-host/settings.json
```

```text
hooks installed in /Users/maya/.claude/settings.json
added: SessionStart, UserPromptSubmit, Stop, PreCompact
```

If a hook is already present, it is reported as `(already present)` and the file is left untouched. See [Session hooks](./hooks.md) for how automatic capture works end to end.

## See also

- [Installation](./installation.md) — installing the package and the `logica-mind` command
- [Quickstart](./quickstart.md) — the same ideas from Python
- [Session hooks](./hooks.md) — automatic capture and injection for agent hosts
- [MCP server](./mcp.md) — exposing memory as MCP tools
- [Dreaming](./dreaming.md) — what a consolidation cycle does
- [Stores](./stores.md) — choosing and configuring a backend
- [Embeddings and reranking](./embeddings-and-reranking.md) — upgrading recall quality
- [Concepts](./concepts.md) — namespaces, layers, and the memory model
