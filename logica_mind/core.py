"""LogicaMind — the orchestrator that ties the layers together.

Public verbs: remember / log / recall / forget / observe_user / dream / serve.
Defaults are fully offline (SQLite + hashing embedder + no LLM); pass real
providers to light up semantic search, automatic extraction and the dialectic
user model.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re as _re
import sys
import time
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from .types import Memory, MemoryLayer, SearchResult
from ._vector import recency_score
from .embeddings.base import Embedder
from .embeddings.hashing import HashingEmbedder
from .stores.base import Store, _tokset, entity_tokset
from .stores.sqlite import SQLiteStore
from .extract.base import Extractor, ExtractOp
from .extract.noop import NoopExtractor
from .extract.llm import LLMExtractor
from .llm.base import LLM, NullLLM
from .graph.temporal import TemporalGraph
from .graph.extractor import GraphExtractor
from .user.dialectic import DialecticUserModel
from .rerank.base import Reranker


def _new_session_suffix() -> str:
    """A short, collision-resistant suffix for an auto-generated session id —
    no wall-clock dependency (uuid is fine and keeps record_session pure)."""
    import uuid
    return uuid.uuid4().hex[:12]


def _age_seconds(created_at: str) -> float:
    if not created_at:
        return 0.0
    try:
        ts = created_at.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, time.time() - dt.timestamp())
    except (ValueError, TypeError):
        return 0.0


_INFER_SYSTEM = (
    "You are the inductive step of a memory system's sleep-time reasoning. Given a "
    "set of known facts, infer NEW, non-obvious facts that logically follow by "
    "connecting them (transitive or combined). Return ONLY JSON: a list of short "
    "fact strings, third person. Be conservative — only high-confidence inferences. "
    "If nothing solid follows, return []."
)

_DERIVE_SYSTEM = (
    "You infer durable facts, preferences and traits about the USER from a "
    "conversation, for a theory-of-mind user model. Return ONLY JSON: a list of "
    "short observation strings, third person, about the user (e.g. "
    '["Prefers concise answers", "Works in fintech"]). '
    "Skip transient chatter and anything already covered by the existing "
    "observations. If nothing durable is revealed, return []."
)


def _flatten_content(raw) -> str:
    """A turn's content as text. Accepts a plain string or Anthropic/OpenAI-style
    content blocks ([{type:'text', text:...}, ...]); anything else → '' (skip),
    so a structured payload is never str()-coerced into a junk repr."""
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, list):
        parts = []
        for b in raw:
            if isinstance(b, str):
                parts.append(b)
            elif isinstance(b, dict) and b.get("type", "text") == "text":
                parts.append(b.get("text", ""))
        return "\n".join(p for p in parts if p).strip()
    return ""


def _norm(s: str) -> str:
    """Lower-case + collapse internal whitespace — one dedup key shared with
    recall()/ingest_json()/session_brief()."""
    return " ".join((s or "").lower().split())


def _strip_embedding(d: Dict[str, Any]) -> Dict[str, Any]:
    """Drop the embedding vector from a memory dict (for API/bundle output)."""
    d.pop("embedding", None)
    return d


def _parse_dt(s: str):
    """ISO string → tz-aware UTC datetime, or None if unparseable. Used to compare
    timestamps across stores that emit different formats (whole-second 'Z' vs the
    microsecond+offset form Postgres/Supabase return), where raw string compare is
    chronologically wrong."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


