# User model & peers

A living, dialectic model of *who the user is*, plus directional peer modeling of what one party believes about another.

Most memory stores keep flat facts. Logica Mind also keeps a **theory of the user**: raw observations accumulate, and a synthesis step reconciles them into one concise, evolving profile. You can then ask natural-language questions *about* the user and get grounded answers. The same machinery models **peers** — what `agent-a` believes about `agent-b` — directionally, without merging perspectives.

Everything on this page works offline with the default zero-key setup (SQLite store + hashing embedder). When an LLM is configured, the model becomes genuinely dialectic — it reasons about the user instead of just listing facts. Without one, it degrades gracefully to a de-duplicated list of observations. See [LLM-optional behavior](#llm-optional-behavior).

## Quick start

```python
from logica_mind import LogicaMind

mind = LogicaMind(namespace="acme-app")   # SQLite + hashing embedder, no API keys

# accumulate observations about the user
mind.observe_user("Prefers email over phone calls.")
mind.observe_user("Works in the Berlin timezone.")
mind.observe_user("Is evaluating Acme Inc for a pilot.")

# read the current profile
print(mind.user_profile())

# ask a natural-language question about the user
print(mind.ask_about_user("How should I contact this person?"))
```

With no LLM, `user_profile()` returns the recent observations and `ask_about_user(...)` returns the most relevant ones. Add an LLM and both become reasoned prose.

## Observations

An observation is a single durable note about the user. Each one is stored as a `USER`-layer `Memory` tagged `observation`, so it travels through the same store as everything else.

```python
mind.observe_user("Prefers concise, bulleted answers.")
```

`observe_user(text)` returns the stored `Memory` (or `None` if `text` is empty). Observations are the raw material the profile is synthesized from.

## The profile

`user_profile()` returns the current model of the user as a string.

```python
profile = mind.user_profile()
print(profile)
```

How it resolves:

- If a synthesized profile exists, that text is returned.
- Otherwise it falls back to the most recent observations (up to the last 12), one per line.

The profile is itself stored as a single `USER`-layer memory (one per namespace), so it is portable and queryable like any other memory.

### Synthesizing the profile

Synthesis is the dialectic step: it reconciles accumulated observations into one concise profile, reconciling contradictions in favour of the most recent observation. It runs automatically during a dream cycle, and you can also trigger it through the underlying user model:

```python
mind.user.synthesize()      # reconcile observations -> profile
print(mind.user_profile())
```

With an LLM, synthesis reasons over the newest observations and the existing model to produce labelled prose (Identity, Preferences, Communication style, Goals, Context). Without an LLM, it produces a de-duplicated list of observations. Either way the result is saved as the namespace's profile memory.

> Synthesis also runs as part of the dream cycle, so the profile stays fresh as new observations arrive. See [Dreaming](./dreaming.md).

## Asking about the user

`ask_about_user(question, k=8)` answers a question *about* the user, reasoning over the profile plus the most relevant observations.

```python
answer = mind.ask_about_user("What's the best way to reach this person?")
print(answer)

# widen the pool of grounding observations
answer = mind.ask_about_user("What are their goals?", k=12)
```

- `question` — a natural-language question about the user.
- `k` — how many relevant observations to pull in as grounding (default `8`).

With an LLM, the answer is grounded in the profile and the retrieved observations; if something isn't supported, it says what is unknown rather than guessing. Without an LLM, it returns the grounding material itself — the most relevant observations (or the profile if there are none).

There is also an async variant:

```python
answer = await mind.aask_about_user("How should I contact this person?")
```

## Learning from conversations

You usually don't write observations by hand. Feed a conversation and let the model derive observations and extract durable facts in one call.

```python
result = mind.ingest_conversation([
    {"role": "user", "content": "I'm Maya. Please keep replies short."},
    {"role": "assistant", "content": "Got it — short and to the point."},
    {"role": "user", "content": "And email me, don't call."},
])
print(result)   # {"logged": 3, "facts": ..., "observations": ...}
```

`ingest_conversation(messages, session=None, extract=True, derive=True, source=None)`:

- `messages` — a list of dicts. Each item may use `role` or `speaker` for the speaker, and `content` or `text` for the body.
- `session` — an optional session id to group the turns.
- `extract` — when `True` (and an LLM is available), durable facts are extracted seeing the *whole* exchange, so a short reply resolves against its question.
- `derive` — when `True` (and an LLM is available), user observations are derived from the conversation and fed to the dialectic model.
- `source` — tags every captured memory with its origin (e.g. an app or client name), useful for auditing what captured what.

It returns a dict of counts: `{"logged", "facts", "observations"}`.

### Deriving observations directly

`derive(transcript=None, session=None, window=20)` infers durable observations about the user from a conversation and feeds them to the dialectic model. It returns the count of *new* (non-duplicate) observations stored.

```python
new_obs = mind.derive(transcript="user: I switched to the Pro plan last week.")
print(new_obs)   # number of new observations added
```

If `transcript` is omitted, `derive()` looks at recent episodic turns that haven't been derived yet (the lazy path used during dreaming) and marks them derived so an idle loop never re-processes unchanged history.

> `derive()` needs an LLM to reason — it is a no-op offline and returns `0`. `ingest_conversation(...)` still logs every turn either way.

## Peers — directional theory of mind

A peer model captures what **one party believes about another**, directionally. Instead of a single merged view of "the user," each observer builds its own theory of an observed party. This is ideal for multi-agent systems where `agent-a` and `support` may know different things about the same `agent-b`.

### Recording peer observations

```python
mind.observe_peer("agent-a", "agent-b", "Owns the billing integration.")
mind.observe_peer("agent-a", "agent-b", "Prefers async updates over meetings.")
mind.observe_peer("support", "agent-b", "Opened two tickets about webhooks.")
```

`observe_peer(observer, observed, text, importance=0.6)` records a directional `observer → observed` observation and returns the stored `Memory` (or `None` if `text` is empty). It is stored on the `USER` layer with the observer and observed recorded so each pairing stays separate.

### Reading a peer card

`peer_card(observer, observed)` returns a directional card describing what `observer` knows or believes about `observed`.

```python
card = mind.peer_card("agent-a", "agent-b")
print(card)
```

With an LLM it writes a concise card from the observations; without one it returns the observations themselves (the newest up to 30). It returns an empty string if there are no observations for that pairing.

### Querying a peer perspective

`peer_query(observer, observed, question)` answers a question from one party's perspective of another — a theory-of-mind query.

```python
print(mind.peer_query(
    "agent-a", "agent-b",
    "How does agent-b prefer to receive updates?",
))
```

With an LLM, it answers from `agent-a`'s perspective of `agent-b`, saying what is unknown if the card doesn't support an answer. Without an LLM, it returns the peer card itself.

Note that peer perspectives are kept separate: `peer_card("agent-a", "agent-b")` and `peer_card("support", "agent-b")` draw from different observations and are not merged.

## LLM-optional behavior

The default `LogicaMind(...)` uses no LLM, so everything here runs zero-key and offline. An LLM only ever *upgrades* the output; it is never required.

| Operation | With an LLM | Without an LLM |
|---|---|---|
| `user_profile()` | reasoned, labelled prose | recent observations (up to 12) |
| `user.synthesize()` | dialectic reconciliation | de-duplicated observation list |
| `ask_about_user(...)` | grounded, reasoned answer | most relevant observations |
| `derive(...)` | infers new observations | no-op, returns `0` |
| `ingest_conversation(...)` | logs + extracts facts + derives | logs turns only |
| `peer_card(...)` | concise directional card | the raw observations |
| `peer_query(...)` | perspective-aware answer | the peer card |

Logging, observing, and profile retrieval never fail when no LLM is present — only the *reasoning* layers degrade to returning their grounding material. If an LLM call fails at runtime, the same fallbacks apply, so these methods stay safe to call.

To enable reasoning, pass an LLM when constructing the mind:

```python
from logica_mind import LogicaMind
from logica_mind.llm import OpenAILLM

mind = LogicaMind(namespace="acme-app", llm=OpenAILLM())   # reads OPENAI_API_KEY
mind.observe_user("Prefers email; works in Berlin.")
mind.user.synthesize()
print(mind.ask_about_user("How should I reach this person?"))
```

## See also

- [Stores](./stores.md) — where user and peer memories are persisted (SQLite by default).
- [Embeddings](./embeddings-and-reranking.md) — how observations are embedded for relevance search.
- [LLM providers](./api-reference.md) — enabling the reasoning layers used by synthesis and queries.
- [Dreaming](./dreaming.md) — the consolidation cycle that synthesizes the profile and derives observations.
- [Multi-agent](./user-model-and-peers.md) — per-namespace agents and directional knowledge between them.
