# Embeddings and reranking

How Logica Mind turns text into vectors, and how it sharpens the final results — all of it pluggable, with an offline, zero-key default.

Recall is a two-stage job. First an **embedder** turns text into a fixed-length vector so the store can find candidates by semantic similarity. Then an optional **reranker** does the final relevance (or diversity) pass over those candidates before they reach you. Both are interfaces you can swap, and both ship with an offline default so the library works out of the box with no API key.

By default `LogicaMind` uses the [`HashingEmbedder`](#hashingembedder-default-offline) (deterministic, dependency-free) and **no reranker**. Everything below is opt-in.

```python
from logica_mind import LogicaMind

# zero-key, fully offline: SQLite store + hashing embedder, no reranker
mind = LogicaMind(namespace="my-agent")
mind.remember("Maya prefers concise answers in Portuguese.")
for hit in mind.recall("what language should I use?"):
    print(round(hit.score, 3), hit.memory.content)
```

---

## The `Embedder` interface

Every embedder implements one small contract (`logica_mind/embeddings/base.py`):

| Member | What it does |
|---|---|
| `dim` (property) | Dimensionality of the vectors this embedder produces. |
| `embed(texts)` | Embed a batch of texts, treated as **documents** to be stored. Returns one vector per input. |
| `embed_one(text)` | Convenience wrapper around `embed` for a single text. |
| `embed_query(text)` | Embed a search **query**. The default falls back to the document path; embedders that distinguish query vs document encoding override it. |

The `embed` ↔ `embed_query` split matters for retrieval quality. Some models encode a question differently from a stored passage. The base class makes the document path the safe default, so simpler embedders don't have to care.

The library never assumes a particular dimension. It reads `embedder.dim` and guards against mixing vectors of different sizes (a 256-d hashing vector and a 1024-d Voyage vector can't be compared), warning you instead of producing garbage similarities.

---

## The six embedders

| Embedder | `name` | Needs | Default dim | Query/doc split | Notes |
|---|---|---|---|---|---|
| `HashingEmbedder` | `hashing` | nothing (stdlib) | 256 | no | offline default, deterministic, lexical |
| `LocalEmbedder` | `local` | `sentence-transformers` | 384 | no | real semantic, on-device, no network |
| `VoyageEmbedder` | `voyage` | `[voyage]` + `VOYAGE_API_KEY` | 1024* | yes | Matryoshka dims, retries, contextualized |
| `OpenAIEmbedder` | `openai` | `[openai]` + `OPENAI_API_KEY` | 1536 | no | pinnable output size |
| `BatchedEmbedder` | `batched` | wraps any embedder | inner's dim | inherits inner | rate-limit-safe wrapper |
| `VoyageMultimodalEmbedder` | `voyage-multimodal` | `[voyage]` + `VOYAGE_API_KEY` | 1024 | yes | text **and** images in one space |

\* `VoyageEmbedder`'s default dim depends on the model (see below).

All optional embedders are **lazy-imported**: importing `logica_mind.embeddings` never pulls `voyageai`, `openai`, or `sentence-transformers`, so the core stays dependency-free until you actually instantiate one.

### `HashingEmbedder` (default, offline)

The zero-key default. It uses the hashing trick: tokens are hashed into a fixed-dimension vector with TF weighting, then L2-normalized. It is *lexical*, not deep-semantic, but it is deterministic, needs no API key, and makes the whole library (and its test suite) work out of the box.

It mixes whole-word features with character n-grams, so near-words still match — `answer` against `answers`, `Portugues` against `Portuguese` — which gives offline recall meaningfully better behavior than plain bag-of-words.

```python
from logica_mind.embeddings import HashingEmbedder

emb = HashingEmbedder(dim=256, char_ngrams=3)   # both are the defaults
print(emb.dim)                                   # 256
vecs = emb.embed(["hello world", "olá mundo"])   # one 256-d vector each
```

### `LocalEmbedder` (offline, real semantic)

True semantic embeddings with **no API key and no network** — it runs a small transformer on-device via `sentence-transformers`. Heavier than the hashing default, but it gives real semantic recall offline. The default model is `all-MiniLM-L6-v2` (384 dims).

```bash
pip install "logica-mind[local]"   # installs sentence-transformers
```

```python
from logica_mind.embeddings import LocalEmbedder

emb = LocalEmbedder(model="all-MiniLM-L6-v2")   # dim resolves to 384 on first use
```

### `VoyageEmbedder` (API, highest-quality text)

Voyage AI text embeddings. Lazy-imports `voyageai`, reads `VOYAGE_API_KEY` from the environment (or `api_key=...`), and retries transient errors with exponential backoff.

```bash
pip install "logica-mind[voyage]"
export VOYAGE_API_KEY=...
```

```python
from logica_mind.embeddings import VoyageEmbedder

emb = VoyageEmbedder(model="voyage-3-lite")     # default model
```

Key constructor arguments:

| Argument | Default | Purpose |
|---|---|---|
| `model` | `"voyage-3-lite"` | Voyage embedding model. |
| `api_key` | `None` → `VOYAGE_API_KEY` env | API credential. |
| `output_dimension` | `None` | Matryoshka — trade vector size for quality (e.g. `256`, `512`, `1024`, `2048`). When set, it also fixes `dim`. |
| `output_dtype` | `"float"` | Only `"float"` is supported; the pipeline assumes float vectors and rejects other values. |
| `max_retries` | `4` | Retry budget for rate limits / transient errors. |
| `base_backoff` | `2.0` | Base seconds for exponential backoff. |
| `context_model` | `"voyage-context-3"` | Model used by `embed_contextualized`. |

**Query vs document.** `VoyageEmbedder` encodes the two paths differently: `embed(texts)` uses `input_type="document"`, while `embed_query(text)` uses `input_type="query"`. Logica Mind calls the right one automatically — `embed_query` on the recall path, `embed` when storing.

**Default dimension by model.** When `output_dimension` is not set, the starting `dim` comes from a per-model table (and is reconciled with the real vector length on the first live call):

| Model | Default dim |
|---|---|
| `voyage-4`, `voyage-4-large`, `voyage-4-lite` | 1024 |
| `voyage-4-nano` | 512 |
| `voyage-3`, `voyage-3-large` | 1024 |
| `voyage-3-lite` | 512 |
| `voyage-finance-2`, `voyage-law-2`, `voyage-code-3`, `voyage-multilingual-2` | 1024 |
| anything else | 1024 |

**Contextualized chunks (`voyage-context-3`).** `embed_contextualized(chunks)` embeds all chunks of *one* document together, so each chunk's vector reflects its surrounding context (e.g. "he raised it to $4M" keeps its referents). It returns one vector per chunk and falls back to independent-chunk embedding if the installed SDK lacks `contextualized_embed`. `LogicaMind` uses this automatically when the embedder exposes it.

```python
emb = VoyageEmbedder(output_dimension=512)      # 512-d Matryoshka vectors
vecs = emb.embed_contextualized(["intro chunk", "next chunk", "final chunk"])
```

### `OpenAIEmbedder` (API)

OpenAI text embeddings. Lazy-imports `openai`, reads `OPENAI_API_KEY` (or `api_key=...`). The default model is `text-embedding-3-small` (1536 dims). Pass `dimensions=` to pin the output size — handy for matching an existing vector column.

```bash
pip install "logica-mind[openai]"
export OPENAI_API_KEY=...
```

```python
from logica_mind.embeddings import OpenAIEmbedder

emb = OpenAIEmbedder(model="text-embedding-3-small", dimensions=1024)  # pin to 1024
```

### `BatchedEmbedder` (rate-limit-safe wrapper)

Not a model of its own — it wraps **any** embedder to make a billed/rate-limited provider safe under load. It chunks large inputs into `batch_size` requests, enforces a minimum gap between calls, and retries transient failures with exponential backoff. Its `dim` is the inner embedder's `dim`.

```python
from logica_mind.embeddings import BatchedEmbedder, VoyageEmbedder

emb = BatchedEmbedder(VoyageEmbedder(), batch_size=128, min_interval=0.4)
```

| Argument | Default | Purpose |
|---|---|---|
| `inner` | (required) | The embedder being wrapped. |
| `batch_size` | `128` | Max texts per request. |
| `min_interval` | `0.0` | Minimum seconds between the end of one request and the start of the next (0 disables throttling). |
| `max_retries` | `4` | Retry budget. |
| `base_backoff` | `1.0` | Base seconds for exponential backoff. |

The throttle measures the gap from the **end** of one successful call to the start of the next, so it stays correct even when a single request takes longer than `min_interval`.

### `VoyageMultimodalEmbedder` (text + images)

Embeds text and images into one shared vector space, so an image and its caption land near each other. Requires `[voyage]` + `VOYAGE_API_KEY`. Default model `voyage-multimodal-3` (1024 dims).

`embed(texts)` behaves like any text embedder, so it drops straight into the normal pipeline. `embed_multimodal(inputs)` takes a list of documents, where each document is a list of content parts. Per the `voyageai` SDK contract those parts must be plain `str` and/or `PIL.Image.Image` objects — **not** OpenAI-style `{"type": "image_url", ...}` dicts. To embed an image from a URL or base64, load it into a `PIL.Image` first.

```python
from PIL import Image
from logica_mind.embeddings import VoyageMultimodalEmbedder

emb = VoyageMultimodalEmbedder()
img = Image.open("product.jpg")
vecs = emb.embed_multimodal([["a red sneaker, side view", img]])   # one vector for the pair
```

---

## Plugging an embedder into `LogicaMind`

Pass any embedder as the `embedder=` argument. Everything downstream — storing, recall, the temporal graph, the user model — uses it.

```python
from logica_mind import LogicaMind
from logica_mind.embeddings import VoyageEmbedder, BatchedEmbedder

mind = LogicaMind(
    namespace="research",
    embedder=BatchedEmbedder(VoyageEmbedder(model="voyage-3-lite"), min_interval=0.4),
)
```

> **Switching embedders on an existing store.** Different embedders produce different dimensions (256 vs 384 vs 1024 …). Mixing them yields meaningless similarities, so `LogicaMind` detects a query/stored dimension mismatch and warns you to re-embed after switching. Pick your embedder before you populate a namespace, or re-embed when you change it.

---

## The `Reranker` interface

A reranker takes the query and a candidate set that recall already retrieved, and reorders it for relevance or diversity. This is the single biggest lever on result quality: embedding retrieval is recall-oriented and a little noisy, and a good final pass sharpens the top results.

Every reranker implements one method (`logica_mind/rerank/base.py`):

```python
def rerank(
    self,
    query: str,
    results: List[SearchResult],
    top_k: int,
    query_embedding: Optional[List[float]] = None,
) -> List[SearchResult]:
    """Reorder `results` for `query` and return the top_k."""
```

By default `LogicaMind` runs **no** reranker. When you set one, recall over-fetches a larger candidate pool (`rerank_pool`, default 30), then hands the top of that pool to the reranker, which returns the final `limit` results. Rerankers own the final `.score` and populate `SearchResult.components` with a breakdown you can inspect.

---

## The five rerankers

| Reranker | `name` | Needs | What it optimizes |
|---|---|---|---|
| `MMRReranker` | `mmr` | nothing (offline) | relevance **and** diversity |
| `VoyageReranker` | `voyage-rerank` | `[voyage]` + `VOYAGE_API_KEY` | cross-encoder relevance (highest quality) |
| `RRFReranker` | `rrf` | nothing (offline) | fuses similarity + importance + recency ranks |
| `NodeDistanceReranker` | `node-distance` | a knowledge graph | proximity to query entities in the graph |
| `EpisodeMentionReranker` | `episode-mention` | nothing (offline) | frequently-recalled memories |

`VoyageReranker` is lazy-imported; the four offline rerankers import directly.

### `MMRReranker` (offline diversity)

Maximal Marginal Relevance. It balances relevance to the query against diversity among the chosen results, so the top-k isn't three paraphrases of the same fact:

```
score(d) = λ · sim(query, d) − (1 − λ) · max sim(d, already_selected)
```

It needs embeddings — the query embedding plus each candidate's embedding. If those are missing it safely returns the input order unchanged. `lambda_` (default `0.7`) tunes the relevance/diversity trade-off. It records `mmr` and `relevance` in each result's `components`.

```python
from logica_mind.rerank import MMRReranker

reranker = MMRReranker(lambda_=0.7)   # higher λ = more relevance, lower = more diversity
```

### `VoyageReranker` (cross-encoder, highest quality)

A cross-encoder reads each `(query, document)` pair jointly, so it judges relevance far more accurately than comparing independent embeddings. This is the highest-quality option. Requires `[voyage]` + `VOYAGE_API_KEY`.

It fails gracefully: with no key or library it logs a warning and keeps the incoming order rather than crashing recall, and it retries transient errors with exponential backoff. It writes a `rerank` relevance score into `components`.

```python
from logica_mind.rerank import VoyageReranker

reranker = VoyageReranker(model="rerank-2-lite")   # or "rerank-2"
```

| Argument | Default | Purpose |
|---|---|---|
| `model` | `"rerank-2-lite"` | Voyage rerank model. |
| `api_key` | `None` → `VOYAGE_API_KEY` env | API credential. |
| `max_retries` | `4` | Retry budget. |
| `base_backoff` | `2.0` | Base seconds for exponential backoff. |

### `RRFReranker` (offline rank fusion)

Reciprocal Rank Fusion. It combines several ranking signals — similarity, importance, recency — by summing `1 / (k + rank)` across each. Because it works on ranks, not raw scores, it's robust to scale differences between signals. Genuine ties share a rank (competition ranking), so equal candidates contribute equally instead of being split by emission order. It records an `rrf` score in `components`. `k` defaults to `60`.

```python
from logica_mind.rerank import RRFReranker

reranker = RRFReranker(k=60)
```

### `NodeDistanceReranker` (graph-aware)

Lifts memories that mention entities close — in the knowledge graph — to entities named in the query. It runs a bounded BFS (`max_hops`, default `2`) from each query entity and adds `weight / (1 + distance)` to matching results, recording `graph_distance` in `components`. If the query names no known entities it returns the candidates unchanged. It takes the graph as its first argument:

```python
from logica_mind.rerank import NodeDistanceReranker

reranker = NodeDistanceReranker(mind.graph, max_hops=2, weight=0.2)
```

### `EpisodeMentionReranker` (offline usage signal)

Lifts memories that have been recalled often — a proxy for how frequently an episode is mentioned. It adds `weight × min(cap, access_count)` to each result (defaults `weight=0.05`, `cap=5`) and records `mentions` in `components`.

```python
from logica_mind.rerank import EpisodeMentionReranker

reranker = EpisodeMentionReranker(weight=0.05, cap=5)
```

---

## Plugging a reranker into `LogicaMind`

Pass any reranker as `reranker=`. Tune the candidate pool with `rerank_pool`:

```python
from logica_mind import LogicaMind
from logica_mind.embeddings import LocalEmbedder
from logica_mind.rerank import MMRReranker

mind = LogicaMind(
    namespace="support",
    embedder=LocalEmbedder(),        # real semantic vectors, offline
    reranker=MMRReranker(lambda_=0.6),
    rerank_pool=30,                  # over-fetch this many candidates to rerank
)

mind.remember("Acme Inc renewed their annual plan in March.")
for hit in mind.recall("when did Acme renew?", limit=5):
    print(round(hit.score, 3), hit.memory.content, hit.components)
```

For a fully offline, real-semantic, diversity-aware setup, combine `LocalEmbedder` with `MMRReranker` — no API key required. For maximum quality on text, combine `VoyageEmbedder` with `VoyageReranker`.

---

## Choosing a combination

| Goal | Embedder | Reranker |
|---|---|---|
| Zero setup, no keys | `HashingEmbedder` (default) | none, or `RRFReranker` / `EpisodeMentionReranker` |
| Offline but real semantics | `LocalEmbedder` | `MMRReranker` |
| Highest text quality | `VoyageEmbedder` (+ `BatchedEmbedder`) | `VoyageReranker` |
| Match an existing vector column | `OpenAIEmbedder(dimensions=…)` | any |
| Text + images | `VoyageMultimodalEmbedder` | `MMRReranker` |
| Graph-heavy data | any | `NodeDistanceReranker` |

---

## See also

- [Stores](./stores.md) — where vectors and memories are persisted (SQLite default, pgvector, and more).
- [Recall and ranking](./concepts.md) — the full retrieval pipeline these plug into.
- [Configuration](./installation.md) — every `LogicaMind` constructor option.
- [Quickstart](./quickstart.md) — the zero-key 30-second start.
