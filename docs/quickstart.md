# Quickstart

Store a few facts, recall them with relevance scores, and open the live dashboard — all offline, with no API key.

This page walks through the smallest end-to-end loop in Logica Mind: create a
`LogicaMind`, `remember()` some durable facts, `log()` a conversational turn,
`recall()` with scores, inspect `stats()`, and open the built-in dashboard with
`serve()`. Everything here runs on the standard library alone — the default
store is SQLite and the default embedder is a deterministic hashing embedder, so
**you need zero dependencies and zero keys** to follow along.

## Install

```bash
pip install logica-mind
```

The core install pulls in no third-party packages. SQLite ships with Python, and
the hashing embedder is built in, so the example below works immediately on a
fresh machine.

> Want real embeddings later? `pip install "logica-mind[voyage]"` (or `[openai]`,
> `[all]`) lights up better providers without changing any of the code below.

## Your first memory

Create a `LogicaMind`. The only argument you need is a `namespace` — a label that
keeps one agent's, app's, or user's memories separate from another's. Everything
else has a sensible default: an on-disk SQLite store and the offline hashing
embedder.

```python
from logica_mind import LogicaMind

mind = LogicaMind(namespace="my-app")   # SQLite store + offline embedder, no keys
```

### Remember durable facts

`remember()` stores long-lived knowledge — preferences, settings, project state.
It runs extraction and deduplication automatically, so storing the same fact
twice won't create a duplicate. It returns a list of the `Memory` objects that
were actually created.

```python
mind.remember("The user prefers dark mode and concise answers.")
mind.remember("The user is based in Lisbon and works in fintech.")
mind.remember("The project deadline is the end of the quarter.")
```

Facts land in the **semantic** layer by default (durable, de-duplicated
knowledge). See [./layers.md](./concepts.md) for the four memory layers and when to
use each.

### Log a conversational turn

`log()` records a raw episodic event — a single turn or thing that happened. It
skips extraction and dedup, so it's a faithful, append-only record of the
conversation. Pass a `role` to tag who said it.

```python
mind.log("Asked about the billing integration today.", role="user")
```

## Recall with scores

`recall()` retrieves the most relevant memories for a query. It returns a list of
`SearchResult` objects, each with a `.score` (higher is more relevant) and the
underlying `.memory`. The score blends semantic similarity, importance, and
recency under the hood.

```python
print("Recall: 'what are the user's preferences?'")
for hit in mind.recall("what are the user's preferences?"):
    print(f"  {hit.score:.3f}  {hit.memory.content}")
```

Example output (the most relevant fact ranks first):

```text
Recall: 'what are the user's preferences?'
  0.524  The user prefers dark mode and concise answers.
  0.440  The user is based in Lisbon and works in fintech.
  0.362  The project deadline is the end of the quarter.
  0.330  Asked about the billing integration today.
```

Each `SearchResult` also carries a `.components` breakdown
(`similarity`, `importance`, `recency`) if you want to see why something ranked
where it did:

```python
top = mind.recall("preferences", limit=1)[0]
print(top.components)
# {'similarity': 0.2839, 'importance': 0.5, 'recency': 1.0}
```

By default `recall()` returns up to 8 results — pass `limit=` to change that. The
full search and ranking pipeline is documented in [./recall.md](./concepts.md).

> The offline hashing embedder gives lexically related text a positive score, so
> with a tiny dataset like this every memory can surface; the ranking still
> floats the best match to the top. Real embedding providers
> ([./embeddings.md](./embeddings-and-reranking.md)) sharpen the separation between relevant and
> irrelevant memories.

## Inspect what's stored

`stats()` returns a per-layer count of everything in the current namespace, plus
a `total`.

```python
print("Stats:", mind.stats())
# Stats: {'total': 4, 'episodic': 1, 'semantic': 3, 'graph': 0, 'user': 0}
```

## The whole thing, end to end

