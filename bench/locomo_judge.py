#!/usr/bin/env python3
"""LoCoMo end-to-end QA accuracy (LLM-as-a-judge) — the "J score" style metric
that memory vendors publish, with the methodology fully in the open:

  ingest turns → recall(question, k) → an ANSWERER LLM answers from ONLY the
  retrieved memories → a JUDGE LLM grades the answer against the gold label.

Needs OPENAI_API_KEY (answerer + judge default to gpt-4o-mini). Checkpointed:
re-running resumes where it stopped, so a flaky run never loses paid calls.

Usage:
  OPENAI_API_KEY=… python bench/locomo_judge.py --embedder onnx
  python bench/locomo_judge.py --samples 1 --limit-qa 20     # cheap smoke run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from logica_mind import LogicaMind, MemoryLayer            # noqa: E402
from logica_mind.stores import SQLiteStore                 # noqa: E402
from locomo import _load, _embedder                        # noqa: E402

MODEL = os.environ.get("BENCH_MODEL", "gpt-4o-mini")
# Answerer+judge backend. "openai" (default, the published protocol) or
# "anthropic" to drive the same harness through any Anthropic Messages-compatible
# endpoint — reproduce the J score without an OpenAI key.
LLM_BACKEND = os.environ.get("BENCH_LLM", "openai").lower()
CKPT = None  # set per-config in run() — one checkpoint per embedder+ingest mode

ANSWER_SYS = ("You answer questions about a long conversation using ONLY the provided "
              "memory snippets. Each session header shows the date it happened — use it "
              "for time questions, and RESOLVE relative time expressions: if a memory "
              "from a session dated 15 July says 'last Friday', the event happened the "
              "Friday before 15 July (say that). You may combine memories and state the "
              "reasonable inference they imply (a likely preference, occupation, plan or "
              "situation). Be concise (a short phrase). Only reply UNKNOWN when the "
              "memories give no basis at all to answer.")
JUDGE_SYS = ("You grade an answer against the gold label for a question about a "
             "conversation. Reply with exactly one word: CORRECT if the answer conveys "
             "the same information as the gold label (paraphrase/partial date formats "
             "are fine), otherwise WRONG.")


def _chat(system: str, user: str, retries: int = 3) -> str:
    if LLM_BACKEND == "anthropic":
        return _chat_anthropic(system, user, retries)
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise SystemExit("OPENAI_API_KEY required (answerer + judge calls)")
    body = json.dumps({"model": MODEL, "temperature": 0,
                       "messages": [{"role": "system", "content": system},
                                    {"role": "user", "content": user}]}).encode()
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions", data=body,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                method="POST")
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)["choices"][0]["message"]["content"].strip()
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2.0 * (attempt + 1))
    return ""


def _chat_anthropic(system: str, user: str, retries: int = 3) -> str:
    """Answerer/judge through any Anthropic Messages-compatible endpoint
    (`BENCH_LLM=anthropic`). Lets the J harness run with no OpenAI key — set
    ANTHROPIC_API_KEY, and ANTHROPIC_BASE_URL to point at a self-hosted or proxy
    gateway instead of the public API."""
    base = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1/messages")
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise SystemExit("ANTHROPIC_API_KEY required for the anthropic backend")
    body = json.dumps({"model": MODEL, "max_tokens": 256, "temperature": 0,
                       "system": system,
                       "messages": [{"role": "user", "content": user}]}).encode()
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                base, data=body,
                headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=90) as r:
                data = json.load(r)
                return "".join(b.get("text", "") for b in data.get("content", [])
                               if b.get("type") == "text").strip()
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2.0 * (attempt + 1))
    return ""


FACTS_CACHE = os.path.join(_HERE, "data", "facts-cache.json")


def _session_facts(cache, si, sess_key, dt, turns):
    """One LLM call per SESSION distills dated, self-contained facts — the write-time
    extraction competitors do per-memory, batched per session (35x cheaper) with the
    whole session visible (coreferences resolve correctly). Disk-cached: re-runs are
    free."""
    ck = f"{si}:{sess_key}"
    if ck in cache:
        return cache[ck]
    body = "\n".join(f"{t.get('speaker', '?')}: {(t.get('text') or '').strip()}" for t in turns)
    out = _chat(
        "You extract memories from one session of a long conversation between two "
        "people. List EVERY durable fact: events, plans, purchases, preferences, "
        "relationships, health, dates. One fact per line, each self-contained with "
        "the person's NAME (never pronouns). When the fact is time-bound, resolve "
        "and include the actual date using the session date. Output only fact lines.",
        f"Session date: {dt}\n\n{body}")
    facts = [ln.strip("-• \t") for ln in out.splitlines() if ln.strip()]
    cache[ck] = facts
    json.dump(cache, open(FACTS_CACHE, "w"))
    return facts


def run(samples=None, limit_qa=None, k=10, embedder="onnx", workers=8, ingest="raw",
        radius=2, only_cats=None, via="manual", profile="balanced"):
    global CKPT
    _tag = ingest if via == "manual" else f"ctx-{profile}"
    CKPT = os.path.join(_HERE, "data", f"judge-checkpoint-{embedder}-{_tag}.json")
    data = _load()
    if samples:
        data = data[:samples]
    emb = _embedder(embedder)
    ckpt = {}
    if os.path.exists(CKPT):
        ckpt = json.load(open(CKPT))
    results = ckpt.get("results", {})
    t0 = time.time()

    for si, sample in enumerate(data):
        mind = LogicaMind(store=SQLiteStore(":memory:"), embedder=emb, namespace="bench")
        conv = sample.get("conversation", {})
        # ingest SINGLE turns (precise retrieval units that fit MiniLM's 256-token
        # window), but keep an ordered index per session so the ANSWER context can be
        # expanded with each hit's neighbouring turns — retrieve precise, read wide.
        sessions: dict = {}
        for key2, val in conv.items():
            if not isinstance(val, list):
                continue
            dt = conv.get(f"{key2}_date_time") or ""
            prefix = f"[{dt}] " if dt else ""
            turns = [t for t in val if (t.get("text") or "").strip()]
            sessions[key2] = (dt, turns)
            for idx, turn in enumerate(turns):
                mind.log(f"{prefix}{turn.get('speaker', '?')}: {(turn.get('text') or '').strip()}",
                         metadata={"dia_id": turn.get("dia_id"), "sess": key2, "idx": idx})

        def expand(hits, radius=radius):
            """answer context: each retrieved turn + its ±radius neighbours, in order."""
            picked: dict = {}
            for h in hits:
                md = h.memory.metadata or {}
                sk, idx = md.get("sess"), md.get("idx")
                if sk is None or idx is None:
                    continue
                dt, turns = sessions.get(sk, ("", []))
                for j in range(max(0, idx - radius), min(len(turns), idx + radius + 1)):
                    picked[(sk, j)] = (dt, turns[j])
            lines, last = [], None
            for (sk, j) in sorted(picked):
                dt, turn = picked[(sk, j)]
                if sk != last:
                    lines.append(f"--- session on {dt} ---")
                    last = sk
                lines.append(f"{turn.get('speaker', '?')}: {(turn.get('text') or '').strip()}")
            return "\n".join(lines)

        # category 5 = adversarial (no gold answer) — excluded from J, the SAME
        # protocol as Mem0's evaluation code (evals.py skips category=='5')
        if ingest in ("full", "supplement"):
            fcache = json.load(open(FACTS_CACHE)) if os.path.exists(FACTS_CACHE) else {}
            for key2, (dt, turns) in sessions.items():
                for f in _session_facts(fcache, si, key2, dt, turns):
                    if len(f) > 8:
                        mind.remember(f, extract=False, metadata={"sess": key2})

        # qids are the question's index in the UNFILTERED list, so checkpoints from
        # targeted runs (--only-cats) merge cleanly into a later full run
        qas_all = [qa for qa in sample.get("qa", []) if qa.get("evidence") and str(qa.get("category")) != "5"]
        qas = list(enumerate(qas_all))
        if only_cats:
            qas = [(i, qa) for i, qa in qas if str(qa.get("category")) in only_cats]
        if limit_qa:
            qas = qas[:limit_qa]

        def grade(idx_qa):
            idx, qa = idx_qa
            qid = f"{si}:{idx}"
            if qid in results:
                return None
            q = str(qa.get("question", ""))
            gold = str(qa.get("answer", ""))
            t1 = time.time()
            if via == "context":
                # CONTEXT-MODE: grade the block the PRODUCT actually injects via
                # mind.context() — exercising the whole injection path (instruction
                # frame, ratio threshold, profile, graph beam search). This is what
                # the hooks feed an agent, so it measures the injection-side wins the
                # recall-only benchmark can't see.
                mems = mind.context(q, token_budget=1800, profile=profile)
                lat_ms = (time.time() - t1) * 1000.0
                ans = _chat(ANSWER_SYS, f"{mems}\n\nQuestion: {q}")
                verdict = _chat(JUDGE_SYS, f"Question: {q}\nGold label: {gold}\nAnswer: {ans}")
                ok2 = verdict.upper().startswith("CORRECT")
                return qid, {"correct": ok2, "category": qa.get("category"),
                             "lat_ms": round(lat_ms, 1), "ctx_tokens": len(mems) // 4}
            if ingest == "supplement":
                # facts SUPPLEMENT the dialogue instead of competing with it for the
                # same top-k: the episodic retrieval is identical to raw mode, and the
                # distilled facts ride along as a separate semantic lookup — strictly
                # additive context (fixes multi-hop/open-domain without losing single-hop)
                epi = mind.recall(q, limit=k, layers=[MemoryLayer.EPISODIC])
                sem = mind.recall(q, limit=10, layers=[MemoryLayer.SEMANTIC])
            else:
                layers = None if ingest == "full" else [MemoryLayer.EPISODIC]
                hits = mind.recall(q, limit=k, layers=layers)
                sem = [h for h in hits if h.memory.layer != MemoryLayer.EPISODIC]
                epi = [h for h in hits if h.memory.layer == MemoryLayer.EPISODIC]
            lat_ms = (time.time() - t1) * 1000.0
            mems = ""
            if sem:
                mems += "Known facts:\n" + "\n".join(f"- {h.memory.content}" for h in sem) + "\n\n"
            if epi:
                mems += "Dialogue excerpts:\n" + expand(epi)
            ans = _chat(ANSWER_SYS, f"Memories:\n{mems}\n\nQuestion: {q}")
            verdict = _chat(JUDGE_SYS, f"Question: {q}\nGold label: {gold}\nAnswer: {ans}")
            ok2 = verdict.upper().startswith("CORRECT")
            if os.environ.get("BENCH_DEBUG") and not ok2:
                print(f"\n✗ Q: {q}\n  gold: {gold}\n  ans: {ans}", file=sys.stderr)
            return qid, {"correct": ok2, "category": qa.get("category"),
                         "lat_ms": round(lat_ms, 1), "ctx_tokens": len(mems) // 4}

        with ThreadPoolExecutor(max_workers=workers) as ex:
            for out in ex.map(grade, qas):
                if out:
                    results[out[0]] = out[1]
        json.dump({"results": results}, open(CKPT, "w"))
        ok = sum(1 for v in results.values() if v["correct"])
        print(f"[{si + 1}/{len(data)}] J parcial: {ok}/{len(results)} "
              f"({ok / max(1, len(results)):.1%})", file=sys.stderr)

    ok = sum(1 for v in results.values() if v["correct"])
    by_cat = {}
    for v in results.values():
        c = str(v.get("category"))
        by_cat.setdefault(c, [0, 0])
        by_cat[c][1] += 1
        if v["correct"]:
            by_cat[c][0] += 1
    lats = sorted(v.get("lat_ms", 0) for v in results.values() if v.get("lat_ms"))
    ctxs = sorted(v.get("ctx_tokens", 0) for v in results.values() if v.get("ctx_tokens"))
    pct = lambda arr, q: (arr[min(len(arr) - 1, int(q * len(arr)))] if arr else None)
    out = {
        "dataset": "LoCoMo (locomo10)", "metric": (f"LLM-judge accuracy (J), {MODEL} answerer+judge, "
                   + (f"via=context profile={profile}" if via == "context" else f"k={k}, ingest={ingest}")),
        "embedder": embedder, "questions": len(results),
        "J": round(ok / max(1, len(results)), 4),
        "J_by_category": {c: {"acc": round(a / max(1, b), 4), "n": b} for c, (a, b) in sorted(by_cat.items())},
        "retrieval_latency_ms": {"p50": pct(lats, 0.50), "p95": pct(lats, 0.95)},
        "median_context_tokens": pct(ctxs, 0.50),
        "seconds": round(time.time() - t0, 1),
    }
    print(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=None)
    ap.add_argument("--limit-qa", type=int, default=None, help="cap QA per sample (smoke runs)")
    ap.add_argument("--k", type=int, default=8, help="retrieved dialogue windows (≈8 turns each)")
    ap.add_argument("--embedder", choices=["hashing", "onnx", "local", "openai"], default="onnx")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--ingest", choices=["raw", "full", "supplement"], default="raw",
                    help="full = facts compete with turns in one top-k; supplement = "
                         "raw dialogue retrieval untouched + facts appended separately")
    ap.add_argument("--radius", type=int, default=2, help="neighbouring turns around each hit")
    ap.add_argument("--only-cats", type=str, default=None,
                    help="comma-separated category ids to score (cheap targeted runs)")
    ap.add_argument("--via", choices=["manual", "context"], default="manual",
                    help="manual = hand-assembled context (recall path); context = grade the "
                         "block mind.context() actually injects (the injection path the hooks feed)")
    ap.add_argument("--profile", choices=["speed", "balanced", "deep"], default="balanced",
                    help="context() profile when --via context")
    a = ap.parse_args()
    run(samples=a.samples, limit_qa=a.limit_qa, k=a.k, embedder=a.embedder, workers=a.workers,
        ingest=a.ingest, radius=a.radius, via=a.via, profile=a.profile,
        only_cats=set(a.only_cats.split(",")) if a.only_cats else None)
