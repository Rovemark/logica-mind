# Sessions and run records

Group related memories under a session, and capture a whole multi-participant run as one structured, framework-agnostic record.

A **session** is just a label you attach to memories so they hang together — one
conversation, one task, one job. You scope a memory to a session by passing
`session=` to `remember()`, `log()`, or `recall()`. On top of that, Logica Mind
has a richer concept: a **session record**, written with `record_session()`,
which captures "a run happened, here's who took part, what they did, and how it
went" as a single first-class memory plus one linked memory per contribution.

Everything on this page works offline with zero keys — the default SQLite store
and built-in hashing embedder are all you need.

## Scoping memories to a session

Every write and read verb accepts an optional `session=` string. When set, it is
stored on the memory's metadata as `metadata["session"]`, and it can be filtered
on at recall time.

```python
from logica_mind import LogicaMind

mind = LogicaMind(namespace="support")     # SQLite + offline embedder, no keys

# log a few turns under one session id
mind.log("Customer reported a failing checkout.", role="user", session="ticket-4821")
mind.log("Walked them through clearing the cart.", role="agent", session="ticket-4821")

# a durable fact, also scoped to the same session
mind.remember("The customer is on the Acme Pro plan.", session="ticket-4821")
```

The session id is yours to choose — a ticket number, a conversation id, a run id.
Anything that groups related memories.

### Recalling within a session

Pass the same `session=` to `recall()` to retrieve only memories from that
session:

```python
for hit in mind.recall("what happened with checkout?", session="ticket-4821"):
    print(f"{hit.score:.3f}  {hit.memory.content}")
```

A few useful behaviors to know:

- **Dedup is session-scoped.** When you `remember()` with a `session=`,
  deduplication only looks within that session — so the *same* fact stored under a
  different session is still kept. Session-less memories dedup globally.
- **`recall()` won't silently contradict itself.** If you pass both `session=` and
  a `metadata_filter={"session": ...}` that disagree, `recall()` raises a
  `ValueError` instead of quietly picking one. Use one or the other.
- **`session=` is optional everywhere.** Leave it off and memories are global to
  the namespace, exactly as in the [quickstart](./quickstart.md).

You can also scope a whole conversation in one call with `ingest_conversation()`,
which logs each turn (and, with an LLM, extracts durable facts) under a shared
session:

```python
mind.ingest_conversation(
    [
        {"role": "user", "content": "Checkout fails on the last step."},
        {"role": "agent", "content": "Let's clear the cart and retry."},
    ],
    session="ticket-4821",
)
# -> {"logged": 2, "facts": 0, "observations": 0}  (facts/observations need an LLM)
```

## Structured run records

`record_session()` records a rich, structured **session/run** as a first-class
memory. This is the generic version of "a multi-agent task ran and here's what
happened" — it makes **no assumption about your host system**. A *participant* is
anything that took part (a human, an agent, a tool, a model) with a free-form
`role`; *metrics* and *links* are open dicts, so any framework maps its own fields
onto them.

```python
from logica_mind import LogicaMind

mind = LogicaMind(namespace="product")

record = mind.record_session(
    title="Ship the onboarding redesign",
    participants=[
        {"name": "research", "role": "discovery",
         "contribution": "Mapped the drop-off points.", "metrics": {"score": 92}},
        {"name": "product", "role": "spec",
         "contribution": "Wrote the redesign spec.", "metrics": {"score": 96}},
        {"name": "engineering", "role": "build",
         "contribution": "Implemented the new flow."},
        {"name": "marketing", "role": "launch",
         "contribution": "Drafted the announcement."},
    ],
    status="completed",
    metrics={"tokens": 18420, "cost_usd": 0.14, "score": 94},
    links={"sprint": "2026-Q2-S3"},
)

print(record.metadata["session"])   # e.g. "sess_9f3c0b1a4d22"
```

### Parameters

`record_session()` takes the following arguments:

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `title` | `str` | *(required)* | One-line title for the run. Also the record's heading and its default display name. |
| `session_id` | `str \| None` | `None` | Session id to group under. If omitted, an id like `sess_<12-hex>` is generated. |
| `participants` | `list[dict]` | `None` | Who took part (see below). |
| `status` | `str` | `"completed"` | Free-form run status, e.g. `"completed"`, `"running"`, `"failed"`. |
| `metrics` | `dict` | `None` | Open dict of run-level metrics (tokens, cost, score…). |
| `links` | `dict[str, str]` | `None` | Open dict of named links/references. |
| `tags` | `list[str]` | `None` | Extra tags. The record always also gets the `session-record` tag. |
| `summary` | `str \| None` | `None` | Optional prose summary, shown under the heading. |
| `store_contributions` | `bool` | `True` | Whether each participant's `contribution` becomes its own linked memory. |
| `importance` | `float` | `0.7` | Fact-rating for the record memory. |

Each entry in `participants` is a plain dict. The recognized keys are:

| Key | Type | Meaning |
|---|---|---|
| `name` | `str` | The participant's name. |
| `role` | `str` | Free-form role (e.g. `"analyst"`, `"engineer"`, `"reviewer"`). |
| `contribution` | `str` | What they produced. Becomes a linked memory when `store_contributions=True`. |
| `metrics` | `dict` | Per-participant metrics, surfaced in the record and the dashboard. |

