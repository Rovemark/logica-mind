# Dreaming & the memory lifecycle

A sleep-time cycle that consolidates, reinforces, forgets, and infers — so your agent's memory ages and improves on its own, the way a brain does during sleep.

Most memory libraries treat storage as an immutable database: what goes in stays in, unchanged, forever. Logica Mind treats memory as something that *lives*. Run `mind.dream()` periodically (a cron job, an idle loop, or at the end of a session) and one cycle will distill recent raw turns into durable facts, raise the importance of memories that keep getting recalled, drop weak traces that nobody ever uses, derive new observations about the user, and — optionally — infer brand-new facts by connecting what it already knows.

Everything degrades gracefully. The default setup is offline and zero-key (a SQLite store plus the hashing embedder), and in that mode the LLM-only steps are simply skipped while the rest still run.

## The dream cycle

A single cycle runs these stages in order. Each one writes a counter into the `DreamReport` it returns.

| Stage | What it does | Needs an LLM? |
|-------|--------------|---------------|
| **Consolidate** | Distill un-consolidated episodic turns into durable, de-duplicated semantic facts | Yes |
| **Reinforce** | Raise the importance of memories that have been recalled | No |
| **Forget** | Decay and delete weak, stale, never-recalled episodic traces | No |
| **Derive** | Infer durable observations about the user from recent turns | Yes |
| **Infer** | Connect existing facts into new inferred facts (off by default) | Yes |
| **Synthesize user** | Reconcile observations into the dialectic user model | Yes |

Two layers are deliberately never hard-pruned: the temporal **graph** (deleting edges would destroy the point-in-time history) and the **user** model (deleting rows would wipe the evolving profile). Their lifecycle is governed elsewhere — edges close instead of being deleted, and the user model is reconciled by synthesis.

## Running a dream

```python
from logica_mind import LogicaMind

mind = LogicaMind(namespace="research-agent", store=...)  # SQLite by default

# log some raw activity over a session
mind.log("I keep my notes in Obsidian, not Notion.", role="user")
mind.log("Actually I switched everything to Obsidian last month.", role="user")

# run a consolidation cycle
report = mind.dream()
print(report.to_dict())
```

Offline (no LLM), a fresh run prints something like:

```python
{
    "episodic_processed": 0,
    "distilled": 0,
    "graph_edges": 0,
    "reinforced": 0,
    "forgotten": 0,
    "derived": 0,
    "inferred": 0,
    "user_synthesized": False,
    "timestamp": "2026-06-04T18:30:00Z",
    "namespace": "research-agent",
}
```

The same cycle from the command line:

```bash
logica-mind dream
```

### Tuning the cycle

`mind.dream(**kwargs)` forwards every keyword to the underlying `Dreamer`. The defaults are conservative; turn knobs on as needed.

```python
report = mind.dream(
    episodic_batch=40,     # max raw turns distilled per cycle
    reinforce=True,        # boost importance of recalled memories
    prune=True,            # decay/forget weak traces
    prune_floor=0.15,      # delete episodic memories whose strength falls below this
    synthesize_user=True,  # reconcile the user model
    derive_user=True,      # derive new user observations first
    infer_links=False,     # inductive inference (LLM only) — off by default
    extract_graph=False,   # grow the temporal graph from the same batch
)
```

`prune_layers` controls which layers decay. It defaults to `[MemoryLayer.EPISODIC]`. You can add `MemoryLayer.SEMANTIC` to let distilled facts decay too — but `GRAPH` and `USER` are filtered out automatically (with a warning) because pruning them would break temporal and user-model invariants.

## How recall feeds the cycle

Reinforce and forget both depend on usage, and usage is recorded by `recall()`. When `track_access=True` (the default), every memory returned by a recall is *touched*: its `access_count` goes up. The dream cycle reads that:

- **Reinforce** boosts importance by `min(0.30, access_count × 0.02)` for any memory with `access_count > 0`.
- **Forget** only deletes episodic traces with `access_count == 0` (never-recalled) whose strength has fallen below `prune_floor`.

So a memory the agent actually uses gets stronger; one nobody ever needs fades and eventually disappears. Memory that earns its keep, stays.

## The Ebbinghaus forgetting curve

Logica Mind models retention with the classic Ebbinghaus curve: knowledge decays exponentially unless it's recalled. `forget_curve()` lets you inspect — and optionally apply — that decay.

Retention is `R = exp(-t / halflife)`, where `t` is the time since a memory was last recalled (`last_recalled_at`) or, if never recalled, since it was created. A memory's effective *strength* is `importance × R`.

```python
# inspect: which beliefs will fade most over the next 7 days?
at_risk = mind.forget_curve(days_halflife=30, limit=10)
for b in at_risk:
    print(
        b["content"],
        "| retention:", b["current_retention"],
        "| 7d strength:", b["projected_strength_7d"],
        "| days since recall:", b["days_since_recall"],
    )
```

Each entry includes `id`, `content`, `current_retention`, `current_strength`, `projected_strength_7d`, `days_since_recall`, `importance`, and `layer`. Results are sorted by projected 7-day strength (weakest first).

To actually lower importance scores in place, pass `apply=True`:

```python
mind.forget_curve(days_halflife=30, apply=True)  # decayed beliefs lose importance
```

This scans the semantic and episodic layers. With `apply=True`, each memory's importance is reset to `max(0.05, importance × retention)` (so nothing drops fully to zero).

> The recency component used inside recall ranking uses the mind's own `half_life_days` (default `7.0`, set at construction). `forget_curve()` takes its own `days_halflife` argument so you can probe a different horizon without changing how recall ranks.

## The surprise score

When a new belief *replaces* an older one (an extraction `UPDATE`), Logica Mind records how much it contradicted what came before. The stronger and more divergent the old belief, the bigger the surprise:

