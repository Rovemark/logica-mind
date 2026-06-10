# Benchmarks

Honest, reproducible, judge-free. The harness measures the one thing a memory
library actually controls — **retrieving the right memories** — so no LLM judge
(and no judge bias / API cost) is involved.

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
  model) at ~40× the install weight; `voyage`/`openai` embeders are stronger
  still but need keys. Contributions of runs on other setups are welcome.
