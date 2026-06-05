# Portability & privacy

Move an agent's memory between apps and vendors with signed, portable bundles — and erase it on demand with GDPR-native deletion across every layer.

Memory is a liability as much as an asset. The moment an agent remembers things about a person, you inherit two obligations: the user owns that data and can take it elsewhere, and the user can ask you to forget it — completely. Logica Mind treats both as first-class operations, not afterthoughts. You can serialize a namespace into a tamper-evident **bundle** and re-import it into any other instance, and you can erase everything about an entity — semantic facts, conversation turns, graph edges, the user model — with a single call.

Everything on this page works offline with the default zero-key setup (SQLite store + hashing embedder). No external service ever sees the data; portability and erasure are local operations on your own store.

## Why this matters

Most memory libraries lock you in. The data lives in their store, in their format, behind their API, and "delete my data" means dropping a row by id if you happen to know it. That's a poor trust story for anything touching real users.

Logica Mind is built around two guarantees:

- **Portability** — your memory is yours. Export it to a plain, signed document and carry it to another app or another vendor. The format is open and provider-independent.
- **Erasure** — your memory is forgettable. One call removes everything that mentions an entity, across all four layers and the knowledge graph, so "right to be forgotten" is one line of code.

| Operation | Method | What it does |
| --- | --- | --- |
| Export | `export_bundle()` | Serialize a namespace into a portable, optionally HMAC-signed bundle. |
| Import | `import_bundle()` | Load a bundle into a namespace, verifying the signature when a secret is given. |
| Erase an entity | `forget_about()` | Delete every memory mentioning an entity, across all layers + graph edges. |
| Hard reset | `purge()` | Delete every memory in the namespace. |
| Mask PII | `redact_pii()` | Mask emails, phone numbers and long digit runs in a string. |

## Portable memory bundles

A bundle is the unit of portability: a JSON-serializable snapshot of a namespace's memories that you can save to disk, hand to a user, or load into a different instance — even one backed by a different store or a different embedding provider.

### Exporting

`export_bundle(secret=None, layers=None)` returns a dictionary with two keys: a `payload` (the memories themselves) and a `signature`.

```python
from logica_mind import LogicaMind

mind = LogicaMind(namespace="acme-app")   # SQLite + hashing embedder, no API keys
mind.remember("Maya prefers email over phone calls.")
mind.remember("Maya works in the Berlin timezone.")

bundle = mind.export_bundle()
# {
#   "payload": {"v": 1, "namespace": "acme-app", "count": 2, "memories": [ ... ]},
#   "signature": None,
# }
```

The payload is a small, stable structure:

| Field | Meaning |
| --- | --- |
| `v` | Bundle format version (currently `1`). |
| `namespace` | The source namespace the memories came from. |
| `count` | Number of memories in the bundle. |
| `memories` | A list of memory dicts. |

Embedding vectors are **stripped** from the export — bundles carry the text and metadata, not the vectors. That keeps bundles compact and provider-neutral: the destination re-embeds with whatever embedder it uses, so a bundle exported under the offline hashing embedder imports cleanly into an instance using a different one.

Persisting a bundle is just JSON:

```python
import json

with open("acme-memory.json", "w", encoding="utf-8") as f:
    json.dump(bundle, f, ensure_ascii=False)
```

#### Exporting selected layers

Pass `layers` to export only some of the four memory layers — for example, durable facts without the raw conversation log:

```python
from logica_mind import MemoryLayer

facts_only = mind.export_bundle(layers=[MemoryLayer.SEMANTIC])
```

With `layers=None` (the default), every layer is exported — episodic, semantic, graph and user. See [Core concepts](./concepts.md) for what each layer holds.

### Signing a bundle

Pass a `secret` to sign the bundle with HMAC-SHA256. The signature is computed over a canonical (sorted-keys) JSON encoding of the payload, so the receiver can prove the bundle wasn't altered in transit.

```python
bundle = mind.export_bundle(secret="shared-secret-between-apps")
print(bundle["signature"])   # a hex SHA-256 HMAC digest
```

Without a secret, `signature` is `None` and the bundle is unsigned — still portable, just not tamper-evident. Signing is the right default whenever a bundle crosses a trust boundary (leaves your process, goes to a user, moves to another vendor).

### Importing

`import_bundle(bundle, secret=None, verify=True)` loads a bundle's memories into the current namespace and returns how many were imported.

```python
import json
from logica_mind import LogicaMind

with open("acme-memory.json", encoding="utf-8") as f:
    bundle = json.load(f)

destination = LogicaMind(namespace="cursor-app")
n = destination.import_bundle(bundle, secret="shared-secret-between-apps")
print(f"imported {n} memories")
```

On import, each memory is:

- re-namespaced to the **destination** namespace (so a bundle from `acme-app` lands cleanly in `cursor-app`),
- re-embedded if it has no vector — using the destination's embedder — so it's immediately searchable,
- added to the store alongside whatever is already there.

#### Signature verification

When you pass a `secret` and leave `verify=True` (the default), the import recomputes the HMAC over the payload and compares it to the bundle's signature using a constant-time check. If they don't match, the import is refused:

```python
try:
    destination.import_bundle(tampered_bundle, secret="shared-secret-between-apps")
except ValueError as exc:
    print(exc)   # "bundle signature verification failed — refusing import"
```

Verification only runs when a `secret` is supplied. To import an unsigned bundle, call without a secret (or set `verify=False`):

```python
destination.import_bundle(unsigned_bundle)            # no secret, no verification
destination.import_bundle(any_bundle, verify=False)   # skip verification explicitly
```

> The same secret must be used on both ends. HMAC is symmetric: the app that exports and the app that imports share the secret, and anyone without it can neither forge a valid signature nor pass verification.