```
surprise_score = old_importance × cosine_distance(old_vector, new_vector)
```

These are the paradigm shifts in your agent's worldview — the moments where it changed its mind. `surprise_events()` surfaces them, most surprising first:

```python
for e in mind.surprise_events(limit=10):
    print(e["surprise_score"], "→", e["content"])
```

You can scope to recent shifts with `since` (an ISO timestamp). High-surprise events are the most useful starting points when debugging why an agent's behavior changed.

## Contested beliefs

A `surprise_score` records a one-way replacement. A *contested belief* is sharper: a pair of beliefs that contradict each other **and** were both held with high confidence — an epistemic standoff where neither side can simply be dismissed.

```python
for c in mind.contested_beliefs(confidence_threshold=0.65):
    print("now:    ", c["current"]["content"],   "(", c["confidence_new"], ")")
    print("was:    ", c["superseded"]["content"], "(", c["confidence_old"], ")")
    print("surprise:", c["surprise_score"])
```

Each result pairs the `current` belief with the `superseded` one it replaced, along with `confidence_new`, `confidence_old`, and `surprise_score`. The superseded belief is read from a `superseded_belief` snapshot saved on the new memory when it was written (so the original content and confidence survive even though the old row was deleted). Results are sorted by surprise, highest first.

This is the system being honest: it admits, in plain view, that it once believed something else — and how sure it was.

## Epistemic self-doubt: stale beliefs

Beyond what it *holds*, Logica Mind can surface what it should probably *re-verify*. `stale_beliefs()` finds durable facts that are old, never recalled, and have decayed below confidence — the things an agent should treat as "I'm not so sure about this anymore."

```python
for s in mind.stale_beliefs(min_age_days=30, limit=10):
    print(s["content"], "| age:", s["age_days"], "days | confidence:", s["confidence"])
```

A belief is stale when it's at least `min_age_days` old **and** has an `access_count` of `0` (never recalled). Each entry reports `id`, `content`, `age_days`, and a decayed `confidence` (`importance × recency`). Results are sorted by confidence, least-confident first — the beliefs most worth double-checking.

## Inductive link inference

Most "consolidation" only compresses what's already there. Inductive dreaming goes further: it *generates* new facts by connecting existing ones. If the graph knows `A → B` and `B → C`, the LLM can infer that `A` relates to `C`, and that inference is stored as a low-confidence `inferred` semantic memory.

It's off by default and requires an LLM. Enable it in a dream, or call it directly:

```python
# inside a dream
report = mind.dream(infer_links=True)
print("new inferred facts:", report.inferred)

# or standalone
n = mind.infer_links(max_new=5)
```

`infer_links()` returns the count of new inferences. It needs at least two graph edges to have anything to connect; offline it's a no-op and returns `0`. Inferred facts are stored at importance `0.4` and tagged `inferred`, so you can always tell a derived belief from one the user stated directly.

A related, lighter-weight introspection is `reflect()`, which summarizes "what changed / what's notable" from recent semantic memories. With an LLM it reasons; offline it returns the recent digest. It's not part of the automatic dream cycle — call it when you want a human-readable summary:

```python
print(mind.reflect(window=30))
```

## The dream journal

Every cycle is recorded so you can watch the memory think over time. `dream()` returns a `DreamReport` and also appends it to a sidecar **dream journal** file next to your SQLite database — for a store at `notes.db`, the journal is `notes_dream_journal.json`. The journal keeps the most recent 200 cycles.

In-memory stores (`:memory:`) have no file to write beside, so no journal is persisted for them — the `DreamReport` is still returned.

`DreamReport` fields:

| Field | Meaning |
|-------|---------|
| `episodic_processed` | Raw turns fed into consolidation |
| `distilled` | New semantic facts created |
| `graph_edges` | Graph edges added (when `extract_graph=True`) |
| `reinforced` | Memories whose importance was raised |
| `forgotten` | Weak traces deleted |
| `derived` | New user observations derived |
| `inferred` | New inferred facts (when `infer_links=True`) |
| `user_synthesized` | Whether the user model was reconciled |
| `timestamp` | When the cycle ran (ISO) |
| `namespace` | The namespace it ran in |

To read the journal back, use the helpers in `logica_mind.dreaming`:

```python
from logica_mind.dreaming import load_dreams

recent = load_dreams(mind.store, namespace=mind.namespace, limit=20)
for entry in recent:
    print(entry["timestamp"], "→ distilled", entry["distilled"],
          "| forgotten", entry["forgotten"], "| inferred", entry["inferred"])
```

`load_dreams()` returns the most recent cycles first (newest at the top), as plain dictionaries. The dashboard's **Dreams** view renders the same data alongside the forgetting curve and contested beliefs, so you can see the whole lifecycle visually.

## Where to run the cycle

`dream()` is cheap when there's nothing to do and safe to call often. Common patterns:

```python
# end of a session
mind.dream()

# nightly cron / idle loop, with inference enabled
mind.dream(infer_links=True, extract_graph=True)
```

```bash
# from a scheduler
logica-mind dream
```

Run it as often as makes sense for your app. The more an agent dreams, the more its memory sharpens around what matters and lets go of what doesn't.

## See also

- [Recall](./concepts.md) — how usage is tracked, which feeds reinforce and forget
- [The user model](./user-model-and-peers.md) — the dialectic profile that synthesis reconciles
- [The temporal graph](./knowledge-graph.md) — the edges that inductive inference connects
- [Stores](./stores.md) — where the dream journal sidecar lives (SQLite default, zero-key)
- [The dashboard](./dashboard.md) — the Dreams view: forgetting curve, contested beliefs, journal
