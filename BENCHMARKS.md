# Benchmarks for agent memory

Honest numbers, open methodology, one-command reproduction. This page reports
how Logica Mind scores on the public benchmarks the agent-memory industry uses
— and explains, with sources, why vendor headline numbers are rarely
comparable to each other.

> **TL;DR** — on LoCoMo under the *same published protocol the Mem0 paper used*
> (gpt-4o-mini answerer **and** judge, adversarial category excluded), Logica
> Mind's **full pipeline scores 72.5%** — above every memory system in the
> published protocol (Mem0ᵍ 68.4%, Mem0 66.9%, Zep 66.0%) and within 0.4pt of
> the full-context ceiling (72.9%), while paying **one LLM call per session**
> at write time (~35× fewer than per-write extraction pipelines). With **zero
> LLM calls at write time** it still scores **67.3%** — above Mem0 and Zep —
> and fully keyless (local ONNX, no API at all) it scores **60.9%**, matching
> the best RAG baseline with **87ms p50** local retrieval and $0 per write.

---

## LoCoMo — full run (locomo10, 1,540 scored questions)

| Mode | **accuracy (J)** | **retrieval latency** | **median context** |
|---|---|---|---|
| **full pipeline** (1 LLM call per *session* at write) | **72.5%** | 1,606 / 2,859 ms (p50/p95)³ | 3,525 tokens |
| zero-LLM writes, `openai` embedder (text-embedding-3-small) | **67.3%** | 584 / 1,452 ms (p50/p95)³ | 2,648 tokens |
| zero-LLM writes, `onnx` embedder (**no API keys at all**) | **60.9%** | 87 / 338 ms (p50/p95) | 2,738 tokens |

³ The `openai`/full-pipeline rows embed each query over the network (the full
pipeline runs two lookups per question: dialogue + facts), measured while the
benchmark hammered the machine with 8 concurrent workers — latency is dominated
by API round-trips, not the library. The `onnx` row is fully in-process: that's
the latency the library itself is responsible for.

**Accuracy by question category** (official locomo10 category mapping¹):

```text
full pipeline · session distillation at write  — overall 72.5%
single-hop    █████████████████░░░  83.5%   (702/841)
temporal      ██████████████░░░░░░  70.7%   (227/321)
multi-hop     ███████████░░░░░░░░░  53.2%   (150/282)
open-domain   ███████░░░░░░░░░░░░░  37.0%   (34/92)

zero-LLM writes · openai embedder              — overall 67.3%
single-hop    █████████████████░░░  82.9%   (697/841)
temporal      ████████████░░░░░░░░  60.4%   (194/321)
multi-hop     █████████░░░░░░░░░░░  43.3%   (122/282)
open-domain   ████░░░░░░░░░░░░░░░░  21.7%   (20/92)

zero-LLM writes · onnx embedder (keyless)      — overall 60.9%
single-hop    ███████████████░░░░░  74.7%   (628/841)
temporal      ███████████░░░░░░░░░  56.7%   (182/321)
multi-hop     ███████░░░░░░░░░░░░░  36.5%   (103/282)
open-domain   █████░░░░░░░░░░░░░░░  25.0%   (23/92)
```

