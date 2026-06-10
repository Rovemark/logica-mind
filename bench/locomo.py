#!/usr/bin/env python3
"""LoCoMo retrieval benchmark — evidence recall@k, no LLM judge needed.

LoCoMo (Maharana et al., 2024) ships very-long multi-session conversations with
QA pairs whose `evidence` lists the dialogue turns that answer each question.
That gives a JUDGE-FREE retrieval metric: ingest every turn as an episodic
memory, run `recall(question, k)` and score whether the evidence turns were
retrieved. It measures exactly what a memory library controls — finding the
right memories — without paying an LLM to grade answers.

Usage:
  python bench/locomo.py                       # all samples, hashing embedder
  python bench/locomo.py --embedder onnx       # pip install logica-mind[onnx]
  python bench/locomo.py --samples 3 --k 5 10

The dataset (~30MB) auto-downloads once into bench/data/locomo10.json from the
official repo (github.com/snap-research/locomo).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))          # run from the source tree

from logica_mind import LogicaMind, MemoryLayer            # noqa: E402
from logica_mind.stores import SQLiteStore                 # noqa: E402

DATA_URL = "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"
DATA_PATH = os.path.join(_HERE, "data", "locomo10.json")


def _embedder(kind: str):
    if kind == "onnx":
        from logica_mind.embeddings import OnnxEmbedder
        return OnnxEmbedder()
    if kind == "local":
        from logica_mind.embeddings import LocalEmbedder
        return LocalEmbedder()
    from logica_mind.embeddings import HashingEmbedder
    return HashingEmbedder()


def _load():
    if not os.path.exists(DATA_PATH):
        os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
        print(f"↓ downloading LoCoMo dataset → {DATA_PATH}", file=sys.stderr)
        urllib.request.urlretrieve(DATA_URL, DATA_PATH)    # nosec - fixed official host
    with open(DATA_PATH) as f:
        return json.load(f)


def run(samples=None, ks=(5, 10), embedder="hashing"):
    data = _load()
    if samples:
        data = data[:samples]
    emb = _embedder(embedder)
    totals = {k: 0 for k in ks}
    answerable = 0
    t0 = time.time()
    for si, sample in enumerate(data):
        mind = LogicaMind(store=SQLiteStore(":memory:"), embedder=emb, namespace="bench")
        conv = sample.get("conversation", {})
        speakers = {conv.get("speaker_a", "A"), conv.get("speaker_b", "B")}
        n_turns = 0
        for key, val in conv.items():
            if not isinstance(val, list):
                continue                                   # session_N only (skip *_date_time)
            for turn in val:
                txt = (turn.get("text") or "").strip()
                if not txt:
                    continue
                mind.log(f"{turn.get('speaker', '?')}: {txt}",
                         metadata={"dia_id": turn.get("dia_id"), "session": key})
                n_turns += 1
        for qa in sample.get("qa", []):
            ev = {str(e) for e in (qa.get("evidence") or [])}
            if not ev:
                continue                                   # unanswerable/adversarial → skip
            answerable += 1
            hits = mind.recall(str(qa.get("question", "")), limit=max(ks),
                               layers=[MemoryLayer.EPISODIC])
            got = [str((h.memory.metadata or {}).get("dia_id")) for h in hits]
            for k in ks:
                if any(g in ev for g in got[:k]):
                    totals[k] += 1
        print(f"[{si + 1}/{len(data)}] {n_turns} turns · "
              + " · ".join(f"R@{k} {totals[k]}/{answerable}" for k in ks), file=sys.stderr)
    out = {
        "dataset": "LoCoMo (locomo10)",
        "samples": len(data),
        "questions": answerable,
        "embedder": embedder,
        "metric": "evidence recall@k (any evidence turn retrieved)",
        **{f"recall@{k}": round(totals[k] / max(1, answerable), 4) for k in ks},
        "seconds": round(time.time() - t0, 1),
    }
    print(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=None, help="cap samples (default: all 10)")
    ap.add_argument("--k", type=int, nargs="+", default=[5, 10])
    ap.add_argument("--embedder", choices=["hashing", "onnx", "local"], default="hashing")
    a = ap.parse_args()
    run(samples=a.samples, ks=tuple(a.k), embedder=a.embedder)
