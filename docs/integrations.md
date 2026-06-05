# Integrations & SDKs

Drop Logica Mind in as the long-term memory behind LangChain, LlamaIndex, any custom host loop, or a TypeScript/JavaScript app talking to the REST API.

A `LogicaMind` object exposes a tiny, stable surface — `remember()`, `log()`,
`recall()`, `forget()`, `dream()` — and that surface is all an integration needs.
Every adapter on this page is a thin wrapper that maps a framework's memory
contract onto those verbs. The adapters never touch stores or embeddings
directly, so they work the same whether you run the zero-key default (a SQLite
store and the hashing embedder, no API keys) or a fully configured semantic
setup. See [./stores.md](./stores.md) and
[./embeddings-and-reranking.md](./embeddings-and-reranking.md) for those choices.

| Integration | Import / package | Maps onto |
| --- | --- | --- |
| LangChain memory | `logica_mind.integrations.langchain.LogicaMindMemory` | `recall()` + `log()` + `remember()` |
| LlamaIndex memory | `logica_mind.integrations.llamaindex.LogicaMindMemory` | `recall()` + `log()` + `remember()` |
| Generic provider adapter | `examples/provider_adapter.py` | `recall()` + `log()` + `remember()` + `dream()` |
| TypeScript SDK | `@logica-mind/sdk` (REST) | the dashboard server's HTTP API |

---

## LangChain memory adapter

`LogicaMindMemory` implements the LangChain `BaseMemory` method surface —
`memory_variables`, `load_memory_variables`, `save_context`, and `clear` — by
duck typing. The module imports whether or not LangChain is installed, so you can
construct it directly and pass it to a chain.

```python
from logica_mind import LogicaMind
from logica_mind.integrations.langchain import LogicaMindMemory

memory = LogicaMindMemory(LogicaMind(namespace="support"))
```

On every turn:

- **`load_memory_variables(inputs)`** reads the current input, calls
  `mind.recall()`, and returns the top hits joined into a single string under
  `memory_key` (default `"history"`). Each hit is rendered as `- <content>`.
- **`save_context(inputs, outputs)`** logs the user message and the assistant
  message as episodic turns (`mind.log(..., role=...)`), then distils durable
  facts from the user turn with `mind.remember()`.
- **`clear()`** bulk-deletes this namespace's episodic turns and keeps the
  distilled knowledge.

### Constructor parameters

| Parameter | Default | Purpose |
| --- | --- | --- |
| `mind` | — | the `LogicaMind` instance to back the memory |
| `memory_key` | `"history"` | key the recalled text is returned under |
| `input_key` | `"input"` | key in `inputs` holding the user message |
| `output_key` | `"output"` | key in `outputs` holding the assistant reply |
| `limit` | `6` | how many memories to recall per turn |
| `distil` | `True` | run LLM fact-extraction on the user turn |
| `distil_every` | `1` | only distil on every Nth turn |

Fact extraction (`remember()`) is the expensive part because it can call an LLM.
Set `distil=False` to skip it entirely (raw turns are still logged), or
`distil_every=N` so a chatty loop fires extraction only once every N user turns.
With the default zero-key setup the LLM is a no-op, so distillation simply logs
the turn — extraction kicks in once you wire a real LLM.

```python
from logica_mind import LogicaMind
from logica_mind.integrations.langchain import LogicaMindMemory

memory = LogicaMindMemory(
    LogicaMind(namespace="support"),
    memory_key="history",
    input_key="input",
    output_key="output",
    limit=6,
    distil=True,
    distil_every=3,   # extract facts every third user turn
)

# What a chain does under the hood:
vars = memory.load_memory_variables({"input": "what plan am I on?"})
print(vars["history"])   # "- The customer is on the Pro tier.\n- ..."

memory.save_context(
    {"input": "I'm on the Pro tier and based in Brazil."},
    {"output": "Got it — Pro tier, Brazil."},
)

memory.clear()   # drops episodic turns, keeps distilled facts
```

> **Strict pydantic validation.** Because the adapter duck types the interface,
> it is not a pydantic model. If your stack requires a real
> `langchain_core.memory.BaseMemory` subclass, subclass `BaseMemory` and delegate
> each method to a `LogicaMindMemory` instance.

The package also re-exports the class as `LangChainMemory`:

```python
from logica_mind.integrations import LangChainMemory  # same class as LogicaMindMemory
```

---

## LlamaIndex memory adapter

