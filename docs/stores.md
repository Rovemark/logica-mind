# Stores

A **store** is where memory lives — the storage backend behind your `LogicaMind` instance.

The store interface is deliberately small, so a backend can be a single SQLite file, a self-hosted SQL database, a markdown vault you can read by hand, a cloud REST API, or several of those at once. Every store implements the same `Store` contract (`add`, `search`, `get`, `delete`, `all`, `namespaces`, plus optional `count`, `timerange`, `delete_layers`, `touch`, `close`), so you can swap one for another without changing your application code.

The default is fully offline and zero-key: `LogicaMind` uses [`SQLiteStore`](#sqlitestore) (a single local file) with no external service and no API key required.

```python
from logica_mind import LogicaMind

# No store argument → SQLiteStore() under the hood. Offline, zero-key.
mind = LogicaMind(namespace="agent-a")
mind.remember("The user prefers concise answers.")
```

To use any other backend, construct it and pass it as `store=`:

```python
from logica_mind import LogicaMind
from logica_mind.stores import ObsidianStore

mind = LogicaMind(namespace="agent-a", store=ObsidianStore(vault="~/notes/memory"))
```

---

## At a glance

| Store | Persistent | External service | Extra install | Native vector search | Best for |
|---|---|---|---|---|---|
| [`SQLiteStore`](#sqlitestore) | Yes (file) | None | — | No (ranks in-process) | The default. Local apps, single machine, getting started. |
| [`InMemoryStore`](#inmemorystore) | No | None | — | No (ranks in-process) | Tests and ephemeral sessions. |
| [`ObsidianStore`](#obsidianstore) | Yes (`.md` files) | None | — | No (lexical only) | Human-readable audit trail / a markdown vault. |
| [`MultiStore`](#multistore) | Depends on children | Depends on children | — | Depends on children | Writing to several backends at once (e.g. SQLite + Obsidian). |
| [`SupabaseStore`](#supabasestore) | Yes (Postgres) | Supabase project | — (stdlib only) | Optional (pgvector RPC) | Shared / hosted deployments, larger datasets. |
| [`PostgresStore`](#postgresstore) | Yes (Postgres) | Postgres server | `logica-mind[postgres]` | No (ranks in-process) | Self-hosted SQL with the same interface as SQLite. |
| [`RedisStore`](#redisstore) | Yes (Redis) | Redis server | `logica-mind[redis]` | No (ranks in-process) | Small, fast working sets. |

> **Note on ranking.** Most stores fetch a batch of candidates and rank them *in-process*, using the shared helpers in `logica_mind.stores.base`: cosine similarity when an embedding is present, and a lexical (BM25 / Jaccard) fallback otherwise. This is why every store works whether or not you configure an embedder. The one backend that can push vector search into the database is `SupabaseStore` (via an optional RPC against pgvector).

All stores are importable from `logica_mind.stores`:

```python
from logica_mind.stores import (
    SQLiteStore, InMemoryStore, ObsidianStore, MultiStore,
    SupabaseStore, PostgresStore, RedisStore,
)
```

The three backends that need an optional dependency (`SupabaseStore`, `PostgresStore`, `RedisStore`) are imported lazily, so importing `logica_mind.stores` never fails just because `psycopg` or `redis` is not installed.

---

## SQLiteStore

The zero-dependency default — persistent, single-file, built on the standard-library `sqlite3` module.

Embeddings are stored as JSON and ranked in-process (cosine when a vector is present, lexical overlap otherwise), so it works with or without an embedder. For large or shared deployments, reach for [`SupabaseStore`](#supabasestore) instead.

```python
from logica_mind import LogicaMind
from logica_mind.stores import SQLiteStore

mind = LogicaMind(
    namespace="agent-a",
    store=SQLiteStore(path="./acme_memory.db"),
)
```

**Constructor**

```python
SQLiteStore(path: str = "logica_mind.db", max_candidates: int = 5000)
```

- `path` — the database file. Parent directories are created automatically. Use `":memory:"` for an in-process database that is not written to disk.
- `max_candidates` — the maximum number of recent rows pulled into a single ranking pass per namespace/layer.

The connection is opened with `check_same_thread=False` and guarded by an internal lock, and it enables WAL mode and a busy timeout — so multiple threads (and multiple processes opening the same file) can read and write safely.

---

## InMemoryStore

A non-persistent store that keeps everything in a Python dictionary. Nothing is written to disk, so it is ideal for unit tests and short-lived, ephemeral sessions.

```python
from logica_mind import LogicaMind
from logica_mind.stores import InMemoryStore

mind = LogicaMind(namespace="research", store=InMemoryStore())
mind.remember("Acme Inc was founded in 2019.")
print([h.memory.content for h in mind.recall("when was Acme founded?")])
```

**Constructor**

```python
InMemoryStore()
```

Takes no arguments. When the process exits, the data is gone.

---

## ObsidianStore

A markdown-vault backend: every memory becomes a human-readable `.md` file with YAML-style frontmatter, laid out as `<vault>/<namespace>/<layer>/<id>.md`.

This makes the store a great **audit trail** — you can open, read, and even edit memories in any editor or in [Obsidian](https://obsidian.md) itself, where the frontmatter shows up in the Properties panel. Search here is **lexical only** (the embedding is ignored), so for semantic recall pair it with a vector-capable store via [`MultiStore`](#multistore).

```python
from logica_mind import LogicaMind
from logica_mind.stores import ObsidianStore

mind = LogicaMind(
    namespace="support",
    store=ObsidianStore(vault="~/acme-memory-vault"),
)
mind.remember("Maya is on the enterprise plan.")
# → ~/acme-memory-vault/support/semantic/<id>.md
```

**Constructor**

```python
ObsidianStore(vault: str = "~/logica-mind-vault")
```

- `vault` — the root directory of the vault. `~` and relative paths are expanded to an absolute path, and the directory is created if it does not exist.

Files are organized one directory per layer (`episodic`, `semantic`, `graph`, `user`). The JSON `metadata:` frontmatter line is the round-trip source of truth; additional frontmatter keys are written purely for display when present.

---

## MultiStore

Write to several backends at once and merge on read. This is the "many warehouses" switch: turn on SQLite + Obsidian + Supabase together with a single object.

- **Writes** fan out to *every* child store. If one backend is down, the error is logged and the others still receive the write — a backend outage never silently loses data.
- **Reads** query each child, merge results by memory id, and keep the best score for each. The first store in the list acts as the primary for `get()`/`delete()` fast paths, but `delete()` is attempted on all children so nothing is orphaned.

```python
from logica_mind import LogicaMind
from logica_mind.stores import MultiStore, SQLiteStore, ObsidianStore

store = MultiStore([
    SQLiteStore(path="./acme_memory.db"),   # fast primary
    ObsidianStore(vault="~/acme-memory-vault"),  # human-readable mirror
])

mind = LogicaMind(namespace="agent-a", store=store)
```

**Constructor**

```python
MultiStore(stores: List[Store])
```

- `stores` — a non-empty list of `Store` instances. Passing an empty list raises `ValueError`.

A handy pattern is a fast vector-capable primary plus a lexical-only mirror like Obsidian: when an Obsidian lexical hit out-scores the vector store, `MultiStore` back-fills the winner's embedding from a sibling store so downstream re-rankers still see a vector.

---

## SupabaseStore

A backend that talks to a [Supabase](https://supabase.com) project over PostgREST, using only the Python standard library (`urllib`) — **no extra dependency to install.**

Memories live in a `logica_mind_memory` table. The schema ships with the library as [`migrations/supabase.sql`](../migrations/supabase.sql); apply it to your project before first use. By default the store fetches candidates by namespace/layer and ranks them in-process like the other backends. With `use_rpc=True` it can instead push vector search into Postgres via a pgvector RPC.

### Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `SUPABASE_URL` | Yes | Your project URL, e.g. `https://xxxx.supabase.co`. |
| `SUPABASE_SERVICE_KEY` | Yes* | Service-role key used for `apikey` / `Authorization`. |
| `SUPABASE_KEY` | Yes* | Fallback key, used if `SUPABASE_SERVICE_KEY` is not set. |

\* You must provide **either** `SUPABASE_SERVICE_KEY` or `SUPABASE_KEY` (or pass `key=` directly). If neither a URL nor a key is available, the constructor raises `RuntimeError`.

```bash
export SUPABASE_URL="https://xxxx.supabase.co"
export SUPABASE_SERVICE_KEY="your-service-role-key"
```

```python
from logica_mind import LogicaMind
from logica_mind.stores import SupabaseStore

# Reads SUPABASE_URL and SUPABASE_SERVICE_KEY from the environment.
mind = LogicaMind(namespace="agent-a", store=SupabaseStore())
```

Or pass credentials explicitly and enable the pgvector RPC:

```python
store = SupabaseStore(
    url="https://xxxx.supabase.co",
    key="your-service-role-key",
    use_rpc=True,                 # push vector search into Postgres (pgvector HNSW)
    rpc="search_logica_mind",     # RPC function name (this is the default)
)
mind = LogicaMind(namespace="agent-a", store=store)
```

**Constructor**

```python
SupabaseStore(
    url: Optional[str] = None,            # falls back to $SUPABASE_URL
    key: Optional[str] = None,            # falls back to $SUPABASE_SERVICE_KEY / $SUPABASE_KEY
    table: str = "logica_mind_memory",
    max_candidates: int = 2000,
    timeout: float = 15.0,
    use_rpc: bool = False,                # native pgvector RPC when True
    rpc: str = "search_logica_mind",
)
```

If an RPC search ever fails, the store automatically falls back to fetching candidates and ranking in-process, so a missing or misconfigured RPC degrades gracefully rather than breaking recall.

---

## PostgresStore

A self-hosted SQL backend with the same interface as `SQLiteStore`, backed directly by a Postgres server.

Embeddings are stored as `jsonb` and ranked in-process (consistent with the other stores). If you want native vector acceleration on Postgres, point [`SupabaseStore(use_rpc=True)`](#supabasestore) at a pgvector-enabled database instead.

**Install the optional dependency:**

```bash
pip install "logica-mind[postgres]"
```

### Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `POSTGRES_DSN` | Yes* | Connection string, e.g. `postgresql://user:pass@host:5432/dbname`. |

\* Used when you do not pass `dsn=` explicitly.

```bash
export POSTGRES_DSN="postgresql://acme:secret@localhost:5432/acme"
```

```python
from logica_mind import LogicaMind
from logica_mind.stores import PostgresStore

# Reads POSTGRES_DSN from the environment.
mind = LogicaMind(namespace="agent-a", store=PostgresStore())

# Or pass the DSN directly:
store = PostgresStore(dsn="postgresql://acme:secret@localhost:5432/acme")
```

**Constructor**

```python
PostgresStore(dsn: Optional[str] = None, max_candidates: int = 5000)
```

- `dsn` — Postgres connection string; falls back to `$POSTGRES_DSN`.
- `max_candidates` — maximum rows pulled per ranking pass.

The table (`logica_mind_memory`) and its indexes are created automatically on first connection. If `psycopg` is not installed, the constructor raises a `RuntimeError` telling you to run `pip install 'psycopg[binary]'`.

---

## RedisStore

A Redis-backed store: each memory is a JSON value at the key `lm:{namespace}:{id}`, with a per-namespace set indexing the ids and a global set tracking namespaces. Search loads a namespace and ranks in-process. Best for small, fast working sets — not large-scale vector search.

**Install the optional dependency:**

```bash
pip install "logica-mind[redis]"
```

### Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `REDIS_URL` | No | Connection URL; defaults to `redis://localhost:6379/0` when not set or passed. |

```bash
export REDIS_URL="redis://localhost:6379/0"
```

```python
from logica_mind import LogicaMind
from logica_mind.stores import RedisStore

# Defaults to redis://localhost:6379/0 if REDIS_URL is unset.
mind = LogicaMind(namespace="agent-a", store=RedisStore())

# Or configure the URL and key prefix explicitly:
store = RedisStore(url="redis://localhost:6379/1", prefix="acme")
```

**Constructor**

```python
RedisStore(url: Optional[str] = None, prefix: str = "lm")
```

- `url` — Redis connection URL; falls back to `$REDIS_URL`, then to `redis://localhost:6379/0`.
- `prefix` — key prefix for all stored values and index sets (default `"lm"`).

If the `redis` package is not installed, the constructor raises a `RuntimeError` telling you to run `pip install redis`.

---

## Choosing a store

- **Just starting, or a single-machine app?** Use the default `SQLiteStore` — nothing to install, nothing to configure, fully offline.
- **Writing tests or throwaway sessions?** Use `InMemoryStore`.
- **Want memories you can read and edit by hand?** Use `ObsidianStore`, ideally mirrored behind a faster store via `MultiStore`.
- **Sharing memory across machines or scaling up?** Use `SupabaseStore` (managed, optional pgvector) or `PostgresStore` (self-hosted SQL).
- **Need a fast, small working set?** Use `RedisStore`.
- **Want belt-and-suspenders durability or a hot mirror?** Wrap any combination in a `MultiStore`.

Because every backend honors the same `Store` contract, you can start on SQLite and move to Supabase or Postgres later without touching the rest of your code.

---

## See also

- [Quickstart](./quickstart.md) — get a `LogicaMind` running in a few lines.
- [Embeddings & providers](./embeddings-and-reranking.md) — the hashing default and how to plug in real embedders for semantic search.
- [Core API](./api-reference.md) — `remember`, `recall`, `forget`, and the other public verbs.
- [CLI](./cli.md) — the `logica-mind` command-line tool and dashboard.
