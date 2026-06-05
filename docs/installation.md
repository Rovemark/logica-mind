# Installation

Install Logica Mind in one command — the core runs fully offline with zero third-party dependencies, and optional extras light up cloud embeddings and external stores when you want them.

## Requirements

- **Python 3.10 or newer** (3.10, 3.11 and 3.12 are tested).
- That's it. The core has **no third-party dependencies** — it uses only the Python standard library, with SQLite for storage and a built-in hashing embedder for retrieval. No API keys, no network, no database server.

## Install the core (offline, zero-key)

```bash
pip install logica-mind
```

This gives you everything you need to start: episodic, semantic, temporal-graph and user memory, the CLI, and the prebuilt web dashboard. By default a `LogicaMind` instance uses a local SQLite store and the offline `HashingEmbedder`, so it works the moment it's installed:

```python
from logica_mind import LogicaMind

mind = LogicaMind(namespace="my-app")          # SQLite + offline embedder, no keys
mind.remember("The user prefers dark mode and concise answers.")

for hit in mind.recall("what does the user like?"):
    print(f"{hit.score:.2f}  {hit.memory.content}")
```

The hashing embedder is *lexical* (it matches on shared words and subwords), not deep-semantic. It's deterministic and needs no setup, which makes it perfect for tests, demos and getting started. When you want true semantic similarity, install one of the embedding extras below and pass the embedder in — nothing else changes.

## Optional extras

Extras are installed with the familiar `pip install "logica-mind[extra]"` syntax. Each one is lazily imported, so installing an extra adds a capability but never changes the offline defaults. Quote the package spec (the brackets are shell metacharacters in zsh and some shells).

| Extra | Install | Pulls in | What it unlocks |
|-------|---------|----------|-----------------|
| `voyage` | `pip install "logica-mind[voyage]"` | `voyageai>=0.2` | The `VoyageEmbedder` — high-quality cloud embeddings with query/document `input_type`, Matryoshka `output_dimension` and contextualized embeddings. Needs a `VOYAGE_API_KEY`. |
| `openai` | `pip install "logica-mind[openai]"` | `openai>=1.0` | The `OpenAIEmbedder` — cloud embeddings (e.g. `text-embedding-3-small`) with an optional `dimensions` parameter. Needs an `OPENAI_API_KEY`. |
| `local` | `pip install "logica-mind[local]"` | `sentence-transformers>=2.2` | The `LocalEmbedder` — real semantic embeddings that run on-device with **no API key and no network** (default model `all-MiniLM-L6-v2`, 384 dims). |
| `postgres` | `pip install "logica-mind[postgres]"` | `psycopg[binary]>=3.1` | The `PostgresStore` — a self-hosted SQL backend with the same interface as the SQLite store. |
| `redis` | `pip install "logica-mind[redis]"` | `redis>=5.0` | The `RedisStore` — a fast in-memory backend, best for small working sets. Reads `REDIS_URL` (defaults to `redis://localhost:6379/0`). |
| `all` | `pip install "logica-mind[all]"` | all of the above | Voyage + OpenAI + local + Postgres + Redis in one install. |

A few things worth knowing:

- **Offline by default, always.** Even after installing an extra, a plain `LogicaMind()` still uses SQLite + the hashing embedder. You opt in by passing the new embedder or store explicitly. See [Embeddings](./embeddings-and-reranking.md) and [Stores](./stores.md) for how to wire them up.
- **The Supabase store needs no extra.** `SupabaseStore` talks to PostgREST over the standard-library `urllib`, so it works on the core install (set `SUPABASE_URL` and `SUPABASE_SERVICE_KEY`).
- **Helpful error messages.** If you reach for an embedder or store whose package isn't installed, Logica Mind raises a clear message telling you exactly which extra to install — for example, `pip install 'logica-mind[voyage]'`.

## Verify the install

Confirm the package imports and check the version:

```bash
python -c "import logica_mind; print(logica_mind.__version__)"
# 0.1.0
```

Confirm the CLI is on your `PATH`:

```bash
logica-mind --help
```

You should see the available subcommands, which include:

- `ui` — launch the web dashboard
- `remember` — store a fact
- `recall` — retrieve memories
- `dream` — run a consolidation cycle
- `stats` — show per-layer counts
- `mcp` — run as a Model Context Protocol server over stdio
- `demo` — load (or clear) a fictional demo dataset

A quick end-to-end smoke test from the terminal:

```bash
logica-mind remember "Acme Inc ships its v2 API in Q3."
logica-mind recall "when does the new API ship?"
logica-mind stats
```

> If the `logica-mind` console script isn't on your `PATH` (some isolated environments), the same CLI is available as a module: `python -m logica_mind --help`.

Want a fully populated example to explore? `logica-mind demo` seeds a fictional dataset across several agents so you can try every feature instantly, and `logica-mind demo --clear` removes it again. See the [CLI reference](./cli.md) for the full command list.

## The dashboard ships prebuilt

Logica Mind includes a self-hosted web dashboard, and **you do not need Node.js to use it**. The published wheel ships the *built* dashboard assets (the Vite dev sources and `node_modules` are excluded from the package), and the dashboard server itself is standard-library only. Just run:

```bash
logica-mind ui            # serve the dashboard at http://127.0.0.1:8420
```

or from Python:

```python
mind.serve()              # -> http://127.0.0.1:8420
```

Node is only needed if you want to *rebuild the UI from source* during development — never to install or run it. See [The dashboard](./dashboard.md) for a tour.

## Install from source

For development (or to run the test suite), clone the repo and install in editable mode with the `dev` extra:

```bash
git clone https://github.com/Rovemark/logica-mind.git
cd logica-mind
pip install -e ".[dev]"   # adds pytest
pytest -q                 # runs the test suite, fully offline
```

## See also

- [Quickstart](./quickstart.md) — store and recall your first memories in 30 seconds.
- [Embeddings](./embeddings-and-reranking.md) — the offline hashing default and the Voyage, OpenAI and local embedders.
- [Stores](./stores.md) — SQLite, Postgres, Redis, Supabase and more.
- [CLI reference](./cli.md) — every `logica-mind` subcommand.
- [The dashboard](./dashboard.md) — the prebuilt web UI for browsing memory.