The LlamaIndex adapter lives in `logica_mind.integrations.llamaindex` and is also
named `LogicaMindMemory`. It implements the LlamaIndex `BaseMemory` method
surface — `put`, `get`, `get_all`, `set`, `reset` — and imports with or without
LlamaIndex installed.

```python
from logica_mind import LogicaMind
from logica_mind.integrations.llamaindex import LogicaMindMemory

memory = LogicaMindMemory(LogicaMind(namespace="research"), limit=8)
```

### Methods

| Method | What it does |
| --- | --- |
| `put(message)` | logs one chat turn; if the role is `user`/`human`, also runs `remember()` |
| `get(input)` | recalls memories relevant to `input`, returned as `system` messages |
| `get_all()` | returns every episodic turn for the namespace, ordered by `created_at` |
| `set(messages)` | replays a list of messages through `put()` |
| `reset()` | forgets every episodic turn in the namespace |

`put()` accepts a dict (`{"role": ..., "content": ...}`), a message object with
`.content` (and optional `.role`, including a `MessageRole`-style enum whose
`.value` is normalized), or a bare string (treated as a user turn). Empty content
is skipped. `get()` returns an empty list when no input is provided; otherwise it
maps each recall hit to `{"role": "system", "content": "- <content>"}`.

```python
from logica_mind import LogicaMind
from logica_mind.integrations.llamaindex import LogicaMindMemory

memory = LogicaMindMemory(LogicaMind(namespace="research"))

memory.put({"role": "user", "content": "I'm comparing vector stores for Acme Inc."})
memory.put({"role": "assistant", "content": "Noted — vector store comparison for Acme."})

for msg in memory.get("what is the user working on?"):
    print(msg)   # {"role": "system", "content": "- The user is comparing vector stores..."}

history = memory.get_all()   # episodic turns, oldest first
memory.reset()               # clear episodic turns
```

The class is re-exported as `LlamaIndexMemory`:

```python
from logica_mind.integrations import LlamaIndexMemory
```

---

## Generic provider adapter

Not every host is a framework. When you control the loop — a custom agent, a
webhook handler, a message bus — you only need two verbs: **recall** before
generating a reply, and **save** after the turn. The runnable example in
`examples/provider_adapter.py` shows the whole pattern in about a dozen lines.

```python
from logica_mind import LogicaMind, MemoryLayer


class LogicaMindProvider:
    """Thin, framework-agnostic adapter."""

    def __init__(self, agent_id: str, **mind_kwargs):
        self.mind = LogicaMind(namespace=agent_id, **mind_kwargs)

    # what a host calls before generating a reply
    def recall(self, query: str, limit: int = 6) -> str:
        hits = self.mind.recall(query, limit=limit)
        if not hits:
            return ""
        lines = [f"- {h.memory.content}" for h in hits]
        return "Relevant memory:\n" + "\n".join(lines)

    # what a host calls after a turn
    def save(self, user_msg: str, assistant_msg: str) -> None:
        self.mind.log(user_msg, role="user")
        self.mind.log(assistant_msg, role="assistant")
        # let the model also learn durable facts from the user's message
        self.mind.remember(user_msg)

    # occasional background consolidation
    def dream(self):
        return self.mind.dream()
```

Use it:

```python
provider = LogicaMindProvider(agent_id="support-bot")
provider.save(
    "My plan is the Pro tier and I'm in Brazil.",
    "Got it — Pro tier, Brazil. How can I help?",
)
print(provider.recall("which plan is the customer on?"))
# Relevant memory:
# - The customer is on the Pro tier.
# - The customer is in Brazil.
```

A few things worth calling out:

- **`agent_id` is the namespace.** Give each agent its own `agent_id` and their
  memories stay isolated. Pass extra `LogicaMind` keyword arguments through
  `**mind_kwargs` (a different `store`, `embedder`, `limit` weights, and so on).
- **`recall()` returns formatted text**, ready to drop into a prompt. Each item
  in the underlying `recall()` result is a `SearchResult` with `.score` and a
  `.memory` whose `.content` is the stored text.
- **`dream()`** is the optional background consolidation pass. Call it on a
  schedule (idle time, end of session) to merge, summarize, and prune — see
  [./dreaming.md](./dreaming.md).

This is the same two-verb contract the LangChain and LlamaIndex adapters use
internally, so once you understand the provider you understand all three.

---

## TypeScript SDK