Putting it together — this is the complete, runnable
[`examples/quickstart.py`](https://github.com/Rovemark/logica-mind/blob/main/examples/quickstart.py):

```python
from logica_mind import LogicaMind

mind = LogicaMind(namespace="my-app")

# remember durable facts (extraction + dedup happen automatically)
mind.remember("The user prefers dark mode and concise answers.")
mind.remember("The user is based in Lisbon and works in fintech.")
mind.remember("The project deadline is the end of the quarter.")

# log a raw conversational turn (episodic, no extraction)
mind.log("Asked about the billing integration today.", role="user")

print("Recall: 'what are the user's preferences?'")
for hit in mind.recall("what are the user's preferences?"):
    print(f"  {hit.score:.3f}  {hit.memory.content}")

print("\nStats:", mind.stats())
```

Run it:

```bash
python examples/quickstart.py
```

Because the default SQLite store writes to a file (`logica_mind.db` in the
current directory), your memories persist between runs — run the script again and
the recall still works without re-storing anything.

## See it live: the dashboard

`serve()` launches the built-in, self-hosted dashboard so you can watch your
memory grow — a calendar heatmap, the knowledge graph, and per-layer views. It
binds to loopback and opens your browser by default. The call blocks until you
stop it with `Ctrl+C`.

```python
mind.serve()                        # -> http://127.0.0.1:8420
```

You can pick a different host/port, or skip auto-opening the browser:

```python
mind.serve(host="127.0.0.1", port=8420, open_browser=False)
```

On startup it prints the URL it's serving:

```text
🧠 Logica Mind dashboard → http://127.0.0.1:8420  (1 namespace)
   Ctrl+C to stop.
```

More on the dashboard and its panels in [./dashboard.md](./dashboard.md).

## Explore with the demo dataset

A brand-new memory is empty, which makes the dashboard hard to appreciate. Logica
Mind ships an optional, **100% fictional** demo dataset — a made-up company,
*Acme Inc*, with role-based agents (`research`, `marketing`, `engineering`,
`finance`, `product`, `support`), a founder (Maya Chen), a knowledge graph,
sessions, and a user model — so every feature is visible at once.

Load it from the command line:

```bash
logica-mind demo
```

```text
🌱 loaded 159 fictional demo memories across 6 agents
   clear anytime with:  logica-mind demo --clear
```

Load it and open the dashboard in one step:

```bash
logica-mind demo --serve
```

Or seed it from Python against the same `mind`:

```python
from logica_mind import LogicaMind, demo

mind = LogicaMind()
demo.seed(mind)     # populate with the fictional dataset
mind.serve()        # explore it in the dashboard
```

Every demo row is tagged, so cleanup is surgical: clearing the demo removes only
the demo data and never touches memories you added yourself.

```bash
logica-mind demo --clear
```

```text
🧹 removed 163 demo memories
```

Or from Python:

```python
demo.clear(mind)    # remove every demo row, your own data stays intact
```

> The CLI commands (`remember`, `recall`, `stats`, `ui`, `demo`, …) operate on a
> shared store under `~/.logica-mind` by default, with a namespace derived from
> the current directory. Pass `--db` and `--namespace` to point at a specific
> store — for example the `logica_mind.db` file created by the Python example
> above. See [./cli.md](./cli.md) for the full command reference.

## What's next

You now have the core loop: `remember`, `log`, `recall`, `stats`, `serve`. From
here:

- Understand the four memory layers in [./layers.md](./concepts.md).
- Tune retrieval and ranking in [./recall.md](./concepts.md).
- Swap SQLite for Postgres, Redis, or Supabase in [./stores.md](./stores.md).
- Plug in Voyage or OpenAI embeddings in [./embeddings.md](./embeddings-and-reranking.md).

## See also

- [Memory layers](./concepts.md) — episodic, semantic, graph, and user memory
- [Recall and ranking](./concepts.md) — how relevance is scored
- [Stores](./stores.md) — SQLite, Postgres, Redis, and more
- [Embeddings](./embeddings-and-reranking.md) — offline hashing vs. provider embeddings
- [The dashboard](./dashboard.md) — the self-hosted UI
- [CLI reference](./cli.md) — `logica-mind` commands