For reference, Mem0's published per-category numbers (same protocol,
[Table 1](https://arxiv.org/html/2504.19413v1)): single-hop 67.1%, temporal
55.5%, multi-hop 51.2%, open-domain 72.9%. The full pipeline **beats Mem0 on
single-hop (+16.4pts), temporal (+15.2pts) and multi-hop (+2.0pts)**;
open-domain remains their stronghold (it rewards broad world-knowledge
synthesis) — even after the pipeline nearly doubled our score there. Zero-LLM
writes already beat them on single-hop and temporal with no ingestion cost at
all.

---

## Why zero-LLM writes beat the extraction pipelines

Scoring 67.3% — above Mem0 (66.9%) and Zep (66.0%) — *without paying an LLM
per memory written* isn't luck. Three design decisions do the work:

**1. Distillation loses detail; raw turns keep it.**
Mem0, Zep, LangMem and OpenAI Memory all run every incoming message through an
LLM at write time and store the *summary*. But 55% of LoCoMo's scored
questions are single-hop — the answer sits verbatim in one dialogue turn, with
its exact wording, number or date. A distilled fact has often thrown that
detail away; the raw turn never does. That's the single-hop gap: **82.9% vs
Mem0's 67.1%**. Logica Mind's strategy is *retrieve precise, read wide*: every
turn is stored as its own memory (a precise retrieval unit that fits the
embedder's window), and the answer context expands each hit with its ±2
neighbouring turns, in conversation order, so the answerer sees the local
dialogue — not an isolated fragment.

**2. Time is a first-class column, not an afterthought.**
Every memory carries its session date (the same reason the knowledge graph is
*temporal*), and the answerer is instructed to resolve relative time — a
memory dated 15 July saying "last Friday" means the Friday before 15 July.
Temporal questions: **60.4% vs Mem0's published 55.5%** — and temporal memory
is the product Zep sells.

**3. The economics are not a footnote.**
Ingesting LoCoMo means ~26,000 dialogue turns. Per-write extraction pipelines
pay an LLM call (plus latency, plus a third party seeing your data) for every
one of them. Logica Mind pays **zero** — ingestion is free, private and local
— and still scores higher. The optional full pipeline pays **one call per
session** (~350 for all of LoCoMo, ~35× fewer), not one per write.

**Where extraction does win** — and we say so: in zero-LLM mode, multi-hop
(43.3% vs 51.2%) and open-domain (21.7% vs 72.9%), questions whose answer must
be *synthesized across many turns*. A distilled fact base can pre-join what
raw turns keep apart. The full pipeline buys exactly that back — multi-hop
jumps to 53.2% (now above Mem0) and open-domain nearly doubles to 37.0% —
**without giving up the raw-turn advantage** (single-hop holds at 83.5%).

**A negative result we publish anyway:** the *obvious* full-pipeline design —
let distilled facts and raw turns compete in one top-k — scores **63.1%**,
*worse than not extracting at all* (67.3%). Facts rank high semantically and
crowd the precise dialogue turns out of the retrieval budget, killing the
single-hop advantage. The design that wins (72.5%) keeps the dialogue
retrieval untouched and *appends* facts as a separate lookup. If you're
building a memory system: extraction is only worth its cost when it
supplements raw evidence instead of replacing it.

The shape is exactly what zero-LLM ingestion predicts: questions answerable from
retrieved dialogue (single-hop, temporal) score high; questions that need facts
*synthesized across many turns* (multi-hop, open-domain) are where write-time
distillation earns its cost — that's what the **full pipeline** row measures.

¹ Verified against the dataset itself: category 1 = multi-hop (282), 2 =
temporal (321), 3 = open-domain (96 in the dataset; 92 carry evidence
annotations and are scored), 4 = single-hop (841); category 5 = adversarial
(446) has no gold answers and is excluded — the same exclusion
[hard-coded in Mem0's evaluation code](https://github.com/mem0ai/mem0/blob/main/evaluation/evals.py).

**Protocol** (matches the [Mem0 paper](https://arxiv.org/abs/2504.19413)
family): ingest the conversation, `recall(question, k)` → answer with
**gpt-4o-mini** from only the retrieved context → grade with a **gpt-4o-mini**
judge against the gold label. Two write-time modes are reported:

- **zero-LLM writes** (k=20): every dialogue turn stored raw (speaker +
  session date), no LLM at ingestion — the free/private/local trade.
- **full pipeline** (k=20 dialogue + 10 facts, ±3 neighbours): Logica Mind's
  LLM extraction distills durable facts at write time — **one call per
  session** (~35× fewer LLM calls than per-memory extraction pipelines). The
  facts *supplement* the dialogue retrieval instead of competing with it for
  the same top-k: the answer context is the same dialogue the zero-LLM mode
  retrieves, plus the 10 most relevant distilled facts appended separately.

```bash
python bench/locomo.py --embedder onnx                        # retrieval-only (free)
OPENAI_API_KEY=… python bench/locomo_judge.py --embedder openai          # zero-LLM writes (~$3)
OPENAI_API_KEY=… python bench/locomo_judge.py --embedder openai \
    --ingest supplement --k 20 --radius 3                     # full pipeline (~$4)
```

---

## How this compares — published numbers, same protocol family

LoCoMo **J score** with gpt-4o-mini answering, adversarial excluded, as
**published in the [Mem0 paper, Table 1](https://arxiv.org/html/2504.19413v1)**
(±, Letta's from [their blog](https://www.letta.com/blog/benchmarking-ai-agent-memory)):

| System | LoCoMo J | LLM at write time | Source |
|---|---|---|---|
| Letta (filesystem agent) | 74.0% | agent-managed | [Letta blog](https://www.letta.com/blog/benchmarking-ai-agent-memory) |
| Full-context baseline (no memory system) | 72.9% | — | [Mem0 paper](https://arxiv.org/html/2504.19413v1) |
| **Logica Mind (full pipeline: session distillation at write)** | **72.5%** | **yes — 1 call per session, ~35× fewer calls** | this page |
| Mem0ᵍ (graph variant) | 68.4% | yes, every write | [Mem0 paper](https://arxiv.org/html/2504.19413v1) |
| **Logica Mind (zero-LLM ingestion, openai embedder)** | **67.3%** | **no** | this page |
| Mem0 | 66.9% | yes, every write | [Mem0 paper](https://arxiv.org/html/2504.19413v1) |
| Zep (as measured by Mem0 — disputed²) | 66.0% | yes, every write | [Mem0 paper](https://arxiv.org/html/2504.19413v1) |
| Best RAG baseline | 61.0% | no | [Mem0 paper](https://arxiv.org/html/2504.19413v1) |
| **Logica Mind (zero-LLM ingestion, onnx embedder — fully keyless memory)** | **60.9%** | **no** | this page |
| LangMem | 58.1% | yes | [Mem0 paper](https://arxiv.org/html/2504.19413v1) |
| OpenAI Memory | 52.9% | yes | [Mem0 paper](https://arxiv.org/html/2504.19413v1) |
| A-Mem | 48.4% | yes | [Mem0 paper](https://arxiv.org/html/2504.19413v1) |

² **The Zep number is publicly disputed.** Mem0 measured Zep at 66.0% and
[filed an issue](https://github.com/getzep/zep-papers/issues/5) arguing Zep's
earlier 84% claim improperly included the adversarial category (recomputing it
as 58.4%); Zep [rebutted](https://blog.getzep.com/lies-damn-lies-statistics-is-mem0-really-sota-in-agent-memory/)
alleging misconfiguration and reported 75.1% for itself under its own re-run.
Both can't be right — which is exactly why this page pins every number to its
source and protocol.

### About the much bigger numbers on vendor sites

[Zep's research page](https://www.getzep.com/research/) reports **94.7%** on
LoCoMo and [Mem0's README](https://github.com/mem0ai/mem0) reports **91.6%**
(April 2026, "new algorithm"). These are **self-reported, post-paper numbers
under each vendor's own methodology** (different answerer models, judges,
retrieval budgets and dataset corrections), not peer-reviewed and not
comparable to the table above — note both vendors' *peer-comparable* numbers
in the published protocol are in the 60s. Letta showed a **plain filesystem
agent scores 74.0%** ([blog](https://www.letta.com/blog/benchmarking-ai-agent-memory)),
and the full-context baseline (72.9%) beats most memory systems — LoCoMo
conversations average only ~16–26k tokens, so the honest reading is:
**LoCoMo measures retrieval quality, not memory magic.** That's also
[Zep's own criticism](https://blog.getzep.com/lies-damn-lies-statistics-is-mem0-really-sota-in-agent-memory/)
of the benchmark.

### What memory systems actually sell: latency & token cost

The Mem0 paper's own argument: full-context costs **17.1s p95** end-to-end vs
1.4s with memory — the value is latency/cost, not accuracy. On that axis:

| System | Search latency (published) | Where memory lives |
|---|---|---|
| **Logica Mind (onnx, fully local)** | **87ms p50 / 338ms p95 (measured, this run)** | in-process, local SQLite |
| Zep (cloud) | 87–104ms p50 / 155–162ms p95 ([site](https://www.getzep.com/research/)) | network service |
| Mem0 | 148ms p50 / 200ms p95 ([paper](https://arxiv.org/html/2504.19413v1)) | network service |
| LangMem | 17,990ms p50 ([Mem0 paper](https://arxiv.org/html/2504.19413v1)) | store-dependent |

Logica Mind's retrieval is a local hybrid search — no network hop, no per-call
billing, and **$0 per memory written** (competing pipelines invoke an LLM on
every write: that's the cost curve they don't put on the landing page).

---

## Positioning — verified, with sources (June 2026)

| | **Logica Mind** | Mem0 | Zep / Graphiti | Letta | LangMem |
|---|---|---|---|---|---|
| License (OSS) | Apache-2.0 | Apache-2.0 | Apache-2.0 (Graphiti engine) | Apache-2.0 | MIT |
| Core install | **zero dependencies** | requires `openai` + `posthog` (telemetry) ([pyproject](https://raw.githubusercontent.com/mem0ai/mem0/main/pyproject.toml)) | needs Neo4j/FalkorDB/Neptune/Kuzu ([repo](https://github.com/getzep/graphiti)) | Postgres + pgvector ([docs](https://docs.letta.com/guides/docker/postgres/)) | 8 langchain-* deps ([pyproject](https://github.com/langchain-ai/langmem/blob/main/pyproject.toml)) |
| Works with no API key | **yes (hashing/onnx + heuristic extraction)** | no (LLM extraction at write) | no (LLM required at ingestion) | no (agent LLM) | no |
| Temporal knowledge graph | **yes, OSS** (point-in-time replay, fact invalidation) | removed from OSS; temporal = paid Platform v3 ([docs](https://docs.mem0.ai/platform/features/temporal-reasoning)) | yes (Graphiti, bi-temporal) | no (blocks + archival) | no |
| Self-hosted dashboard | **yes — 15 languages, graph explorer, zero services** | bundled with self-hosted server (needs OPENAI_API_KEY + JWT) | cloud only (server OSS deprecated) | ADE connects via HTTPS/cloud ([docs](https://docs.letta.com/guides/ade/overview/)) | none |
| Self-host status | first-class | supported (docker) | Graphiti yes; Zep server OSS **deprecated** | Docker image **deprecated** ([docs](https://docs.letta.com/guides/docker/)) | SDK only |
| Cloud pricing | — (self-host) | $19–$249/mo ([pricing](https://mem0.ai/pricing)) | free tier; Flex ~$104/mo | app.letta.com | via LangGraph Platform |

*(GitHub stars, 2026-06-10, via API: Mem0 58.3k · Graphiti 27.3k · Letta 23.2k
· LangMem 1.5k.)*

---

## Methodology notes & honesty policy

- Every external number above links to its primary source; nothing is
  estimated. When sources conflict (Zep×Mem0), both sides are shown.
- Our runs: Apple M4 (CPU), Logica Mind v0.3.x defaults, hybrid vector+lexical
  search + recency/importance blend + graph-aware boost; dialogue turns
  ingested raw (speaker + session date), answer context = retrieved turns plus
  neighbouring turns (±2 in the zero-LLM runs, ±3 in the full pipeline);
  ~$3-4 of gpt-4o-mini for answer+judge per full run.
- The answerer prompt is part of the system under test (as in every published
  pipeline): the zero-LLM runs used a strict answer-from-memories prompt; the
  full-pipeline run additionally allows stating the reasonable inference the
  memories imply. The judge prompt is identical across all runs.
- Known limitation we don't hide: with **zero LLM at write time** there is no
  fact distillation at ingestion, so multi-hop/open-domain questions suffer —
  that is the trade those rows sell (free, private, local writes). The **full
  pipeline** rows measure what the optional write-time extraction buys back,
  at 1 LLM call per session instead of per memory.
- **Two retrieval paths, both measurable.** The numbers above grade
  `recall()` / the supplement path — the raw search the score has always
  tracked. The 0.4.x injection features (performance profiles, the `safe=True`
  instruction frame, pin/snooze, the ratio cutoff) shape `context()`, the
  *assembled* block a hook injects into a prompt — a different path. So the
  judge harness takes `--via context --profile {speed,balanced,deep}` and grades
  that assembled block directly, otherwise injection-side changes would be
  invisible to the score.
- **The injection path costs no measurable accuracy, at ~27% fewer tokens.**
  On a keyless control (onnx embedder, a Claude-Haiku judge through a local
  Anthropic gateway, **180 paired questions**), `context()` at the `balanced`
  profile is statistically indistinguishable from raw recall — **38.9% vs 42.2%,
  McNemar p≈0.44** (24 questions flip one way, 18 the other: chance) — while the
  assembled block carries **~27% fewer context tokens** (≈920 vs ≈1,260). The
  safety frame and the low-score-tail cutoff buy that token saving without a
  significant hit to answer quality; the only mild skew is open-domain, which
  rewards a larger window. (This control uses a Claude judge and the keyless
  embedder, so its absolute J sits below the gpt-4o-mini headline rows — what it
  isolates is the *delta* between the two retrieval paths, not the leaderboard
  number.)
- Reproduce everything: `bench/locomo.py` (retrieval, free) and
  `bench/locomo_judge.py` (J score). With an OpenAI key it runs the published
  protocol; with `BENCH_LLM=anthropic` (any Anthropic Messages endpoint, incl. a
  self-hosted or proxy gateway) it reproduces a keyless J — no OpenAI key needed.
  The injection path: `bench/locomo_judge.py --via context --profile balanced`.