class LogicaMind:
    def __init__(
        self,
        namespace: str = "default",
        store: Optional[Store] = None,
        embedder: Optional[Embedder] = None,
        extractor: Optional[Extractor] = None,
        llm: Optional[LLM] = None,
        dedup_threshold: float = 0.92,
        weights: tuple = (0.60, 0.25, 0.15),  # similarity, importance, recency
        half_life_days: float = 7.0,
        track_access: bool = True,
        reranker: Optional["Reranker"] = None,
        rerank_pool: int = 30,
        entity_boost: float = 0.0,
    ):
        self.namespace = namespace
        self.store = store or SQLiteStore()
        self.embedder = embedder or HashingEmbedder()
        # zero-config: if no LLM was passed but a provider key is already in the
        # environment, pick it up so extraction/decomposition just turn on. Fully
        # guarded — detection never breaks construction or the offline default.
        if llm is None:
            try:
                from .providers import auto_llm
                llm = auto_llm()
            except Exception:
                llm = None
        self.llm = llm or NullLLM()
        # default extractor: LLM-based if an LLM is available, else noop
        if extractor is not None:
            self.extractor = extractor
        elif getattr(self.llm, "available", False):
            self.extractor = LLMExtractor(self.llm)
        else:
            self.extractor = NoopExtractor()

        self.dedup_threshold = dedup_threshold
        self.w_sim, self.w_imp, self.w_rec = weights
        self.half_life_days = half_life_days
        self.track_access = track_access
        self.reranker = reranker
        self.rerank_pool = rerank_pool
        self.entity_boost = entity_boost
        self._warned_dim = False

        self.graph = TemporalGraph(self.store, namespace, self.embedder)
        self.graph_extractor = GraphExtractor(self.llm)
        self.user = DialecticUserModel(self.store, namespace, self.llm, self.embedder)

    # ---- internals ---------------------------------------------------------
    def _embed(self, text: str) -> Optional[List[float]]:
        try:
            return self.embedder.embed_one(text)
        except Exception as e:
            print(f"[logica-mind] embed failed, storing text-only ({e})", file=sys.stderr)
            return None

    def _embed_query(self, text: str) -> Optional[List[float]]:
        try:
            return self.embedder.embed_query(text)
        except Exception as e:
            print(f"[logica-mind] query embed failed, falling back to lexical ({e})", file=sys.stderr)
            return None

    def _embed_many(self, texts: List[str]) -> List[Optional[List[float]]]:
        """Embed many texts in ONE provider call (batch) when possible."""
        if not texts:
            return []
        try:
            vecs = list(self.embedder.embed(texts))
        except Exception as e:
            print(f"[logica-mind] batch embed failed, storing text-only ({e})", file=sys.stderr)
            return [None] * len(texts)
        # contract guard: exactly one vector per input. A misbehaving provider
        # returning a different count would make zip() in remember() silently
        # drop facts or pair them with the WRONG embedding — fail safe instead.
        if len(vecs) != len(texts):
            print(
                f"[logica-mind] embedder returned {len(vecs)} vectors for "
                f"{len(texts)} inputs — storing text-only to avoid mis-pairing.",
                file=sys.stderr,
            )
            return [None] * len(texts)
        return vecs

    def _find_duplicate(self, content: str, embedding, layer: MemoryLayer,
                        scope_filter: Optional[Dict[str, Any]] = None) -> Optional[Memory]:
        hits = self.store.search(self.namespace, embedding, content, [layer], 1, scope_filter or None)
        if hits and hits[0].score >= self.dedup_threshold:
            return hits[0].memory
        return None

    # ---- write -------------------------------------------------------------
    def remember(
        self,
        text: str,
        layer: MemoryLayer = MemoryLayer.SEMANTIC,
        importance: float = 0.5,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        session: Optional[str] = None,
        extract: bool = True,
        build_graph: bool = False,
        category: Optional[str] = None,
    ) -> List[Memory]:
        """Store a durable fact/note. Runs extraction (add/update/
        delete/noop) + dedup, then persists. `session` scopes the memory (it is
        stored in metadata and can be filtered on at recall). With
        `build_graph=True` (and an LLM), entity/relationship triples are also
        extracted from the text into the temporal graph. Returns created."""
        text = (text or "").strip()
        if not text:
            return []

        base_meta = dict(metadata or {})
        if session:
            base_meta["session"] = session
        if category:
            base_meta["category"] = category

        # dedup is scoped to the same session (so an identical fact in another
        # session is still stored); session-less memories dedup globally
        dedup_scope = {"session": session} if session else None

        if extract:
            existing = [r.memory for r in self.store.search(
                self.namespace, self._embed_query(text), text, [layer], 12, dedup_scope or None)]
            facts = self.extractor.extract(text, existing)
        else:
            from .extract.base import Fact
            facts = [Fact(content=text, importance=importance)]

        # batch-embed all fact contents in a single provider call
        embs = self._embed_many([f.content for f in facts])

        created: List[Memory] = []
        for fact, emb in zip(facts, embs):
            # DELETE: an existing memory is now false → remove it, create nothing
            if fact.op == ExtractOp.DELETE:
                if fact.target_id:
                    self.store.delete(self.namespace, fact.target_id)
                continue

            supersedes = None
            surprise_score = 0.0
            superseded_snapshot = None
            if fact.op == ExtractOp.UPDATE and fact.target_id:
                old_mem = self.store.get(self.namespace, fact.target_id)
                if old_mem:
                    if emb and old_mem.embedding:
                        from ._vector import cosine
                        divergence = max(0.0, 1.0 - cosine(emb, old_mem.embedding))
                        surprise_score = round(old_mem.importance * divergence, 4)
                    # snapshot the belief we're replacing — the row is hard-deleted
                    # next line, so contested_beliefs()/provenance can't re-fetch it.
                    # Keeping content+importance here is what makes the temporal
                    # "what did I used to believe, and how sure was I" readable.
                    superseded_snapshot = {
                        "content": old_mem.content,
                        "importance": round(old_mem.importance, 4),
                        "created_at": old_mem.created_at,
                    }
                self.store.delete(self.namespace, fact.target_id)
                supersedes = fact.target_id
                # even on update, don't create a near-duplicate of a DIFFERENT memory
                dup = self._find_duplicate(fact.content, emb, layer, dedup_scope)
                if dup is not None and dup.id != fact.target_id:
                    continue
            else:
                dup = self._find_duplicate(fact.content, emb, layer, dedup_scope)
                if dup is not None:
                    continue  # already known

            meta = dict(base_meta)
            # carry the extractor's life-dimension categorization onto every row,
            # so categories/dimensions are queryable system-wide (search, Profile)
            if getattr(fact, "category", None) and "category" not in meta:
                meta["category"] = fact.category
            if getattr(fact, "dimension", None):
                meta["dimension"] = fact.dimension
            if supersedes:
                meta["supersedes"] = supersedes  # provenance without a dangling source_id
            if superseded_snapshot:
                meta["superseded_belief"] = superseded_snapshot

            mem = Memory(
                content=fact.content,
                namespace=self.namespace,
                layer=layer,
                importance=max(importance, fact.importance),
                tags=tags or fact.tags or [],
                metadata=meta,
                embedding=emb,
                source_ids=[],
                surprise_score=surprise_score,
            )
            self.store.add([mem])
            created.append(mem)

        if build_graph and self.graph_extractor.available:
            try:
                self.graph.ingest_text(text, self.graph_extractor)
            except Exception as e:
                print(f"[logica-mind] build_graph failed ({e})", file=sys.stderr)
        return created

    def log(
        self,
        text: str,
        role: Optional[str] = None,
        importance: float = 0.3,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        session: Optional[str] = None,
    ) -> Optional[Memory]:
        """Store a raw EPISODIC turn/event — no extraction, no dedup."""
        text = (text or "").strip()
        if not text:
            return None
        meta = dict(metadata or {})
        if role:
            meta["role"] = role
        if session:
            meta["session"] = session
        mem = Memory(
            content=text,
            namespace=self.namespace,
            layer=MemoryLayer.EPISODIC,
            importance=importance,
            tags=tags or [],
            metadata=meta,
            embedding=self._embed(text),
        )
        self.store.add([mem])
        return mem

    # ---- structured session / run records ----------------------------------
    def record_session(
        self,
        title: str,
        session_id: Optional[str] = None,
        participants: Optional[List[Dict[str, Any]]] = None,
        status: str = "completed",
        metrics: Optional[Dict[str, Any]] = None,
        links: Optional[Dict[str, str]] = None,
        tags: Optional[List[str]] = None,
        summary: Optional[str] = None,
        store_contributions: bool = True,
        importance: float = 0.7,
    ) -> Memory:
        """Record a rich, structured **session/run** as a first-class memory.

        This is the generic version of "a multi-agent task ran and here's what
        happened" — it makes no assumption about your host system (CrewAI, LangGraph,
        AutoGen…). A *participant* is anything that took part (a human, an agent,
        a clone, a tool, a model) with a free-form `role`; *metrics* and *links*
        are open dicts so any framework maps its own fields on:

            mind.record_session(
                title="Ship the installer",
                participants=[
                    {"name": "Vision", "role": "analyst", "contribution": "…", "metrics": {"score": 100}},
                    {"name": "Neo", "role": "engineer", "contribution": "…"},
                ],
                status="completed",
                metrics={"tokens": 28713, "cost_usd": 0.2058, "score": 95},
                links={"daily": "2026-04-09"},
            )

        Stores one rich **session-record** memory (a readable markdown body +
        structured metadata) plus, with `store_contributions=True`, one linked
        memory per participant contribution — all sharing `session_id`, so the
        Sessions view groups them and the record is the header. Returns the record.
        """
        sid = session_id or f"sess_{_new_session_suffix()}"
        parts = [dict(p) for p in (participants or [])]
        metrics = dict(metrics or {})
        links = dict(links or {})

        body = self._render_session_body(title, parts, status, metrics, links, summary)
        meta = {
            "session": sid,
            "record": True,
            "title": title,
            "status": status,
            "participants": [{k: p.get(k) for k in ("name", "role", "metrics") if k in p}
                             for p in parts],
            "metrics": metrics,
            "links": links,
        }
        record = Memory(
            content=body,
            namespace=self.namespace,
            layer=MemoryLayer.EPISODIC,
            importance=importance,
            tags=(tags or []) + ["session-record"],
            metadata=meta,
            embedding=self._embed(f"{title}\n{summary or ''}"),
        )
        self.store.add([record])

        # each participant's contribution becomes its own linked memory (the
        # "capsule"), discoverable as part of the session group
        if store_contributions:
            contribs = []
            for p in parts:
                c = (p.get("contribution") or "").strip()
                if not c:
                    continue
                contribs.append(Memory(
                    content=c,
                    namespace=self.namespace,
                    layer=MemoryLayer.EPISODIC,
                    importance=0.4,
                    tags=["contribution"],
                    metadata={"session": sid, "participant": p.get("name"),
                              "role": p.get("role"), "of_record": record.id},
                    embedding=self._embed(c),
                ))
            if contribs:
                self.store.add(contribs)
        return record

    @staticmethod
    def _render_session_body(title, participants, status, metrics, links, summary) -> str:
        """A readable markdown body for a session record — generic, no framework
        terms. Shown verbatim in flat stores and recall; Obsidian adds frontmatter."""
        heading = " ".join(str(title).split())          # one-line heading (no stray --- / breaks)
        lines = [f"# {heading}", ""]
        meta_bits = [f"**Status:** {status}"]
        if participants:
            meta_bits.append(f"**Participants:** {len(participants)}")
        if metrics:
            mb = " · ".join(f"{k} {v}" for k, v in metrics.items())
            meta_bits.append(f"**Metrics:** {mb}")
        lines.append(" — ".join(meta_bits))
        if summary:
            lines += ["", summary.strip()]
        if participants:
            lines += ["", "## Participants"]
            for p in participants:
                role = f" ({p['role']})" if p.get("role") else ""
                pm = p.get("metrics") or {}
                pmstr = "  ·  " + " ".join(f"{k}={v}" for k, v in pm.items()) if pm else ""
                lines.append(f"- **{p.get('name', '?')}**{role}{pmstr}")
                c = (p.get("contribution") or "").strip()
                if c:
                    excerpt = c[:240] + ("…" if len(c) > 240 else "")
                    lines.append(f"  {excerpt}")
        if links:
            lines += ["", "## Links"]
            lines += [f"- {k}: {v}" for k, v in links.items()]
        return "\n".join(lines)

    def session_record(self, session_id: str) -> Optional[Dict[str, Any]]:
        """The structured session-record header for a session id (or None). Pairs
        the metadata with its contributions for the Sessions view / API.

        If a caller re-uses an explicit `session_id` for two records, the NEWEST
        one wins (deterministic across backends — store order differs between
        SQLite/in-memory, so we pick by created_at instead of iteration order)."""
        records = []
        contributions = []
        for m in self.store.all(self.namespace, [MemoryLayer.EPISODIC]):
            md = m.metadata or {}
            if md.get("session") != session_id:
                continue
            if md.get("record"):
                records.append(m)
            elif "contribution" in (m.tags or []):
                contributions.append(m)
        if not records:
            return None
        record = max(records, key=lambda m: (m.created_at or "", getattr(m, "seq", 0)))
        out = _strip_embedding(record.to_dict())
        out["contributions"] = [_strip_embedding(c.to_dict()) for c in contributions]
        return out

    # ---- read --------------------------------------------------------------
    def recall(
        self,
        query: str,
        layers: Optional[List[MemoryLayer]] = None,
        limit: int = 8,
        session: Optional[str] = None,
        metadata_filter: Optional[Dict[str, Any]] = None,
        min_importance: float = 0.0,
        category: Optional[str] = None,
    ) -> List[SearchResult]:
        """Retrieve the most relevant memories. Pipeline: embed query → hybrid
        store search (optionally metadata/session/category-filtered) → blend
        similarity · importance · recency → dedup → optional reranker.
        `min_importance` is a fact-rating threshold (drop low-rated)."""
        query = (query or "").strip()
        if not query:
            return []
        limit = max(1, limit)   # guard: a negative limit would slice from the end

        # explicit session/category kwargs take precedence over metadata_filter,
        # but a genuine mismatch is a caller bug — fail loud instead of silently
        # shadowing it.
        flt = dict(metadata_filter or {})
        if session is not None:
            if "session" in flt and flt["session"] != session:
                raise ValueError(f"conflicting session filter: {session!r} vs "
                                 f"metadata_filter['session']={flt['session']!r}")
            flt["session"] = session
        if category is not None:
            if "category" in flt and flt["category"] != category:
                raise ValueError(f"conflicting category filter: {category!r} vs "
                                 f"metadata_filter['category']={flt['category']!r}")
            flt["category"] = category

        q_emb = self._embed_query(query)
        # overfetch enough to feed both dedup and the reranker pool
        pool_size = max(limit * 4, self.rerank_pool if self.reranker else 0)
        raw = self.store.search(self.namespace, q_emb, query, layers, pool_size, flt or None)
        self._check_dim(q_emb, raw)

        # entity-boosted retrieval: graph entities mentioned in the query lift
        # memories that also mention them (entity linking)
        boost_ents = self._query_entities(query) if self.entity_boost > 0 else set()

        reranked: List[SearchResult] = []
        for r in raw:
            sim = r.components.get("similarity", r.score)
            rec = recency_score(_age_seconds(r.memory.created_at), self.half_life_days)
            imp = r.memory.importance
            final = self.w_sim * sim + self.w_imp * imp + self.w_rec * rec
            comps = {"similarity": round(sim, 4), "importance": round(imp, 4), "recency": round(rec, 4)}
            if boost_ents:
                ctoks = _tokset(r.memory.content)
                if any(e <= ctoks for e in boost_ents):   # entity tokens present in content
                    final += self.entity_boost
                    comps["entity_boost"] = self.entity_boost
            if min_importance and imp < min_importance:
                continue                          # fact-rating threshold
            reranked.append(SearchResult(memory=r.memory, score=final, components=comps))
        reranked.sort(key=lambda x: x.score, reverse=True)

        # collapse near-identical content (e.g. the same fact logged + remembered,
        # or mirrored across stores) — keep the highest-scored instance
        seen, pool = set(), []
        for r in reranked:
            key = " ".join(r.memory.content.lower().split())
            if key in seen:
                continue
            seen.add(key)
            pool.append(r)

        if self.reranker is not None:
            # the reranker re-scores from scratch and owns the final order, so the
            # entity_boost added above doesn't affect ranking here — drop the now-
            # inert component so it isn't misleadingly advertised
            top = self.reranker.rerank(query, pool[: self.rerank_pool], limit, q_emb)
            for r in top:
                r.components.pop("entity_boost", None)
        else:
            top = pool[:limit]

        if self.track_access and top:
            try:
                # single source of truth: update-only, never writes a memory into
                # a backend that lacked it (and no double-count on stores that
                # return live objects vs copies)
                self.store.touch(self.namespace, [r.memory.id for r in top])
            except Exception:
                pass
        return top

    def _check_dim(self, q_emb, raw) -> None:
        """Warn once if stored vectors have a different dimension than the current
        embedder's query vector — a sign the embedder was swapped on existing
        data (cosine safely returns 0 for those, falling back to lexical)."""
        if self._warned_dim or not q_emb:
            return
        for r in raw:
            e = r.memory.embedding
            if e and len(e) != len(q_emb):
                print(
                    f"[logica-mind] embedder dimension mismatch: query={len(q_emb)}d "
                    f"vs stored={len(e)}d. Those memories fall back to lexical search. "
                    f"Re-embed after switching embedders.",
                    file=sys.stderr,
                )
                self._warned_dim = True
                return

    def _query_entities(self, query: str) -> set:
        """Graph-entity names mentioned in the query as WHOLE tokens (returns
        frozensets of their tokens). Token-boundary matching avoids substring
        false positives like 'AI' inside 'rain'; too-short/stopword names are
        dropped."""
        qtoks = _tokset(query)
        ents: set = set()
        try:
            for name in self.graph.entity_names():   # cheap projection, valid edges
                ntoks = entity_tokset(name)
                if ntoks and ntoks <= qtoks:          # all entity tokens present in query
                    ents.add(ntoks)
        except Exception:
            pass
        return ents

    def get(self, memory_id: str) -> Optional[Memory]:
        return self.store.get(self.namespace, memory_id)

    # ---- cross-namespace (agents / clones) ---------------------------------
    def for_namespace(self, namespace: str) -> "LogicaMind":
        """A sibling view on the same store/providers, scoped to another
        namespace — e.g. one per agent or clone."""
        child = LogicaMind(
            namespace=namespace,
            store=self.store,
            embedder=self.embedder,
            extractor=self.extractor,
            llm=self.llm,
            dedup_threshold=self.dedup_threshold,
            weights=(self.w_sim, self.w_imp, self.w_rec),
            half_life_days=self.half_life_days,
            track_access=self.track_access,
            reranker=self.reranker,
            rerank_pool=self.rerank_pool,
            entity_boost=self.entity_boost,
        )
        # carry over any customized graph/user prompts (the extractor instance is
        # already shared above); the user model stays per-namespace
        child.graph_extractor = GraphExtractor(self.llm, system=self.graph_extractor.system)
        child.user = DialecticUserModel(
            self.store, namespace, self.llm, self.embedder,
            synth_system=self.user.synth_system, query_system=self.user.query_system,
        )
        return child

    def list_namespaces(self) -> List[Dict[str, Any]]:
        """Every namespace in the store with per-layer counts (for the sidebar)."""
        out: List[Dict[str, Any]] = []
        for ns in self.store.namespaces():
            stats, total = {}, 0
            for layer in MemoryLayer:
                n = self.store.count(ns, [layer])
                stats[layer.value] = n
                total += n
            out.append({"namespace": ns, "total": total, "stats": stats})
        out.sort(key=lambda x: (-x["total"], x["namespace"]))
        return out

    def recall_across(
        self,
        query: str,
        namespaces: Optional[List[str]] = None,
        layers: Optional[List[MemoryLayer]] = None,
        limit: int = 8,
    ) -> List[SearchResult]:
        """Recall across many namespaces (or all) and merge the rankings."""
        limit = max(1, limit)   # guard: a negative limit would slice from the end
        namespaces = namespaces or self.store.namespaces()
        merged: List[SearchResult] = []
        for ns in namespaces:
            merged.extend(self.for_namespace(ns).recall(query, layers=layers, limit=limit))
        merged.sort(key=lambda r: r.score, reverse=True)
        return merged[:limit]

    def graph_viz(self, namespace: Optional[str] = None, include_history: bool = True,
                  at: Optional[str] = None, layers: Optional[List[str]] = None,
                  focus: Optional[str] = None, depth: int = 1) -> Dict[str, Any]:
        """Graph payload for the UI. A single namespace, or the *general* graph
        across all of them with shared entities flagged.

        `at` gives a point-in-time view. `layers` selects which CONNECTION kinds
        to include (relation always; "co_mention" adds emergent links from facts
        that name two entities together). `focus`+`depth` return the LOCAL graph —
        only the neighbourhood within `depth` hops of one entity. Every link
        carries a kind/weight/direction and every node a degree + centrality, so
        the canvas can speak a real edge grammar instead of one flat blue line."""
        want = set(layers) if layers is not None else {"relation", "co_mention"}

        if namespace and namespace not in ("__all__", "*", "all"):
            viz = TemporalGraph(self.store, namespace, self.embedder).to_viz(include_history, at=at)
            edim = self._entity_dimensions([namespace])
            for n in viz["nodes"]:
                n["namespaces"], n["shared"] = [namespace], False
                if n["id"] in edim:
                    n["dimension"] = edim[n["id"]]
            for l in viz["links"]:
                l["namespace"] = namespace
            node_list, links = self._finish_viz(viz["nodes"], viz["links"], [namespace], want, focus, depth)
            return {"nodes": node_list, "links": links, "namespaces": [namespace],
                    "focus": focus, "depth": depth}

        nodes: Dict[str, set] = {}
        links: List[Dict[str, Any]] = []
        all_ns = self.store.namespaces()
        for ns in all_ns:
            g = TemporalGraph(self.store, ns, self.embedder)
            for e in g.edges(include_history, at=at):
                nodes.setdefault(e.subject, set()).add(ns)
                nodes.setdefault(e.object, set()).add(ns)
                links.append({
                    "source": e.subject, "target": e.object, "label": e.predicate,
                    "valid": e.is_valid, "valid_from": e.valid_from, "valid_to": e.valid_to,
                    "confidence": e.confidence, "namespace": ns,
                })
        edim = self._entity_dimensions(all_ns)
        node_list = []
        for name, nss in nodes.items():
            n = {"id": name, "namespaces": sorted(nss), "shared": len(nss) > 1}
            if name in edim:
                n["dimension"] = edim[name]
            node_list.append(n)
        node_list, links = self._finish_viz(node_list, links, all_ns, want, focus, depth)
        return {"nodes": node_list, "links": links, "namespaces": all_ns,
                "focus": focus, "depth": depth}

    def _finish_viz(self, node_list, links, ns_scope, want, focus, depth):
        """Shared graph augmentation: tag relation links (kind/weight/direction/
        predicate-class), fold in the requested emergent layers, compute degree +
        PageRank centrality, and (optionally) clip to a focus node's local graph."""
        from .graph.analytics import pagerank, predicate_class, build_adjacency, ego_nodes
        for l in links:
            l.setdefault("kind", "relation")
            l.setdefault("directed", True)
            l.setdefault("weight", l.get("confidence", 1.0))
            if l.get("label"):
                l["pclass"] = predicate_class(l["label"])
        node_ids = {n["id"] for n in node_list}
        rel_pairs = {frozenset((l["source"], l["target"])) for l in links}
        if "co_mention" in want:
            for cm in self._co_mention_links(ns_scope):
                if cm["source"] in node_ids and cm["target"] in node_ids \
                        and frozenset((cm["source"], cm["target"])) not in rel_pairs:
                    links.append(cm)
        # degree + centrality over everything shown
        deg = {nid: 0 for nid in node_ids}
        weighted = []
        for l in links:
            if l["source"] in deg:
                deg[l["source"]] += 1
            if l["target"] in deg:
                deg[l["target"]] += 1
            weighted.append((l["source"], l["target"], l.get("weight", 1.0)))
        cen = pagerank(list(node_ids), weighted)
        for n in node_list:
            n["degree"] = deg.get(n["id"], 0)
            n["centrality"] = round(cen.get(n["id"], 0.0), 4)
        # local graph: keep only the focus node's neighbourhood within `depth` hops
        if focus and focus in node_ids:
            keep = ego_nodes(build_adjacency(weighted), focus, max(1, int(depth or 1)))
            node_list = [n for n in node_list if n["id"] in keep]
            links = [l for l in links if l["source"] in keep and l["target"] in keep]
        return node_list, links

    def _co_mention_links(self, namespaces, cooc_min: int = 2, cap_per_mem: int = 8):
        """Emergent connections: entity pairs that get TALKED ABOUT TOGETHER. One
        regex scan over each namespace's facts; a fact that names two graph
        entities votes a co-mention edge between them. No LLM, no embeddings — the
        Obsidian 'unlinked mention', but computed. Capped per memory so a giant
        note can't emit a quadratic fan of pairs."""
        import re as _re
        from collections import Counter
        ents: set = set()
        for ns in namespaces:
            for e in TemporalGraph(self.store, ns, self.embedder).edges():
                if e.subject and len(e.subject) >= 2:
                    ents.add(e.subject)
                if e.object and len(e.object) >= 2:
                    ents.add(e.object)
        if len(ents) < 2:
            return []
        lower_map = {e.lower(): e for e in ents}
        pat = _re.compile(r"\b(" + "|".join(
            _re.escape(e) for e in sorted(lower_map, key=len, reverse=True)) + r")\b")
        pair_count: Counter = Counter()
        for ns in namespaces:
            for m in self.store.all(ns):
                if "edge" in (m.tags or []) or "alias" in (m.tags or []):
                    continue
                found: List[str] = []
                seen: set = set()
                for mt in pat.finditer((m.content or "").lower()):
                    nm = lower_map.get(mt.group(1))
                    if nm and nm not in seen:
                        seen.add(nm)
                        found.append(nm)
                        if len(found) >= cap_per_mem:
                            break
                for i in range(len(found)):
                    for j in range(i + 1, len(found)):
                        a, b = sorted((found[i], found[j]))
                        pair_count[(a, b)] += 1
        return [{"source": a, "target": b, "kind": "co_mention", "directed": False,
                 "weight": c, "label": "", "valid": True}
                for (a, b), c in pair_count.items() if c >= cooc_min]

    def graph_communities(self, summarize: bool = False, include_history: bool = False):
        """Clusters of related entities in this namespace's graph. With
        summarize=True, each community gets an LLM-written summary."""
        if summarize:
            return self.graph.summarize_communities(self.llm, include_history=include_history)
        return self.graph.communities(include_history=include_history)

    # ---- forget ------------------------------------------------------------
    def forget(
        self,
        memory_id: Optional[str] = None,
        query: Optional[str] = None,
        threshold: float = 0.9,
        layers: Optional[List[MemoryLayer]] = None,
    ) -> int:
        if memory_id:
            return 1 if self.store.delete(self.namespace, memory_id) else 0
        if query:
            q_emb = self._embed_query(query)
            hits = self.store.search(self.namespace, q_emb, query, layers, 50)
            n = 0
            for h in hits:
                if h.score >= threshold:
                    n += int(self.store.delete(self.namespace, h.memory.id))
            return n
        return 0

    # ---- user model --------------------------------------------------------
    def observe_user(self, text: str) -> Optional[Memory]:
        return self.user.observe(text)

    def ingest_conversation(self, messages: List[Dict[str, Any]], session: Optional[str] = None,
                            extract: bool = True, derive: bool = True,
                            source: Optional[str] = None) -> Dict[str, int]:
        """conversation ingestion. `messages` is a list of
        {"role"/"speaker", "content"} dicts. Each turn is logged (episodic); with
        an LLM, durable facts are extracted seeing the WHOLE exchange (so a reply
        like 'sim, pode' resolves against its question), and user observations are
        derived for the dialectic model. `source` tags every captured memory with
        its origin (e.g. the MCP client name: 'claude-code', 'cursor', 'chatgpt')
        so the dashboard can show what captured it. Returns {logged, facts, observations}."""
        meta = {"source": source} if source else None
        turns = []
        for msg in messages or []:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role") or msg.get("speaker") or "user")
            raw = msg.get("content") if msg.get("content") is not None else msg.get("text")
            content = _flatten_content(raw)
            if not content:
                continue
            self.log(content, role=role, session=session, metadata=meta)
            turns.append((role, content))
        if not turns:
            return {"logged": 0, "facts": 0, "observations": 0}
        transcript = "\n".join(f"{r}: {c}" for r, c in turns)
        facts = 0
        # extract facts seeing the WHOLE exchange, but STRICT: a parse/LLM failure
        # yields zero facts, never the raw transcript blob (the turns are already
        # logged as episodic, so dropping a failed extraction loses nothing)
        if extract and isinstance(self.extractor, LLMExtractor) and getattr(self.llm, "available", False):
            strict = LLMExtractor(self.llm, max_existing=self.extractor.max_existing,
                                  system=self.extractor.system, strict=True)
            for f in strict.extract(transcript, existing=[]):
                facts += len(self.remember(f.content, session=session, metadata=meta))
        obs = self.derive(transcript=transcript, session=session) if derive else 0
        return {"logged": len(turns), "facts": facts, "observations": obs}

    def derive(self, transcript: Optional[str] = None, session: Optional[str] = None,
               window: int = 20) -> int:
        """deriver: infer durable observations about the USER from the
        conversation and feed the dialectic model. No-op offline (it needs the LLM
        to reason). Runs eagerly from ingest_conversation and lazily from dream().
        Returns the count of NEW (non-duplicate) observations stored."""
        if not getattr(self.llm, "available", False):
            return 0
        turns = None
        if transcript is None:
            # lazy/dream path: only turns not yet derived, in chronological order
            # (created_at is whole-second → tiebreak on the persisted seq)
            turns = [m for m in self.store.all(self.namespace, [MemoryLayer.EPISODIC])
                     if (not session or (m.metadata or {}).get("session") == session)
                     and not (m.metadata or {}).get("derived")]
            turns.sort(key=lambda m: (m.created_at or "", getattr(m, "seq", 0)))
            turns = turns[-window:]
            if not turns:
                return 0
            transcript = "\n".join(f"{(m.metadata or {}).get('role', 'user')}: {m.content}" for m in turns)
        existing_obs = self.user._observations()
        seen = {_norm(o.content) for o in existing_obs}
        existing_block = "\n".join(f"- {o.content}" for o in existing_obs[-20:]) or "(none)"
        prompt = (f"EXISTING OBSERVATIONS ABOUT THE USER:\n{existing_block}\n\n"
                  f"CONVERSATION:\n{transcript}\n\nReturn NEW durable observations as JSON.")
        try:
            data = self.llm.complete_json(prompt, system=_DERIVE_SYSTEM)
        except Exception as e:
            print(f"[logica-mind] derive failed ({e})", file=sys.stderr)
            return 0
        if not isinstance(data, list):
            return 0
        n = 0
        for item in data:
            obs = (item if isinstance(item, str) else str((item or {}).get("content", ""))).strip()
            key = _norm(obs)
            if not obs or key in seen:
                continue
            seen.add(key)
            self.user.observe(obs)
            n += 1
        # mark the lazy-path turns derived (even when 0 new obs) so an idle dream()
        # loop never re-calls the LLM over unchanged history
        if turns:
            for m in turns:
                m.metadata = dict(m.metadata or {})
                m.metadata["derived"] = True
            self.store.add(turns)
        return n

    def user_profile(self) -> str:
        return self.user.profile()

    def ask_about_user(self, question: str, k: int = 8) -> str:
        """Dialectic query: answer a question ABOUT the user,
        reasoning over the profile + relevant observations."""
        return self.user.query(question, k=k)

    # ---- graph from text ---------------------------------------------------
    def learn_graph(self, text: str):
        """Extract entity/relationship triples from `text` into the temporal
        graph (needs an LLM; no-op offline). Returns the new edges."""
        if not self.graph_extractor.available:
            return []
        try:
            return self.graph.ingest_text(text, self.graph_extractor)
        except Exception as e:
            print(f"[logica-mind] learn_graph failed ({e})", file=sys.stderr)
            return []

    def add_alias(self, variant: str, canonical: str) -> None:
        """Declare two entity spellings are the same node (e.g. 'Robert' → 'Bob')
        so the graph doesn't fragment and temporal invalidation still fires."""
        self.graph.add_alias(variant, canonical)

    def entity(self, name: str, include_history: bool = False) -> Dict[str, Any]:
        """First-class entity view: canonical name, type, aliases, edges, neighbours."""
        return self.graph.entity(name, include_history=include_history)

    def graph_nodes(self, include_history: bool = False) -> List[Dict[str, Any]]:
        """Every entity with its degree (how many edges touch it), busiest first."""
        return self.graph.nodes(include_history=include_history)

    def _entity_dimensions(self, namespaces: List[str]) -> Dict[str, str]:
        """Map each graph entity to its DOMINANT life/work dimension, so the
        knowledge graph can be coloured/filtered the same way the Profile is.

        Entities live in the graph; dimensions live on the categorized facts.
        We bridge them by name: a fact whose content mentions an entity votes
        its dimension for that entity; the most-voted dimension wins. Word-
        boundary matching keeps short names from over-matching."""
        import re as _re
        from collections import Counter
        # gather (content, dimension) for every categorized fact across the graphs
        facts: List[tuple] = []
        for ns in namespaces:
            for m in self.store.all(ns):
                if "edge" in (m.tags or []) or "alias" in (m.tags or []):
                    continue
                dim = (m.metadata or {}).get("dimension")
                if dim and m.content:
                    facts.append((m.content.lower(), dim))
        if not facts:
            return {}
        # the canonical entity names in play (subjects + objects of valid edges)
        ents: set = set()
        for ns in namespaces:
            for e in TemporalGraph(self.store, ns, self.embedder).edges():
                if e.subject:
                    ents.add(e.subject)
                if e.object:
                    ents.add(e.object)
        from .extract.taxonomy import group_of
        out: Dict[str, str] = {}
        for ent in ents:
            name = ent.strip()
            if len(name) < 2:
                continue
            pat = _re.compile(r"\b" + _re.escape(name.lower()) + r"\b")
            votes: Counter = Counter()
            for content, dim in facts:
                if pat.search(content):
                    votes[dim] += 1
            if not votes:
                continue
            # pick the dominant life-AREA first (a group can hold several dimensions),
            # then the busiest dimension inside it — so an entity that's mostly about
            # business reads as business even when its business facts span dimensions.
            group_votes: Counter = Counter()
            for dim, n in votes.items():
                group_votes[group_of(dim) or "personal"] += n
            top_group = group_votes.most_common(1)[0][0]
            best = max((d for d in votes if (group_of(d) or "personal") == top_group),
                       key=lambda d: votes[d])
            out[ent] = best
        return out

    # ---- observations ------------------------------------------------------
    def observations(self, limit: int = 12) -> List[Dict[str, Any]]:
        """Surface structural PATTERNS the memory has noticed — recurrences and
        co-occurrences that live across many facts, not inside any single one of
        them. Honest detection over the temporal graph: hub entities (high
        connectivity) and entity pairs that keep showing up together (shared
        neighborhoods). Returns dicts: {kind, entities, count, shared, text}."""
        from collections import Counter, defaultdict
        deg: Counter = Counter()
        neighbors: Dict[str, set] = defaultdict(set)
        for e in self.graph.edges():
            s, o = e.subject, e.object
            deg[s] += 1
            deg[o] += 1
            neighbors[s].add(o)
            neighbors[o].add(s)
        if not deg:
            return []

        # hubs: the few entities everything else hangs off of
        hubs: List[Dict[str, Any]] = []
        for ent, d in deg.most_common(5):
            if d >= 3:
                hubs.append({
                    "kind": "hub",
                    "entities": [ent],
                    "count": d,
                    "shared": sorted(neighbors[ent])[:5],
                    "text": f"{ent} is central — appears in {d} relationships",
                })

        # co-occurrence: entity pairs that keep landing in the same neighborhood
        cooc: List[Dict[str, Any]] = []
        ents = sorted(neighbors, key=lambda e: deg[e], reverse=True)
        for i in range(len(ents)):
            for j in range(i + 1, len(ents)):
                a, b = ents[i], ents[j]
                common = (neighbors[a] & neighbors[b]) - {a, b}
                if len(common) >= 2:
                    cooc.append({
                        "kind": "co_occurrence",
                        "entities": [a, b],
                        "count": len(common),
                        "shared": sorted(common)[:4],
                        "text": f"{a} and {b} recur together — {len(common)} shared connections",
                    })
        cooc.sort(key=lambda x: x["count"], reverse=True)
        return (hubs + cooc)[:limit]

    # ---- dimension profile -------------------------------------------------
    def dimensions(self) -> Dict[str, Any]:
        """The categorization profile for this namespace: every fact grouped by
        its life/work `dimension` and Maslow tier, with the open categories under
        each. Powers the dashboard Profile view and the lm_dimensions MCP tool."""
        from .extract.taxonomy import DIMENSIONS, MASLOW
        agg: Dict[str, Dict[str, Any]] = {}
        uncategorized = 0
        for m in self.store.all(self.namespace):
            md = m.metadata or {}
            dim = md.get("dimension")
            if not dim:
                uncategorized += 1
                continue
            e = agg.setdefault(dim, {"count": 0, "cats": {}})
            e["count"] += 1
            cat = md.get("category")
            if cat:
                e["cats"][cat] = e["cats"].get(cat, 0) + 1
        out = []
        for d in DIMENSIONS:
            info = agg.get(d["id"], {"count": 0, "cats": {}})
            cats = sorted(info["cats"].items(), key=lambda x: -x[1])
            out.append({"id": d["id"], "label": d["label"], "group": d["group"],
                        "maslow": d["maslow"], "count": info["count"],
                        "categories": [{"name": c, "count": n} for c, n in cats]})
        return {"dimensions": out, "uncategorized": uncategorized, "maslow": MASLOW}

    # ---- context assembly --------------------------------------------------
    @staticmethod
    def _approx_tokens(text: str) -> int:
        # rough heuristic (~4 chars/token); good enough for budgeting
        return max(1, len(text) // 4)

    def context(
        self,
        query: str,
        token_budget: int = 1500,
        layers: Optional[List[MemoryLayer]] = None,
        session: Optional[str] = None,
        include_user: bool = True,
    ) -> str:
        """Assemble a ready-to-inject context block for `query`, fitted to a
        token budget (Context endpoint): user model first, then the
        most relevant memories until the budget is spent."""
        budget = max(0, token_budget)
        blocks: List[str] = []

        # measure the FULL assembled candidate (headers + bodies + separators)
        # against the budget so the returned string actually fits it
        if include_user:
            profile = self.user_profile()
            if profile:
                block = "## User\n" + profile
                if self._approx_tokens("\n\n".join(blocks + [block])) <= budget:
                    blocks.append(block)

        chosen: List[str] = []
        for h in self.recall(query, layers=layers, limit=20, session=session):
            line = f"- {h.memory.content}"
            candidate = blocks + ["## Relevant memory\n" + "\n".join(chosen + [line])]
            if self._approx_tokens("\n\n".join(candidate)) <= budget:
                chosen.append(line)
            else:
                break
        if chosen:
            blocks.append("## Relevant memory\n" + "\n".join(chosen))
        return "\n\n".join(blocks)

    # ---- document ingestion ------------------------------------------------
    @staticmethod
    def _chunk(text: str, size: int, overlap: int) -> List[str]:
        text = (text or "").strip()
        if not text:
            return []
        size = max(1, size)              # guard: size<=0 would never advance (infinite loop)
        if len(text) <= size:
            return [text]
        overlap = max(0, min(overlap, size - 1))
        chunks, start = [], 0
        while start < len(text):
            end = start + size
            chunks.append(text[start:end])
            if end >= len(text):
                break
            start = end - overlap
        return chunks

    def ingest_document(
        self,
        text: str,
        chunk_size: int = 1000,
        overlap: int = 100,
        metadata: Optional[Dict[str, Any]] = None,
        session: Optional[str] = None,
        tags: Optional[List[str]] = None,
        build_graph: bool = False,
        extract: bool = False,
    ) -> List[Memory]:
        """Chunk a document and store each chunk as a memory (optionally
        extracting facts and graph edges per chunk). Returns all created.

        Note: byte-identical chunks are dropped by remember()'s dedup, so
        len(created) can be < the number of chunks; metadata['chunk'] is the
        SOURCE chunk index (position in the full chunk list) and may have gaps if
        duplicates were dropped."""
        created: List[Memory] = []
        chunks = self._chunk(text, chunk_size, overlap)

        # voyage-context-3: when the embedder supports it AND we're not running
        # per-chunk fact/graph extraction, embed all chunks TOGETHER so each
        # vector reflects the whole document (independent-chunk embedding is where
        # retrieval quality dies). Store the contextual vectors directly.
        ctx = None
        if chunks and not extract and not build_graph and hasattr(self.embedder, "embed_contextualized"):
            try:
                ctx = self.embedder.embed_contextualized(chunks)
            except Exception as e:
                print(f"[logica-mind] contextual embed fell back to per-chunk ({e})", file=sys.stderr)
                ctx = None

        if ctx is not None and len(ctx) == len(chunks):
            base_meta = dict(metadata or {})
            if session:
                base_meta["session"] = session
            dedup_scope = {"session": session} if session else None
            for i, (ch, emb) in enumerate(zip(chunks, ctx)):
                if self._find_duplicate(ch, emb, MemoryLayer.SEMANTIC, dedup_scope):
                    continue
                meta = dict(base_meta)
                meta["chunk"] = i
                mem = Memory(content=ch, namespace=self.namespace, layer=MemoryLayer.SEMANTIC,
                             tags=(tags or []) + ["document", "contextual"], metadata=meta, embedding=emb)
                self.store.add([mem])
                created.append(mem)
            return created

        for i, ch in enumerate(chunks):
            meta = dict(metadata or {})
            meta["chunk"] = i
            created += self.remember(
                ch, layer=MemoryLayer.SEMANTIC,
                tags=(tags or []) + ["document"], metadata=meta,
                session=session, extract=extract, build_graph=build_graph,
            )
        return created

    # ---- structured ingestion ---------------------------------------------
    @staticmethod
    def _flatten_json(obj, prefix: str = "") -> List[str]:
        out: List[str] = []
        if isinstance(obj, dict):
            if not obj and prefix:
                out.append(f"{prefix} = {{}}")        # record empty container fact
            for k, v in obj.items():
                out += LogicaMind._flatten_json(v, f"{prefix}.{k}" if prefix else str(k))
        elif isinstance(obj, list):
            if not obj and prefix:
                out.append(f"{prefix} = []")
            for i, v in enumerate(obj):
                out += LogicaMind._flatten_json(v, f"{prefix}[{i}]")
        else:
            out.append(f"{prefix} = {obj}" if prefix else str(obj))
        return out

    def ingest_json(self, obj, session: Optional[str] = None,
                    tags: Optional[List[str]] = None, max_items: int = 200) -> List[Memory]:
        """Flatten a JSON object/array into `path = value` facts and store them
        (business-data ingestion). Dedups on EXACT normalized string —
        not embedding cosine — so distinct short/numeric values (ids, codes) are
        never collapsed and never accidentally kept twice. Returns created."""
        norm = lambda s: " ".join(s.lower().split())
        seen = {norm(m.content) for m in self.store.all(self.namespace, [MemoryLayer.SEMANTIC])
                if (not session) or (m.metadata or {}).get("session") == session}
        meta = {"session": session} if session else {}
        created: List[Memory] = []
        for line in self._flatten_json(obj)[:max_items]:
            key = norm(line)
            if key in seen:
                continue
            seen.add(key)
            mem = Memory(content=line, namespace=self.namespace, layer=MemoryLayer.SEMANTIC,
                         importance=0.5, tags=(tags or []) + ["json"], metadata=dict(meta),
                         embedding=self._embed(line))
            self.store.add([mem])
            created.append(mem)
        return created

    # ---- reflection --------------------------------------------------------
    def reflect(self, window: int = 30, store_result: bool = True) -> str:
        """Synthesize insights from recent memories ('what changed / what's
        notable'). With an LLM it reasons; offline it returns the recent digest."""
        mems = self.store.all(self.namespace, [MemoryLayer.SEMANTIC])
        # most important first, then recent; dedup by content so a fact repeated
        # across many days shows once (an insight digest, not a raw dump)
        mems.sort(key=lambda m: (m.importance, m.created_at or ""), reverse=True)
        seen, recent = set(), []
        for m in mems:
            c = (m.content or "").strip()
            if not c or c in seen or "reflection" in (m.tags or []):
                continue
            seen.add(c)
            recent.append(m)
            if len(recent) >= window:
                break
        if not recent:
            return ""
        facts = "\n".join(f"- {m.content}" for m in recent)
        if getattr(self.llm, "available", False):
            try:
                text = self.llm.complete(
                    f"Recent things learned:\n{facts}\n\nWrite 2-3 concise insights about "
                    f"what changed or what's notable.",
                    system="You synthesize concise insights from a set of recent memories.",
                ).strip()
            except Exception as e:
                print(f"[logica-mind] reflect fell back ({e})", file=sys.stderr)
                text = facts
        else:
            text = facts
        if store_result and text:
            # skip writing an identical reflection (offline digest is stable)
            last = next((m for m in mems if "reflection" in (m.tags or [])), None)
            if last is None or last.content != text:
                self.store.add([Memory(
                    content=text, namespace=self.namespace, layer=MemoryLayer.SEMANTIC,
                    importance=0.7, tags=["reflection"], embedding=self._embed(text),
                )])
        return text

    # ---- dreaming ----------------------------------------------------------
    def dream(self, **kwargs):
        """Run a sleep-time consolidation cycle. See logica_mind.dreaming."""
        from .dreaming import Dreamer
        return Dreamer(self, **kwargs).run()

    def session_brief(self, limit: int = 10, token_budget: int = 1200) -> str:
        """A digest to inject at the start of a session: what we know about the
        user + the most important things from past sessions. Used by the
        SessionStart hook (there's no query yet, so rank by importance/recency)."""
        budget = max(0, token_budget)
        blocks: List[str] = []

        def _fits(candidate):
            return self._approx_tokens("\n\n".join(candidate)) <= budget

        def _fit_section(header, items):
            # add whole lines only while they fit — never cut mid-line, never
            # emit a header with no body
            chosen: List[str] = []
            for line in items:
                if _fits(blocks + [header + "\n" + "\n".join(chosen + [line])]):
                    chosen.append(line)
                else:
                    break
            return (header + "\n" + "\n".join(chosen)) if chosen else None

        def _dedup(mems):
            seen, out = set(), []
            for m in mems:
                key = " ".join(m.content.lower().split())
                if key in seen:
                    continue
                seen.add(key)
                out.append(m)
            return out

        prof = self.user_profile()
        if prof:
            block = "## What I know about you\n" + prof
            if _fits(blocks + [block]):
                blocks.append(block)

        # semantic facts, importance-ranked (survive even if old)
        sem = self.store.all(self.namespace, [MemoryLayer.SEMANTIC])
        sem.sort(key=lambda m: (m.importance, m.created_at or ""), reverse=True)
        sem_block = _fit_section("## From past sessions",
                                 [f"- {m.content}" for m in _dedup(sem)[:limit]])
        if sem_block:
            blocks.append(sem_block)

        # recent raw activity (episodic) — what we were doing last, deduped and
        # chronological, even if never distilled (offline / no-LLM case)
        eps = self.store.all(self.namespace, [MemoryLayer.EPISODIC])
        eps.sort(key=lambda m: m.created_at or "", reverse=True)
        ep_lines = [f"- {m.content[:200]}" for m in _dedup(eps)[:limit]]
        ep_block = _fit_section("## Recent activity", list(reversed(ep_lines)))
        if ep_block:
            blocks.append(ep_block)

        return "\n\n".join(blocks)

    # ---- introspection -----------------------------------------------------
    def stats(self) -> Dict[str, int]:
        out = {"total": 0}
        for layer in MemoryLayer:
            n = self.store.count(self.namespace, [layer])
            out[layer.value] = n
            out["total"] += n
        return out

    # ---- async API ---------------------------------------------------------
    # Thin wrappers that run the (blocking) verbs in a thread, so Logica Mind can
    # be used from async apps without holding the event loop.
    async def aremember(self, *args, **kwargs) -> List[Memory]:
        return await asyncio.to_thread(self.remember, *args, **kwargs)

    async def alog(self, *args, **kwargs) -> Optional[Memory]:
        return await asyncio.to_thread(self.log, *args, **kwargs)

    async def arecall(self, *args, **kwargs) -> List[SearchResult]:
        return await asyncio.to_thread(self.recall, *args, **kwargs)

    async def aforget(self, *args, **kwargs) -> int:
        return await asyncio.to_thread(self.forget, *args, **kwargs)

    async def acontext(self, *args, **kwargs) -> str:
        return await asyncio.to_thread(self.context, *args, **kwargs)

    async def aask_about_user(self, *args, **kwargs) -> str:
        return await asyncio.to_thread(self.ask_about_user, *args, **kwargs)

    # ---- export / import / migrate -----------------------------------------
    def export(self, layers: Optional[List[MemoryLayer]] = None) -> List[Dict[str, Any]]:
        """Dump this namespace's memories as plain dicts (for backup/transfer)."""
        return [m.to_dict() for m in self.store.all(self.namespace, layers)]

    def import_memories(self, records: List[Dict[str, Any]]) -> int:
        """Load memories from dicts (as produced by export()) into the store."""
        mems = []
        for r in records:
            try:
                mems.append(Memory.from_dict(r))
            except Exception:
                continue
        if mems:
            self.store.add(mems)
        return len(mems)

    def migrate_to(self, dst_store: Store, layers: Optional[List[MemoryLayer]] = None) -> int:
        """Copy this namespace's memories into another store (e.g. SQLite → Supabase)."""
        mems = self.store.all(self.namespace, layers)
        if mems:
            dst_store.add(mems)
        return len(mems)

    # ---- peers / multi-perspective --------------------------
    def observe_peer(self, observer: str, observed: str, text: str, importance: float = 0.6) -> Optional[Memory]:
        """Record what `observer` learned about `observed` — a directional
        (observer→observed) observation, so each peer builds its own theory of
        another (not just the system's view of 'the user')."""
        text = (text or "").strip()
        if not text:
            return None
        m = Memory(
            content=text, namespace=self.namespace, layer=MemoryLayer.USER, importance=importance,
            tags=["peer-observation"], metadata={"observer": observer, "observed": observed},
            embedding=self._embed(text),
        )
        self.store.add([m])
        return m

    def _peer_obs(self, observer: str, observed: str) -> List[Memory]:
        obs = [m for m in self.store.all(self.namespace, [MemoryLayer.USER])
               if (m.metadata or {}).get("observer") == observer
               and (m.metadata or {}).get("observed") == observed]
        # store.all() ordering is backend-defined; sort so obs[-30:] is really the
        # NEWEST 30 on SQLite/Postgres/Supabase, not an arbitrary slice
        obs.sort(key=lambda m: m.created_at or "")
        return obs

    def peer_card(self, observer: str, observed: str) -> str:
        """A directional card: what `observer` knows about `observed`."""
        obs = self._peer_obs(observer, observed)
        if not obs:
            return ""
        facts = "\n".join(f"- {o.content}" for o in obs[-30:])
        if getattr(self.llm, "available", False):
            try:
                return self.llm.complete(
                    f"OBSERVATIONS that {observer} has of {observed}:\n{facts}\n\n"
                    f"Write a concise card describing what {observer} knows/believes about {observed}.",
                    system="You build a concise directional profile of one party as seen by another.",
                ).strip()
            except Exception as e:
                print(f"[logica-mind] peer_card fell back ({e})", file=sys.stderr)
        return facts

    def peer_query(self, observer: str, observed: str, question: str) -> str:
        """Ask what `observer` would say about `observed` (theory-of-mind query)."""
        card = self.peer_card(observer, observed)
        if getattr(self.llm, "available", False) and card:
            try:
                return self.llm.complete(
                    f"WHAT {observer} KNOWS ABOUT {observed}:\n{card}\n\nQUESTION: {question}",
                    system="Answer from one party's perspective of another; say what's unknown if unsupported.",
                ).strip()
            except Exception as e:
                print(f"[logica-mind] peer_query fell back ({e})", file=sys.stderr)
        return card

    # ---- differentiators / moats -------------------------------------------
    def contradictions(self) -> List[Dict[str, Any]]:
        """Facts that CHANGED over time — graph slots (subject, predicate) that
        had multiple objects, with the temporal history. The 'what did I believe
        and when did it change' audit trail no flat memory store has."""
        from collections import defaultdict
        slots = defaultdict(list)
        for e in self.graph.edges(include_history=True):
            slots[(e.subject, e.predicate)].append(e)
        out = []
        for (subj, pred), edges in slots.items():
            if len({e.object for e in edges}) > 1:
                edges.sort(key=lambda e: e.valid_from or "")
                out.append({"subject": subj, "predicate": pred, "history": [
                    {"object": e.object, "valid_from": e.valid_from, "valid_to": e.valid_to,
                     "current": e.is_valid} for e in edges]})
        return out

    def diff(self, since: str, until: Optional[str] = None,
             layers: Optional[List[MemoryLayer]] = None) -> List[Dict[str, Any]]:
        """What was learned in a time window [since, until] — a memory changelog."""
        out = []
        since_dt, until_dt = _parse_dt(since), _parse_dt(until)
        for m in self.store.all(self.namespace, layers):
            if "alias" in (m.tags or []):       # internal entity-alias rows aren't "learned facts"
                continue
            c = m.created_at or ""
            if not c:
                continue
            c_dt = _parse_dt(c)
            if c_dt is not None and since_dt is not None:
                # format-agnostic, chronologically correct comparison
                if c_dt >= since_dt and (until_dt is None or c_dt <= until_dt):
                    out.append({"content": m.content, "layer": m.layer.value, "created_at": c})
            elif c >= since and (until is None or c <= until):
                # unparseable row/boundary → degrade to lexical compare, never crash
                out.append({"content": m.content, "layer": m.layer.value, "created_at": c})
        _epoch = datetime.min.replace(tzinfo=timezone.utc)
        out.sort(key=lambda x: _parse_dt(x["created_at"]) or _epoch)
        return out

    def forget_about(self, entity: str) -> int:
        """GDPR-style erase: delete every memory mentioning `entity` (any layer)
        and every graph edge touching it. Returns the number removed."""
        ent = (entity or "").strip().lower()
        if not ent:
            return 0
        # match on whole tokens, not substrings, so "ana" never erases "banana".
        ent_toks = _tokset(ent)
        n = 0
        for m in self.store.all(self.namespace):
            md = m.metadata or {}
            mentions = bool(ent_toks) and ent_toks <= _tokset(m.content)
            if (mentions
                    or str(md.get("observed", "")).lower() == ent
                    or str(md.get("subject", "")).lower() == ent
                    or str(md.get("object", "")).lower() == ent):
                n += int(self.store.delete(self.namespace, m.id))
        return n

    def purge(self) -> int:
        """Delete every memory in this namespace (a hard reset)."""
        return self.store.delete_layers(self.namespace)

    def transfer_to(self, dst, query: str, limit: int = 10) -> int:
        """Cross-agent knowledge transfer: copy facts matching `query` from this
        namespace into another mind/namespace, tagged with their origin."""
        dst_mind = dst if isinstance(dst, LogicaMind) else self.for_namespace(str(dst))
        n = 0
        for h in self.recall(query, limit=limit):
            src = h.memory
            # preserve the source fact-rating — otherwise every transferred fact
            # flattens to remember()'s default 0.5, corrupting recall ranking and
            # the min_importance threshold on the destination
            n += len(dst_mind.remember(
                src.content,
                importance=src.importance,
                tags=list(dict.fromkeys((src.tags or []) + ["transferred"])),
                metadata={"from": self.namespace}, extract=False))
        return n

    # ---- moats: provenance / replay / gap / decay / bundles ----------------
    def provenance(self, memory_id: str) -> Dict[str, Any]:
        """Why do I believe this? Trace a memory back to the source turns/documents
        it was distilled from (via source_ids) + what it superseded. The 'show your
        work' that flat vector stores can't give."""
        m = self.store.get(self.namespace, memory_id)
        if not m:
            return {}
        sources = [self.store.get(self.namespace, sid) for sid in (m.source_ids or [])]
        return {
            "memory": m.to_dict(),
            "from": [s.to_dict() for s in sources if s],
            "supersedes": (m.metadata or {}).get("supersedes"),
        }

    def connections(self, memory_id: str, limit: int = 8) -> Dict[str, Any]:
        """Backlinks, but DERIVED — no manual [[wikilinks]] to maintain. For one
        memory we surface, automatically: (a) the graph entities it mentions, each
        typed and carrying its life-area; (b) the relations touching those
        entities; (c) other memories that mention the same entities (the auto-
        backlink); and (d) sibling facts sharing its category/dimension. Obsidian
        makes you author links by hand — here the connective tissue is inferred."""
        import re as _re
        m = self.store.get(self.namespace, memory_id)
        if not m:
            return {}
        md = m.metadata or {}
        low = (m.content or "").lower()
        g = self.graph
        nodes = g.nodes()                                   # [{name, degree, type}]
        deg_by = {nd["name"].lower(): nd for nd in nodes}

        # (a) entities this memory mentions — an edge names them directly; a fact
        # is matched on a word boundary so short names don't over-match.
        mentioned: List[str] = []
        if "edge" in (m.tags or []) and (md.get("subject") or md.get("object")):
            for nm in (md.get("subject"), md.get("object")):
                if nm and nm not in mentioned:
                    mentioned.append(nm)
        else:
            for nd in nodes:
                nm = nd["name"]
                if len(nm) >= 2 and _re.search(r"\b" + _re.escape(nm.lower()) + r"\b", low):
                    mentioned.append(nm)
        mentioned = mentioned[:12]
        ment_low = {nm.lower() for nm in mentioned}
        edim = self._entity_dimensions([self.namespace]) if mentioned else {}
        entities = [{
            "name": nm, "degree": deg_by.get(nm.lower(), {}).get("degree", 0),
            "type": deg_by.get(nm.lower(), {}).get("type", ""), "dimension": edim.get(nm),
        } for nm in mentioned]

        # (b) typed relations touching those entities
        relations: List[Dict[str, Any]] = []
        if ment_low:
            for e in g.edges():
                if e.subject.lower() in ment_low or e.object.lower() in ment_low:
                    relations.append({"subject": e.subject, "predicate": e.predicate,
                                      "object": e.object, "valid": e.is_valid, "id": e.id})
        relations = relations[:limit]

        # (c) auto-backlinks + (d) siblings — single pass over the namespace
        cat, dim = md.get("category"), md.get("dimension")
        mentions: List[Memory] = []
        siblings: List[Memory] = []
        for other in self.store.all(self.namespace):
            if other.id == m.id or "edge" in (other.tags or []) or "alias" in (other.tags or []):
                continue
            ol = (other.content or "").lower()
            if ment_low and any(_re.search(r"\b" + _re.escape(e) + r"\b", ol) for e in ment_low):
                mentions.append(other)
                continue
            omd = other.metadata or {}
            if (cat and omd.get("category") == cat) or (dim and omd.get("dimension") == dim):
                siblings.append(other)

        def trim(lst: List[Memory]):
            lst.sort(key=lambda x: x.created_at or "", reverse=True)
            return [_strip_embedding(x.to_dict()) for x in lst[:limit]]

        return {"entities": entities, "relations": relations,
                "mentions": trim(mentions), "siblings": trim(siblings)}

    def state_at(self, at: str, layers: Optional[List[MemoryLayer]] = None) -> List[Dict[str, Any]]:
        """Memory replay: everything the agent knew at a past instant — what it
        believed when it made a decision. Filters by created_at and, for graph
        edges, their valid window (so closed edges vanish from the past view)."""
        at_dt = _parse_dt(at)
        out = []
        for m in self.store.all(self.namespace, layers):
            c_dt = _parse_dt(m.created_at)
            if c_dt is None or at_dt is None:
                if not (m.created_at and m.created_at <= at):
                    continue
            elif c_dt > at_dt:
                continue
            if m.layer == MemoryLayer.GRAPH:
                md = m.metadata or {}
                vf, vt = md.get("valid_from"), md.get("valid_to")
                if vf and vf > at:
                    continue
                if vt and vt <= at:
                    continue
            out.append(m)
        out.sort(key=lambda m: m.created_at or "")
        return [_strip_embedding(m.to_dict()) for m in out]

    def knowledge_gap(self, other, limit: int = 50) -> List[Dict[str, Any]]:
        """What `other` knows that THIS namespace doesn't — cross-agent knowledge
        gap (e.g. 'what does agent-a know that agent-b doesn't?'). Content-keyed."""
        dst = other if isinstance(other, LogicaMind) else self.for_namespace(str(other))
        mine = {_norm(m.content) for m in self.store.all(self.namespace, [MemoryLayer.SEMANTIC])}
        gap = [m for m in dst.store.all(dst.namespace, [MemoryLayer.SEMANTIC])
               if _norm(m.content) not in mine]
        gap.sort(key=lambda m: m.importance, reverse=True)
        return [{"content": m.content, "importance": m.importance} for m in gap[:limit]]

    def stale_beliefs(self, min_age_days: float = 30.0, limit: int = 20) -> List[Dict[str, Any]]:
        """Epistemic self-doubt: durable facts that are OLD, never recalled, and
        decayed below confidence — beliefs the agent should re-verify ('not sure
        about this anymore'). No memory system surfaces its own uncertainty."""
        out = []
        for m in self.store.all(self.namespace, [MemoryLayer.SEMANTIC]):
            age_days = _age_seconds(m.created_at) / 86400.0
            rec = recency_score(_age_seconds(m.created_at), self.half_life_days)
            conf = round(m.importance * rec, 3)
            if age_days >= min_age_days and m.access_count == 0:
                out.append({"id": m.id, "content": m.content,
                            "age_days": round(age_days, 1), "confidence": conf})
        out.sort(key=lambda x: x["confidence"])
        return out[:limit]

    def export_bundle(self, secret: Optional[str] = None,
                      layers: Optional[List[MemoryLayer]] = None) -> Dict[str, Any]:
        """Portable, signed memory bundle — move YOUR memory between apps/vendors
        (Claude → Cursor → ChatGPT). Optionally HMAC-signed so the destination can
        verify it wasn't tampered with. Provider-independent memory, which nobody
        else ships."""
        mems = [_strip_embedding(m.to_dict()) for m in self.store.all(self.namespace, layers)]
        payload = {"v": 1, "namespace": self.namespace, "count": len(mems), "memories": mems}
        body = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest() if secret else None
        return {"payload": payload, "signature": sig}

    def import_bundle(self, bundle: Dict[str, Any], secret: Optional[str] = None,
                      verify: bool = True) -> int:
        """Import a (signed) memory bundle into this namespace. Verifies the HMAC
        signature when a secret is given. Re-embeds missing vectors. Returns count."""
        payload = bundle.get("payload") or {}
        if verify and secret is not None:
            body = json.dumps(payload, sort_keys=True, ensure_ascii=False)
            expect = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expect, str(bundle.get("signature") or "")):
                raise ValueError("bundle signature verification failed — refusing import")
        n = 0
        for d in payload.get("memories", []):
            try:
                m = Memory.from_dict(d)
            except Exception:
                continue
            m.namespace = self.namespace
            if not m.embedding:
                m.embedding = self._embed(m.content)
            self.store.add([m])
            n += 1
        return n

    def infer_links(self, max_new: int = 5) -> int:
        """Inductive dreaming: connect existing graph facts into NEW inferred facts
        (A→B, B→C ⟹ A relates to C) via the LLM, at rest. Stored as low-confidence
        'inferred' semantic memories. Generative synthesis — not just consolidation.
        Offline = no-op. Returns the count of new inferences."""
        if not getattr(self.llm, "available", False):
            return 0
        edges = self.graph.edges()
        if len(edges) < 2:
            return 0
        facts = "\n".join(f"- {e.label()}" for e in edges[:60])
        prompt = (f"KNOWN FACTS:\n{facts}\n\nInfer up to {max_new} new facts that follow "
                  f"by connecting these. Return JSON list of fact strings.")
        try:
            data = self.llm.complete_json(prompt, system=_INFER_SYSTEM)
        except Exception as e:
            print(f"[logica-mind] infer_links failed ({e})", file=sys.stderr)
            return 0
        if not isinstance(data, list):
            return 0
        seen = {_norm(m.content) for m in self.store.all(self.namespace, [MemoryLayer.SEMANTIC])}
        n = 0
        for item in data:
            f = (item if isinstance(item, str) else str((item or {}).get("content", ""))).strip()
            if not f or _norm(f) in seen:
                continue
            seen.add(_norm(f))
            self.remember(f, importance=0.4, tags=["inferred"], extract=False)
            n += 1
        return n

    @staticmethod
    def redact_pii(text: str) -> str:
        """Mask emails / phone numbers / long digit runs — a light privacy guard
        for recall output in shared contexts."""
        text = _re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "[email]", text or "")
        text = _re.sub(r"\+?\d[\d ()\-]{7,}\d", "[phone]", text)
        return text

    # ---- Ebbinghaus forgetting curve ----------------------------------------
    def forget_curve(
        self, days_halflife: float = 30.0, apply: bool = False, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Return beliefs sorted by how much they'll decay in the next 7 days.

        Ebbinghaus: retention R = exp(-t / halflife) where t is time since last
        recall (or creation). If apply=True, actually lower importance scores.
        Nobody else exposes this — most systems treat memory as an immutable DB.
        """
        import math

        at_risk: List[Dict[str, Any]] = []
        to_update: List[Memory] = []
        now_ts = time.time()
        halflife_s = days_halflife * 86400.0

        for m in self.store.all(self.namespace, [MemoryLayer.SEMANTIC, MemoryLayer.EPISODIC]):
            ref_at = m.last_recalled_at or m.created_at or ""
            age_s = max(0.0, now_ts - (
                datetime.fromisoformat(ref_at.replace("Z", "+00:00")).timestamp()
                if ref_at else now_ts
            ))
            retention = math.exp(-age_s / halflife_s)
            future_age_s = age_s + 7 * 86400.0
            future_retention = math.exp(-future_age_s / halflife_s)
            at_risk.append({
                "id": m.id,
                "content": m.content,
                "current_retention": round(retention, 3),
                "current_strength": round(m.importance * retention, 3),
                "projected_strength_7d": round(m.importance * future_retention, 3),
                "days_since_recall": round(age_s / 86400.0, 1),
                "importance": round(m.importance, 3),
                "layer": m.layer.value,
            })
            if apply:
                new_imp = max(0.05, m.importance * retention)
                if abs(new_imp - m.importance) > 0.005:
                    m.importance = new_imp
                    to_update.append(m)

        if apply and to_update:
            self.store.add(to_update)

        at_risk.sort(key=lambda x: x["projected_strength_7d"])
        return at_risk[:limit]

    # ---- contested beliefs --------------------------------------------------
    def contested_beliefs(self, confidence_threshold: float = 0.65) -> List[Dict[str, Any]]:
        """Return pairs of beliefs that contradict each other AND both had high
        confidence — epistemic contests where neither side can be dismissed.
        This is honesty: the system admits it holds conflicting beliefs.

        The superseded belief is read from the `superseded_belief` snapshot in the
        new memory's metadata (the old row is hard-deleted on UPDATE), falling back
        to a live `store.get(supersedes)` for older data written before snapshots.
        """
        out: List[Dict[str, Any]] = []
        for m in self.store.all(self.namespace, [MemoryLayer.SEMANTIC]):
            if m.importance < confidence_threshold:
                continue
            md = m.metadata or {}
            snap = md.get("superseded_belief")
            old_content = old_importance = old_dict = None
            if snap:
                old_content = snap.get("content")
                old_importance = snap.get("importance", 0.0)
                old_dict = {"content": old_content, "importance": old_importance,
                            "created_at": snap.get("created_at", "")}
            elif md.get("supersedes"):
                old = self.store.get(self.namespace, md["supersedes"])
                if old:
                    old_content, old_importance = old.content, old.importance
                    old_dict = _strip_embedding(old.to_dict())
            if old_dict is None or (old_importance or 0.0) < confidence_threshold:
                continue
            out.append({
                "current": _strip_embedding(m.to_dict()),
                "superseded": old_dict,
                "confidence_new": round(m.importance, 3),
                "confidence_old": round(old_importance or 0.0, 3),
                "surprise_score": round(getattr(m, "surprise_score", 0.0), 3),
            })
        out.sort(key=lambda x: x["surprise_score"], reverse=True)
        return out

    # ---- surprise events ----------------------------------------------------
    def surprise_events(self, since: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        """Return beliefs that surprised the system when stored — paradigm shifts.
        surprise_score = old_confidence × cosine_distance(old_vec, new_vec).
        High-surprise events are the most valuable for debugging agent behavior."""
        out: List[Dict[str, Any]] = []
        for m in self.store.all(self.namespace, [MemoryLayer.SEMANTIC]):
            ss = getattr(m, "surprise_score", 0.0) or 0.0
            if ss <= 0.0:
                continue
            if since and (m.created_at or "") < since:
                continue
            d = _strip_embedding(m.to_dict())
            d["surprise_score"] = round(ss, 3)
            out.append(d)
        out.sort(key=lambda x: x["surprise_score"], reverse=True)
        return out[:limit]

    # ---- web ---------------------------------------------------------------
    def serve(self, host: str = "127.0.0.1", port: int = 8420, open_browser: bool = True):
        """Launch the self-hosted dashboard (blocking)."""
        from .web.server import serve
        serve(self, host=host, port=port, open_browser=open_browser)

    def close(self) -> None:
        self.store.close()