### What gets stored

`record_session()` returns the **record** `Memory` and writes:

1. **One session-record memory** — an episodic memory whose content is a readable
   Markdown body (heading, status, metrics, a participants list, and links) and
   whose metadata carries the structured fields: `session`, `record: True`,
   `title`, `status`, `participants`, `metrics`, and `links`. It is tagged
   `session-record`.
2. **One memory per contribution** (when `store_contributions=True`) — each
   non-empty `contribution` becomes its own episodic memory tagged
   `contribution`, sharing the same `session` id and linked back to the record via
   `metadata["of_record"]`, plus `participant` and `role`.

Because the record and all its contributions share one `session` id, the
dashboard's Sessions view groups them automatically and treats the record as the
header.

### Reading a record back

`session_record(session_id)` returns the structured header for a session — its
record metadata paired with its contributions — or `None` if that session has no
record.

```python
data = mind.session_record(record.metadata["session"])

print(data["metadata"]["title"])          # "Ship the onboarding redesign"
print(data["metadata"]["status"])         # "completed"
print(data["metadata"]["metrics"])        # {"tokens": 18420, "cost_usd": 0.14, "score": 94}
for c in data["contributions"]:
    print(" -", c["content"])             # each participant's contribution
```

If the same explicit `session_id` is reused for two records, the **newest** record
wins — chosen deterministically by `created_at`, so the result is stable across
SQLite, in-memory, and other backends.

## How the dashboard groups sessions

Launch the built-in dashboard and open the **Sessions** view:

```python
mind.serve()        # -> http://127.0.0.1:8420
```

The Sessions view lists every distinct session it finds (any memory with a
`session` in its metadata), with a per-session memory count, time span, source,
and namespace. Selecting a session shows its memories; if the session has a
structured record, a rich header renders the title, status, metrics, participants
(with roles and per-participant metrics), and links — exactly the fields you
passed to `record_session()`.

### Auto-naming

A session is given a display name automatically, in this order of preference:

1. A name you set yourself (see [Renaming](#renaming) below).
2. The **record title**, if the session has a structured record.
3. Otherwise, the **first message** in the session — its earliest content,
   trimmed to ~60 characters (a leading `User:` / `Human:` / `You:` prefix is
   stripped). If there's nothing to name it from, the start of the session id is
   used.

This means a session you only `log()` into is named after its opening turn, while
a session you `record_session()` into is named after its title — no manual step
required.

### Renaming

In the Sessions view, the selected session has a pencil icon. Click it, type a new
name, and confirm. The name is capped at 80 characters and persists across
restarts.

Under the hood the dashboard stores names in a small JSON sidecar next to your
SQLite database — `<db-name>_session_names.json` — so renaming requires a file-
backed store (it's a no-op for an in-memory store). The name lives alongside your
data, never inside the memories themselves, so renaming never rewrites a memory.

### Export

In the session detail pane, the download icon exports the selected session as a
JSON file named `session-<id>.json`. The file contains the session summary and
every memory in it:

```json
{
  "session": { "id": "ticket-4821", "namespace": "support", "count": 3, "...": "..." },
  "memories": [ { "id": "...", "content": "...", "layer": "episodic", "...": "..." } ]
}
```

For a full namespace dump (not just one session), the dashboard's overview offers
a download backed by the `/api/export` endpoint, which returns every memory in the
namespace (or across all namespaces).

### Clearing

When you want to remove memories, the dashboard's danger-zone clear supports three
modes, all scoped to a namespace:

- **By layer** — delete just the `episodic`, `semantic`, `graph`, or `user` layer.
- **By age** — delete memories older than N days (`older_than_days`).
- **Full reset** — purge the whole namespace.

From Python, a full namespace reset is one call:

```python
mind.purge()        # delete every memory in this namespace — a hard reset
```

There is no separate "delete one session" button; to clear a single session,
recall or list its memories and delete them by id, or use a namespace-scoped clear
if a session has its own namespace.

> **Tip:** if you loaded the fictional demo dataset (`logica-mind demo`), it
> includes a complete structured session record for *Acme Inc* so you can see the
> Sessions view populated immediately. Clear it any time with
> `logica-mind demo --clear` — only demo rows are removed, your own data stays
> intact.

## When to use which

- Use **`log(..., session=...)`** for raw turns/events you want to keep verbatim
  and group together.
- Use **`remember(..., session=...)`** for durable facts that belong to a specific
  session but should still be deduplicated within it.
- Use **`record_session(...)`** once a run is done, to capture its outcome —
  participants, roles, contributions, metrics, and links — as a single structured,
  framework-agnostic record that the dashboard surfaces as a session header.

## See also

- [Quickstart](./quickstart.md) — `remember`, `log`, `recall`, and the offline defaults.
- [Stores](./stores.md) — where sessions and the session-name sidecar are persisted (SQLite by default).
- [Core concepts](./concepts.md) — the memory layers and how `session=` filtering fits into recall.
- [The dashboard](./dashboard.md) — the Sessions view and the rest of the self-hosted UI.
- [API reference](./api-reference.md) — the full signatures of `remember`, `log`, `recall`, and `record_session`.
