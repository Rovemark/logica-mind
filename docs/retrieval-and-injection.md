# Retrieval profiles, injection safety & lifecycle controls

The pieces that govern *how memory reaches the model* and *how it ages* — added
across the 0.4.x line. All of them are zero-dependency and keep the keyless,
offline-first default intact; the heavier ones are opt-in.

## Performance profiles

`context()` (and the `lm_context` MCP tool) takes a `profile` that trades latency
for depth:

```python
mind.context(query, profile="speed")     # sub-second: skip the graph, small pool
mind.context(query, profile="balanced")  # default
mind.context(query, profile="deep")      # wider pool + 2-hop graph beam search
```

- **speed** — lexical/vector recall only, no graph hop. For latency-sensitive
  hooks that fire on every prompt.
- **balanced** — the default; 1-hop graph facts + a moderate memory pool.
- **deep** — a wider recall pool and a **bounded beam search** two hops out in the
  knowledge graph, so relational questions ("how does A connect to C?") reach
  facts the 1-hop expansion misses. The beam is bounded (beam width + total node
  budget), so cost stays predictable.

## Injection safety (hooks-first hardening)

When a hook injects memory into every prompt, stored memory becomes part of the
prompt — so a poisoned note ("ignore previous instructions…") could act as a
system directive. `context()` and `session_brief()` default to `safe=True`:

- **Instruction frame** — the block is wrapped in `<logica-memory>` with an
  explicit instruction that it's background knowledge, not commands; if it
  conflicts with the user, the user wins.
- **Sanitization** — invisible/bidi control characters are stripped, fake role
  markers (`system:`, ChatML tags) and frame-escape attempts are defanged, and
  the classic override phrasings are neutralized. Non-destructive: attack tokens
  are rewritten, legitimate content stays.
- **Retrieval gate** (in the hook) — trivial turns (greetings, "ok", shell
  commands, emoji) skip recall entirely; memory-referencing turns ("remember…",
  "my name", "yesterday") force it. Saves tokens and stops noise injection.

Pass `safe=False` if you need the raw assembled block (e.g. for your own framing).

## Lifecycle controls

```python
mind.pin(memory_id)              # always surfaces first in recall
mind.unpin(memory_id)
mind.snooze(memory_id, "2026-09-01T00:00:00Z")   # hidden from recall until then
mind.unsnooze(memory_id)
```

Also available as the `lm_pin` / `lm_snooze` MCP tools.

## Type-aware forgetting

The sleep-time cycle decays memories on a half-life that depends on their type
(read from `metadata["type"]` or a matching tag):

| type | half-life |
|---|---|
| decision, identity, milestone, preference | never decays |
| project, feature | 120 days |
| bugfix, discovery | 90 days |
| note | 60 days · problem 45 · handoff 30 · status 14 · transient 7 |

Frequent recall extends a memory's half-life up to 3× (access-reinforcement).
Unknown types fall back to the global half-life.

## Neighbor evolution (self-organizing metadata)

```python
mind.dream(evolve=True)
```

An undimensioned memory inherits its life/work dimension from a majority vote of
its confident nearest neighbours — so the keyless path gradually acquires
categorization without any LLM. Deterministic, off by default, fail-soft.

## Anti-contamination guardrail

`infer_links()` (inductive dreaming) drops any synthesized fact that introduces a
proper noun **absent from the source facts** — a fail-closed guard against the
LLM hallucinating a new entity into a conclusion. Inferences built only from
known entities are kept.

## Read/write context isolation

Set `LOGICA_MIND_CONTEXT=secondary` (or `read-only`) on background processes — a
cron, a subagent, a tool run. They keep **reading** the shared memory, but
`observe_user()` becomes a no-op, so automated turns can't drown the real owner's
dialectic profile.

---

← Back to the [docs index](README.md).
