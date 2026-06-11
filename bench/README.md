# Benchmarks

Two harnesses live here:

- **`locomo.py`** — judge-free *evidence recall@k*: measures the one thing a
  memory library actually controls — retrieving the right memories — with no
  LLM judge (no judge bias, no API cost).
- **`locomo_judge.py`** — the industry-standard *J score* (LLM-as-a-judge
  end-to-end QA accuracy) under the same published protocol the Mem0 paper
  used. Headline results, per-category accuracy and the full market
  comparison live in **[BENCHMARKS.md](../BENCHMARKS.md)**.

## LoCoMo — evidence recall@k

[LoCoMo](https://github.com/snap-research/locomo) (Maharana et al., 2024) ships
very-long multi-session conversations whose QA pairs list the dialogue turns
(`evidence`) that answer each question. We ingest every turn as an episodic
memory, run `recall(question, k)` and score whether any evidence turn was
retrieved.

```bash
python bench/locomo.py                    # full run, default embedder
python bench/locomo.py --embedder onnx    # pip install logica-mind[onnx]
```

### Results — full locomo10 (10 conversations, 1,982 answerable questions)

| Embedder | dims | recall@5 | recall@10 | wall time |
|---|---|---|---|---|
| `hashing` (zero-dep default) | 256 | 0.309 | 0.397 | 74s |
| **`onnx`** (MiniLM, no torch) | 384 | **0.378** | **0.477** | 272s |

Run on an Apple M3, CPU only, 2026-06-10, Logica Mind v0.3.0 defaults
(hybrid vector+lexical search, recency/importance blend, graph-aware boost).

Notes:
- The metric is conservative: a question counts as a hit only if one of its
  *annotated* evidence turns is in the top-k — paraphrases of the same
  information elsewhere in the conversation don't count.
- `onnx` gives **+22% recall@5 / +20% recall@10** over the keyless hashing
  default for ~50MB of wheels and zero API calls — that's the recommended
  upgrade for any client that can spare the download.
- `local` (sentence-transformers) produces the same vectors as `onnx` (same
  model) at ~40× the install weight; `voyage`/`openai` embedders are stronger
  still but need keys. Contributions of runs on other setups are welcome.

## LoCoMo — J score (LLM-as-a-judge)

The metric vendors publish: recall → a gpt-4o-mini answerer writes an answer
from only the retrieved memories → a gpt-4o-mini judge grades it against the
gold label. Adversarial category excluded, exactly like Mem0's published
evaluation code. Checkpointed — a flaky run never loses paid calls.

```bash
OPENAI_API_KEY=… python bench/locomo_judge.py --embedder onnx                  # zero-LLM writes
OPENAI_API_KEY=… python bench/locomo_judge.py --ingest full --k 30             # full pipeline
```

Results and methodology: **[BENCHMARKS.md](../BENCHMARKS.md)**.