`@logica-mind/sdk` is a thin TypeScript client for the Logica Mind server. It has
**zero dependencies** — it uses the global `fetch`, so it runs on Node 18+ or in
the browser — and it speaks the same small REST surface the dashboard uses.

### Run the server

The SDK talks to a running Logica Mind instance. Start one headless with the CLI:

```bash
logica-mind ui --no-open        # serves the REST API on http://localhost:8420
```

The dashboard server defaults to port `8420`; pass `--port` to change it (and
`--db` / `--namespace` to point at a specific database or namespace). With no
flags this is the zero-key path: a local SQLite database and the hashing embedder,
no API keys required. See [./installation.md](./installation.md) for setup.

### Use the client

```ts
import { LogicaMind } from "@logica-mind/sdk";

const mind = new LogicaMind({ namespace: "my-agent" });

await mind.remember("The user prefers concise answers in Portuguese.");
await mind.log("Talked about the deploy pipeline.", "user");

const hits = await mind.recall("what language should I use?");
for (const h of hits) console.log(h.score, h.memory.content);

console.log(await mind.user());     // dialectic user model
console.log(await mind.stats());    // per-layer counts
```

### Construction

```ts
const mind = new LogicaMind({
  baseUrl: "http://localhost:8420",  // default; trailing slash is trimmed
  namespace: "my-agent",             // default: "default"
  fetch: customFetch,                // optional: inject your own fetch
});
```

| Option | Default | Purpose |
| --- | --- | --- |
| `baseUrl` | `"http://localhost:8420"` | server address |
| `namespace` | `"default"` | namespace sent with every request |
| `fetch` | global `fetch` | injectable fetch implementation |

The `namespace` is attached automatically to each call, so you do not pass it per
method.

### Methods

| Method | HTTP | Returns |
| --- | --- | --- |
| `remember(text, session?)` | `POST /api/remember` | `{ stored: string[]; count: number }` |
| `log(text, role?, session?)` | `POST /api/log` | `{ ok: boolean; id: string \| null }` |
| `forget({ id?, query? })` | `POST /api/forget` | `{ deleted: number }` |
| `recall(query, limit = 8)` | `GET /api/recall` | `RecallHit[]` |
| `stats()` | `GET /api/stats` | `{ namespace: string; stats: Record<string, number> }` |
| `graph(history = true)` | `GET /api/graph` | `{ nodes: unknown[]; links: unknown[] }` |
| `user()` | `GET /api/user` | `string` (the profile text) |

`remember()` performs automatic fact extraction and dedup server-side and reports
what it stored. `log()` records a raw episodic turn. `forget()` deletes by `id` or
by semantic `query`. `recall()` unwraps the server's `{ results: [...] }` envelope
and returns the array directly (an empty array if nothing matched). `user()`
unwraps `{ profile }` and returns the string.

### Types

The SDK ships these interfaces:

```ts
interface Memory {
  id: string;
  content: string;
  layer: "episodic" | "semantic" | "graph" | "user";
  namespace: string;
  tags?: string[];
  created_at?: string;
}

interface RecallHit {
  score: number;
  components?: Record<string, number>;
  memory: Memory;
}

interface LogicaMindOptions {
  baseUrl?: string;
  namespace?: string;
  fetch?: typeof fetch;
}
```

The four `layer` values line up with the four memory layers Logica Mind manages —
episodic, semantic, graph, and user — described in [./concepts.md](./concepts.md).
`score` is the blended recall score and `components` is the optional per-signal
breakdown (similarity, importance, recency).

### Build

The package is published as ES modules with TypeScript types. To build from
source:

```bash
cd sdk-ts
npm run build     # runs tsc → dist/
```

It is licensed Apache-2.0, the same as the rest of the project.

---

## See also

- [Quickstart](./quickstart.md) — create a `LogicaMind` and run the smallest end-to-end loop.
- [Concepts](./concepts.md) — the four memory layers the adapters map onto.
- [Stores](./stores.md) — the SQLite default and the Postgres, Redis, and Supabase backends.
- [Embeddings & reranking](./embeddings-and-reranking.md) — the hashing default and how to plug in real embedders.
- [Dreaming](./dreaming.md) — the background consolidation the provider's `dream()` triggers.
- [User model & peers](./user-model-and-peers.md) — what `mind.user()` / `/api/user` returns.
- [Knowledge graph](./knowledge-graph.md) — the temporal graph behind `/api/graph`.
