"""Dreaming — sleep-time memory consolidation.

Run this periodically (cron, idle loop, or `mind.dream()`), the way a brain
consolidates during sleep. One cycle:

  1. CONSOLIDATE  distill recent episodic turns into durable semantic facts (LLM)
  2. REINFORCE    raise importance of memories that keep getting recalled
  3. DECAY/FORGET drop weak, stale, never-recalled episodic traces
  4. SYNTHESIZE   reconcile observations into the dialectic user model

Everything is graceful: with no LLM, step 1 is skipped and the rest still run.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, asdict, field
from typing import List, Optional, TYPE_CHECKING

from .types import Memory, MemoryLayer, now_iso
from ._vector import recency_score
from .core import _age_seconds

if TYPE_CHECKING:
    from .core import LogicaMind


@dataclass
class DreamReport:
    episodic_processed: int = 0
    distilled: int = 0
    graph_edges: int = 0
    reinforced: int = 0
    forgotten: int = 0
    derived: int = 0
    inferred: int = 0
    user_synthesized: bool = False
    timestamp: str = field(default_factory=now_iso)
    namespace: str = ""

    def to_dict(self):
        return asdict(self)


def _journal_path(store) -> Optional[str]:
    """Sidecar JSON file next to the SQLite DB, or None for in-memory stores."""
    p = getattr(store, "path", None)
    if not p or p in (":memory:", ""):
        return None
    base = os.path.splitext(p)[0]
    return base + "_dream_journal.json"


def save_dream(report: DreamReport, store) -> None:
    """Append a DreamReport to the sidecar dream journal file."""
    path = _journal_path(store)
    if not path:
        return
    try:
        existing = []
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        existing.append(report.to_dict())
        # keep only the last 200 dream cycles
        existing = existing[-200:]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False)
    except Exception as e:
        print(f"[logica-mind] could not save dream journal ({e})", file=sys.stderr)


def load_dreams(store, namespace: Optional[str] = None, limit: int = 50) -> List[dict]:
    """Load recent dream reports from the sidecar file."""
    path = _journal_path(store)
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            all_reports = json.load(f)
        if namespace:
            all_reports = [r for r in all_reports if r.get("namespace") == namespace or not r.get("namespace")]
        return list(reversed(all_reports[-limit:]))
    except Exception:
        return []


class Dreamer:
    def __init__(
        self,
        mind: "LogicaMind",
        episodic_batch: int = 40,
        reinforce: bool = True,
        prune: bool = True,
        prune_floor: float = 0.15,
        synthesize_user: bool = True,
        derive_user: bool = True,
        infer_links: bool = False,
        extract_graph: bool = False,
        prune_layers: Optional[List[MemoryLayer]] = None,
    ):
        self.mind = mind
        self.episodic_batch = episodic_batch
        self.do_reinforce = reinforce
        self.do_prune = prune
        self.prune_floor = prune_floor
        self.do_user = synthesize_user
        self.do_derive = derive_user
        self.do_infer = infer_links
        self.extract_graph = extract_graph
        # which layers decay/forget (configurable per-layer policy); episodic by
        # default. GRAPH and USER are NEVER raw-pruned here: hard-deleting graph
        # edges would destroy the temporal history (point-in-time / contradictions
        # rely on *closing* edges, not deleting them) and deleting USER rows would
        # wipe the dialectic model. Their lifecycle is the graph's valid_to /
        # DialecticUserModel.synthesize() / explicit forget_about().
        requested = prune_layers if prune_layers is not None else [MemoryLayer.EPISODIC]
        self.prune_layers = [l for l in requested
                             if l not in (MemoryLayer.GRAPH, MemoryLayer.USER)]
        if len(self.prune_layers) != len(requested):
            print("[logica-mind] dreaming: GRAPH/USER cannot be hard-pruned "
                  "(temporal/user invariants); ignoring those layers", file=sys.stderr)

    def run(self) -> DreamReport:
        report = DreamReport(namespace=self.mind.namespace)
        self._consolidate(report)
        if self.do_reinforce:
            self._reinforce(report)
        if self.do_prune:
            self._prune(report)
        # derive observations from recent turns BEFORE synthesizing, so the profile
        # reflects them (the deriver feeds the dialectic model)
        if self.do_derive:
            report.derived = self.mind.derive()
        if self.do_infer:
            report.inferred = self.mind.infer_links()
        if self.do_user:
            report.user_synthesized = bool(self.mind.user.synthesize())
        save_dream(report, self.mind.store)
        return report

    # ---- 1. consolidate ----------------------------------------------------
    def _consolidate(self, report: DreamReport) -> None:
        m = self.mind
        llm_ready = getattr(m.extractor, "name", "") == "llm" and getattr(m.llm, "available", False)
        # Without an LLM there is nothing to distill. Do NOT touch the batch:
        # marking it consolidated here would permanently exclude these raw turns
        # from a future LLM-enabled dream, making offline capture write-only.
        if not llm_ready:
            return
        episodic = [
            e for e in m.store.all(m.namespace, [MemoryLayer.EPISODIC])
            if not (e.metadata or {}).get("consolidated")
        ]
        batch = episodic[: self.episodic_batch]
        if not batch:
            return
        report.episodic_processed = len(batch)

        joined = "\n".join(f"- {e.content}" for e in batch)
        existing = [r.memory for r in m.store.search(m.namespace, m._embed(joined), joined, [MemoryLayer.SEMANTIC], 12)]
        facts = m.extractor.extract(joined, existing)
        source_ids = [e.id for e in batch]
        for fact in facts:
            emb = m._embed(fact.content)
            if m._find_duplicate(fact.content, emb, MemoryLayer.SEMANTIC):
                continue
            # carry the extractor's life-area categorization onto sleep-distilled
            # facts too, so a belief born in a dream is as queryable as one the
            # user stated directly (Profile, search, graph colouring, connections).
            meta = {}
            if getattr(fact, "category", None):
                meta["category"] = fact.category
            if getattr(fact, "dimension", None):
                meta["dimension"] = fact.dimension
            m.store.add([Memory(
                content=fact.content,
                namespace=m.namespace,
                layer=MemoryLayer.SEMANTIC,
                importance=max(0.5, fact.importance),
                embedding=emb,
                source_ids=source_ids,
                metadata=meta or None,
                tags=["distilled"],
            )])
            report.distilled += 1

        # optionally grow the temporal graph from the same episodic batch
        if self.extract_graph and m.graph_extractor.available:
            try:
                report.graph_edges += len(m.graph.ingest_text(joined, m.graph_extractor))
            except Exception as e:
                print(f"[logica-mind] dream graph extraction failed ({e})", file=sys.stderr)

        # mark the batch consolidated so we don't reprocess it next cycle
        for e in batch:
            e.metadata = dict(e.metadata or {})
            e.metadata["consolidated"] = True
        m.store.add(batch)

    # ---- 2. reinforce ------------------------------------------------------
    def _reinforce(self, report: DreamReport) -> None:
        m = self.mind
        changed: List[Memory] = []
        for mem in m.store.all(m.namespace):
            if mem.access_count <= 0:
                continue
            boost = min(0.30, mem.access_count * 0.02)
            new_imp = min(1.0, mem.importance + boost)
            if new_imp > mem.importance:
                mem.importance = new_imp
                changed.append(mem)
        if changed:
            m.store.add(changed)
            report.reinforced = len(changed)

    # ---- 3. decay / forget -------------------------------------------------
    def _prune(self, report: DreamReport) -> None:
        m = self.mind
        # decay/forget the configured layers (episodic by default; semantic too if
        # asked). Belt-and-suspenders even if a future caller bypasses the __init__
        # filter: never raw-delete a USER row, and never delete an OPEN graph edge
        # (valid_to is None) — those are governed by synthesize()/valid_to, not decay.
        for mem in m.store.all(m.namespace, self.prune_layers):
            if mem.layer == MemoryLayer.USER:
                continue
            if mem.layer == MemoryLayer.GRAPH and (mem.metadata or {}).get("valid_to") is None:
                continue
            rec = recency_score(_age_seconds(mem.created_at), m.half_life_days)
            strength = mem.importance * rec
            if mem.access_count == 0 and strength < self.prune_floor:
                if m.store.delete(m.namespace, mem.id):
                    report.forgotten += 1