### Moving memory between apps and vendors

Together, export and import make memory provider-independent. A user can carry the same memory from one assistant to another:

```python
# In app A — export the user's memory, signed
bundle = app_a_mind.export_bundle(secret=user_secret)

# ...hand the bundle to the user or to app B...

# In app B — verify and load it
app_b_mind.import_bundle(bundle, secret=user_secret)
```

Because bundles are plain JSON and embeddings are re-derived on import, the source and destination don't have to share a store backend or an embedding model. A namespace exported from a SQLite + hashing setup imports just as well into one backed by a hosted vector store and a different embedder. See [Stores](./stores.md) and [Embeddings & reranking](./embeddings-and-reranking.md) for the backends a bundle can move between.

## GDPR-native erasure

Portability is only half the trust story. The other half is being able to delete data thoroughly and provably.

### `forget_about(entity)` — right to be forgotten

`forget_about(entity)` is the right-to-be-forgotten primitive. It deletes **every memory that mentions the entity, across all four layers and the knowledge graph**, and returns the number of memories removed.

```python
mind.remember("Maya prefers email over phone calls.")
mind.remember("Maya is evaluating Acme Inc for a pilot.")
mind.learn_graph("Maya works at Acme Inc.")

removed = mind.forget_about("Maya")
print(f"erased {removed} memories about Maya")
```

What it covers:

- **Semantic facts** — any distilled fact whose content mentions the entity.
- **Episodic turns** — raw conversation/event logs that mention the entity.
- **Graph edges** — any relationship edge where the entity is the subject or object.
- **User / peer observations** — observations recorded *about* the entity.

How the match works — and why it's safe:

- Matching is on **whole tokens**, not substrings. Erasing `"ana"` will never delete a memory about a `"banana"`. An entity matches a memory only when all of the entity's tokens are present as tokens in that memory.
- It also matches structured fields: a graph edge or observation whose `subject`, `object`, or `observed` field equals the entity is erased even if the rendered content phrases it differently.

This is the call to wire into a data-subject deletion request. One invocation cleans up a person, a customer, or a project name everywhere it appears in the namespace:

```python
# A customer exercises their right to erasure
deleted = mind.forget_about("Acme Inc")
log.info("GDPR erase complete: %d memories removed", deleted)
```

> `forget_about` is also exposed over the MCP server as the `lm_forget_about` tool, so an agent can perform a right-to-be-forgotten erase directly. See [MCP server](./mcp.md).

#### `forget_about` vs `forget`

There's also a lower-level [`forget(...)`](./concepts.md) for targeted deletion — by memory id or by semantic query above a similarity threshold. Use `forget` to remove a *specific* memory or a small cluster; use `forget_about` for *complete* erasure of an entity. They serve different jobs:

| | `forget` | `forget_about` |
| --- | --- | --- |
| Targets | one id, or a semantic query | an entity name |
| Scope | matched memories only | every layer + graph edge |
| Use case | correct/remove a fact | data-subject erasure |

### `purge()` — hard reset

`purge()` deletes **every** memory in the namespace and returns the count removed. It's the nuclear option: a full reset of that agent's memory.

```python
total = mind.purge()
print(f"wiped {total} memories from this namespace")
```

`purge()` is scoped to the current namespace only — other namespaces in the same store are untouched. Reach for it when you're decommissioning an agent, resetting a test fixture, or honoring a "delete everything" request for an isolated tenant.

### `redact_pii(text)` — masking at the boundary

`redact_pii(text)` is a static method that masks personal identifiers in a string. It's a light privacy guard for the *output* boundary — when recalled content might be shown in a shared or logged context.

```python
from logica_mind import LogicaMind

safe = LogicaMind.redact_pii("Reach Maya at maya@acme.com or +1 (555) 123-4567.")
print(safe)   # "Reach Maya at [email] or [phone]."
```

It masks:

- **emails** → `[email]`
- **phone numbers and long digit runs** → `[phone]`

It's a regex-based guard, not a full PII classifier — it won't catch names or addresses. Use it to scrub recall output before it lands in logs or a shared transcript, layered on top of `forget_about` for true erasure. Because it's a `@staticmethod`, you can call it on the class without constructing a mind:

```python
for hit in mind.recall("how do I contact the user?"):
    print(LogicaMind.redact_pii(hit.memory.content))
```

## The compliance story, end to end

These primitives compose into a defensible data-handling posture:

1. **Portability** — `export_bundle()` gives a user a complete, signed copy of what an agent knows about them (data portability), in an open format they can take anywhere.
2. **Erasure** — `forget_about(entity)` removes a data subject across every layer and the graph in one call (right to be forgotten); `purge()` wipes a namespace entirely.
3. **Minimization at the boundary** — `redact_pii(text)` masks identifiers in what gets surfaced or logged.
4. **Tamper-evidence** — HMAC signatures prove a bundle wasn't altered between apps or vendors, so memory can cross trust boundaries with integrity intact.

Because all of this runs locally on your own store with the default offline setup, you're never sending user data to a third party just to honor a portability or deletion request. The data stays where you put it, moves only when you export it, and disappears completely when you erase it.

## See also

- [Core concepts](./concepts.md) — the four memory layers and the `Memory` unit that bundles serialize.
- [Stores](./stores.md) — the backends a bundle can move between, and where erasure deletes from.
- [Embeddings & reranking](./embeddings-and-reranking.md) — why bundles drop vectors and re-embed on import.
- [Knowledge graph](./knowledge-graph.md) — the entity/relationship edges that `forget_about` erases.
- [MCP server](./mcp.md) — exposing `forget_about` to agents as the `lm_forget_about` tool.
