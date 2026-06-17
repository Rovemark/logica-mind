"""Temporal knowledge graph, persisted through any Store.

Edges live as GRAPH-layer memories (so they're embeddable and searchable like
everything else). The temporal twist: ingesting a fact that contradicts a current
edge *closes* the old one (sets `valid_to`) instead of deleting it — so you can
ask "what is true now?" and "what was true on date X?".
"""
from __future__ import annotations

import re
import sys

from collections import defaultdict
from typing import Any, Dict, List, Optional

from ..types import Memory, MemoryLayer, now_iso
from ..stores.base import Store
from ..embeddings.base import Embedder
from .types import Edge

_ENT_RE = re.compile(r"[a-z0-9]+")


def _norm_entity(name: str) -> str:
    """Fold an entity name to a comparison key so casing/spacing/punctuation
    variants collapse onto ONE node: 'Open AI' / 'OpenAI' / 'open-ai' → 'openai'."""
    return "".join(_ENT_RE.findall((name or "").lower()))


def _edge_to_memory(edge: Edge, namespace: str) -> Memory:
    m = Memory(
        content=edge.label(),
        namespace=namespace,
        layer=MemoryLayer.GRAPH,
        importance=0.5,                        # neutral baseline; confidence lives in metadata
        metadata={
            "subject": edge.subject,
            "predicate": edge.predicate,
            "object": edge.object,
            "valid_from": edge.valid_from,
            "valid_to": edge.valid_to,
            "confidence": edge.confidence,
            "subject_type": edge.subject_type,
            "object_type": edge.object_type,
        },
        source_ids=list(edge.source_ids or []),
        tags=["edge"],
    )
    if edge.id:
        m.id = edge.id
    edge.id = m.id
    return m


def _memory_to_edge(m: Memory) -> Edge:
    md = m.metadata or {}
    return Edge(
        subject=md.get("subject", ""),
        predicate=md.get("predicate", ""),
        object=md.get("object", ""),
        fact=m.content,
        valid_from=md.get("valid_from", m.created_at),
        valid_to=md.get("valid_to"),
        confidence=md.get("confidence", 1.0),
        subject_type=md.get("subject_type", ""),
        object_type=md.get("object_type", ""),
        source_ids=list(m.source_ids or []),
        id=m.id,
    )


class TemporalGraph:
    def __init__(self, store: Store, namespace: str, embedder: Optional[Embedder] = None):
        self.store = store
        self.namespace = namespace
        self.embedder = embedder
        self._amap: Optional[Dict[str, str]] = None   # entity alias map (lazy)

    # ---- read --------------------------------------------------------------
    def edges(self, include_history: bool = False, at: Optional[str] = None) -> List[Edge]:
        """All edges. `at` (ISO timestamp) gives a point-in-time view: only edges
        that were valid at that instant — "what was true on date X"."""
        # with_embeddings=False: edges never use vectors, and parsing 384 floats per
        # row was the single biggest cost of every /api/graph request (~1.5-2s).
        mems = self.store.all(self.namespace, layers=[MemoryLayer.GRAPH], with_embeddings=False)
        # alias rows live in the GRAPH layer too — never expose them as edges
        out = [_memory_to_edge(m) for m in mems if "alias" not in (m.tags or [])]
        # ENTITY RESOLUTION at read time: canonicalize endpoints through the alias
        # map, so casing/spacing variants ('OpenAI'/'Open AI') and explicit
        # add_alias() merges collapse onto ONE node everywhere downstream (viz,
        # dimensions, co-mentions, facets) — without rewriting stored rows.
        amap = self._alias_map()
        if amap:
            for e in out:
                cs = amap.get(_norm_entity(e.subject))
                if cs and cs != e.subject:
                    e.subject = cs
                co = amap.get(_norm_entity(e.object))
                if co and co != e.object:
                    e.object = co
        if at is not None:
            return [e for e in out if e.valid_at(at)]
        if not include_history:
            out = [e for e in out if e.is_valid]
        return out

    def query(self, entity: str, include_history: bool = False, at: Optional[str] = None) -> List[Edge]:
        e = self.resolve(entity).lower()
        return [
            edge for edge in self.edges(include_history, at=at)
            if edge.subject.lower() == e or edge.object.lower() == e
        ]

    def entity_names(self) -> set:
        """Cheap projection: lowercased subject/object names of valid edges,
        read straight from metadata without building Edge objects (used by the
        entity-boost path so it doesn't materialize the whole graph per recall)."""
        names: set = set()
        for m in self.store.all(self.namespace, layers=[MemoryLayer.GRAPH]):
            if "alias" in (m.tags or []):
                continue
            md = m.metadata or {}
            if md.get("valid_to") is not None:
                continue
            for key in ("subject", "object"):
                v = md.get(key)
                if v:
                    names.add(str(v).lower())
        return names

    def neighbors(self, entity: str) -> List[str]:
        out = set()
        e = self.resolve(entity).lower()
        for edge in self.query(self.resolve(entity)):
            if edge.subject.lower() == e:
                out.add(edge.object)
            else:
                out.add(edge.subject)
        return sorted(out)

    # ---- entity resolution / aliasing --------------------------------------
    def _alias_map(self) -> Dict[str, str]:
        """norm(name) → canonical display name. Explicit aliases (persisted as
        tag='alias' rows) win; otherwise the first-seen spelling of each entity
        is canonical, so 'OpenAI' and 'Open AI' resolve to one node."""
        if self._amap is not None:
            return self._amap
        amap: Dict[str, str] = {}
        rows = self.store.all(self.namespace, layers=[MemoryLayer.GRAPH])
        for m in rows:                                    # explicit aliases first
            md = m.metadata or {}
            if "alias" in (m.tags or []) and md.get("alias_norm"):
                amap[md["alias_norm"]] = md.get("canonical") or md.get("alias_norm")
        for m in rows:                                    # then first-seen edge names
            if "alias" in (m.tags or []):
                continue
            md = m.metadata or {}
            for k in ("subject", "object"):
                v = md.get(k)
                if v:
                    amap.setdefault(_norm_entity(v), v)
        self._amap = amap
        return amap

    def resolve(self, name: str) -> str:
        """Canonical display name for an entity (alias-aware). Unknown names are
        registered as their own canonical (first-seen wins)."""
        n = _norm_entity(name)
        if not n:
            return name
        amap = self._alias_map()
        if n in amap:
            return amap[n]
        amap[n] = name
        return name

    def add_alias(self, variant: str, canonical: str) -> None:
        """Declare that `variant` is the same entity as `canonical` (e.g.
        'Robert' → 'Bob'). Persisted; subsequent ingests resolve to canonical."""
        vn, cn = _norm_entity(variant), _norm_entity(canonical)
        if not vn or not cn:
            return
        amap = self._alias_map()
        amap[vn] = canonical
        amap[cn] = canonical
        self.store.add([Memory(
            content=f"alias: {variant} → {canonical}", namespace=self.namespace,
            layer=MemoryLayer.GRAPH, tags=["alias"],
            metadata={"alias_norm": vn, "canonical": canonical, "variant": variant},
        )])

    def aliases_of(self, canonical: str) -> List[str]:
        canon = self.resolve(canonical)
        out = []
        for m in self.store.all(self.namespace, layers=[MemoryLayer.GRAPH]):
            md = m.metadata or {}
            if "alias" in (m.tags or []) and md.get("canonical") == canon and md.get("variant"):
                out.append(md["variant"])
        return sorted(set(out))

    # ---- first-class entity nodes ------------------------------------------
    def nodes(self, include_history: bool = False) -> List[Dict[str, Any]]:
        """Every entity with its degree (how many edges touch it), busiest first."""
        deg: Dict[str, int] = {}
        disp: Dict[str, str] = {}
        types: Dict[str, str] = {}
        for e in self.edges(include_history=include_history):
            for nm, ty in ((e.subject, e.subject_type), (e.object, e.object_type)):
                k = nm.lower()
                deg[k] = deg.get(k, 0) + 1
                disp.setdefault(k, nm)
                if ty and k not in types:
                    types[k] = ty
        return sorted(
            [{"name": disp[k], "degree": deg[k], "type": types.get(k, "")} for k in deg],
            key=lambda x: -x["degree"],
        )

    def entity(self, name: str, include_history: bool = False) -> Dict[str, Any]:
        """A first-class view of one entity: canonical name, type, aliases, the
        edges touching it (as subject or object) and its neighbours."""
        canon = self.resolve(name)
        cl = canon.lower()
        all_edges = [e for e in self.edges(include_history=True)
                     if e.subject.lower() == cl or e.object.lower() == cl]
        valid = [e for e in all_edges if e.is_valid]
        shown = all_edges if include_history else valid
        ety = ""
        for e in all_edges:
            ety = (e.subject_type if e.subject.lower() == cl else e.object_type) or ety
            if ety:
                break
        neighbours = sorted({(e.object if e.subject.lower() == cl else e.subject) for e in shown})
        return {
            "name": canon,
            "type": ety,
            "aliases": self.aliases_of(canon),
            "degree": len(valid),
            "degree_total": len(all_edges),
            "neighbors": neighbours,
            "facts": [e.label() for e in shown][:30],
        }

    # ---- write -------------------------------------------------------------
    def ingest(
        self,
        subject: str,
        predicate: str,
        obj: str,
        fact: str = "",
        single_valued: bool = True,
        ts: Optional[str] = None,
        confidence: float = 1.0,
        subject_type: str = "",
        object_type: str = "",
        source_ids: Optional[List[str]] = None,
    ) -> Edge:
        """Add an edge. Idempotent: an identical (subject, predicate, object)
        that is still valid is a no-op. If `single_valued`, a current edge with
        the same (subject, predicate) but a DIFFERENT object is closed (temporal
        update). `confidence` is the fact rating in [0, 1]."""
        ts = ts or now_iso()
        # resolve aliases so 'Robert' and 'Bob' land on ONE node (otherwise the
        # graph fragments and single-valued invalidation silently misses the update)
        subject, obj = self.resolve(subject), self.resolve(obj)
        s_l, p_l, o_l = subject.lower(), predicate.lower(), obj.lower()

        # single pass over the subject's edges: dedup + (optional) invalidation
        for edge in self.query(subject):
            if not edge.is_valid:
                continue
            if edge.subject.lower() != s_l or edge.predicate.lower() != p_l:
                continue
            if edge.object.lower() == o_l:
                # exact match → no-op, but merge in any new provenance source_ids
                incoming = [s for s in (source_ids or []) if s]
                if incoming:
                    existing = sorted(set(edge.source_ids or []))
                    merged = sorted(set(existing) | set(incoming))
                    if merged != existing:
                        stored = self.store.get(self.namespace, edge.id) if edge.id else None
                        if stored is not None:
                            stored.source_ids = merged       # preserves stored embedding
                            self.store.add([stored])
                        else:
                            edge.source_ids = merged
                            self.store.add([_edge_to_memory(edge, self.namespace)])
                        edge.source_ids = merged
                return edge
            if single_valued:
                # close the contradicting fact WITHOUT wiping its stored embedding:
                # round-tripping through the embedding-less Edge would rewrite the
                # row with embedding=None via INSERT OR REPLACE.
                stored = self.store.get(self.namespace, edge.id) if edge.id else None
                if stored is not None:
                    md = dict(stored.metadata or {})
                    md["valid_to"] = ts
                    stored.metadata = md
                    self.store.add([stored])
                else:
                    edge.valid_to = ts
                    self.store.add([_edge_to_memory(edge, self.namespace)])

        new_edge = Edge(subject=subject, predicate=predicate, object=obj, fact=fact,
                        valid_from=ts, confidence=confidence, subject_type=subject_type,
                        object_type=object_type, source_ids=list(source_ids or []))
        mem = _edge_to_memory(new_edge, self.namespace)
        if self.embedder is not None:
            mem.embedding = self.embedder.embed_one(mem.content)
        self.store.add([mem])
        return new_edge

    def ingest_text(self, text: str, extractor, ts: Optional[str] = None,
                    single_valued: Optional[bool] = None,
                    source_ids: Optional[List[str]] = None) -> List[Edge]:
        """Extract (subject, predicate, object) triples from prose and ingest each
        as a temporal edge. Returns new edges.

        Batch-aware: when one text yields several objects for the same
        (subject, predicate) — e.g. "Alice speaks English and Spanish" — those are
        treated as multi-valued and do NOT invalidate each other. A genuine update
        across separate texts (lives_in Paris → later Berlin) still closes the old
        edge. Pass `single_valued` to force a mode."""
        triples = list(extractor.extract(text))
        slot_objs = defaultdict(set)
        for t in triples:
            slot_objs[(t.subject.lower(), t.predicate.lower())].add(t.object.lower())
        edges: List[Edge] = []
        for t in triples:
            if single_valued is None:
                sv = len(slot_objs[(t.subject.lower(), t.predicate.lower())]) <= 1
            else:
                sv = single_valued
            edges.append(self.ingest(
                t.subject, t.predicate, t.object, fact=t.fact, single_valued=sv, ts=ts,
                confidence=t.confidence,
                subject_type=getattr(t, "subject_type", ""), object_type=getattr(t, "object_type", ""),
                source_ids=source_ids,
            ))
        return edges

    def bfs(self, start: str, depth: int = 2, include_history: bool = False) -> dict:
        """Breadth-first traversal from `start`. Returns {nodes, edges, levels}
        for everything reachable within `depth` hops (graph neighborhood)."""
        all_edges = self.edges(include_history)
        adj: dict = {}
        for e in all_edges:
            adj.setdefault(e.subject.lower(), []).append(e)
            adj.setdefault(e.object.lower(), []).append(e)

        start_l = start.lower()
        levels = {start_l: 0}
        order = [start]
        seen_edges = {}
        frontier = [start_l]
        for _ in range(max(0, depth)):
            nxt = []
            for node in frontier:
                for e in adj.get(node, []):
                    seen_edges[e.id or e.label()] = e
                    for other in (e.subject, e.object):
                        ol = other.lower()
                        if ol not in levels:
                            levels[ol] = levels[node] + 1
                            order.append(other)
                            nxt.append(ol)
            frontier = nxt
            if not frontier:
                break
        return {
            "nodes": order,
            "edges": list(seen_edges.values()),
            "levels": {n: lvl for n, lvl in levels.items()},
        }

    # ---- communities -------------------------------------------------------
    def communities(self, include_history: bool = False) -> List[dict]:
        """Connected components of the (undirected) graph — clusters of related
        entities. Each: {nodes: [...], edges: [Edge...]}. Largest first."""
        edges = self.edges(include_history)
        parent: dict = {}

        def find(x):
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        for e in edges:
            union(e.subject, e.object)

        groups: dict = {}
        for e in edges:
            groups.setdefault(find(e.subject), {"nodes": set(), "edges": []})
        for node in list(parent):
            groups.setdefault(find(node), {"nodes": set(), "edges": []})["nodes"].add(node)
        for e in edges:
            groups[find(e.subject)]["edges"].append(e)

        out = [
            {"nodes": sorted(g["nodes"]), "edges": g["edges"]}
            for g in groups.values() if g["nodes"]
        ]
        out.sort(key=lambda g: len(g["nodes"]), reverse=True)
        return out

    def summarize_communities(self, llm=None, include_history: bool = False) -> List[dict]:
        """Summarize each community. With an LLM it writes a prose summary; without
        one it lists the facts. Each: {nodes, summary}."""
        result = []
        for c in self.communities(include_history):
            facts = "\n".join(f"- {e.label()}" for e in c["edges"])
            if llm is not None and getattr(llm, "available", False) and facts:
                try:
                    summary = llm.complete(
                        f"Summarize these related facts in 1-2 sentences:\n{facts}",
                        system="You summarize a cluster of knowledge-graph facts concisely.",
                    ).strip()
                except Exception as e:
                    print(f"[logica-mind] community summary failed ({e})", file=sys.stderr)
                    summary = facts
            else:
                summary = facts
            result.append({"nodes": c["nodes"], "summary": summary})
        return result

    def to_viz(self, include_history: bool = False, at: Optional[str] = None) -> dict:
        """Nodes + links payload for the web UI graph view."""
        edges = self.edges(include_history, at=at)
        nodes = {}
        for e in edges:
            s = nodes.setdefault(e.subject, {"id": e.subject})
            if e.subject_type and "type" not in s: s["type"] = e.subject_type
            o = nodes.setdefault(e.object, {"id": e.object})
            if e.object_type and "type" not in o: o["type"] = e.object_type
        links = [
            {
                "source": e.subject,
                "target": e.object,
                "label": e.predicate,
                "valid": e.is_valid,
                "valid_from": e.valid_from,
                "valid_to": e.valid_to,
                "confidence": e.confidence,
            }
            for e in edges
        ]
        return {"nodes": list(nodes.values()), "links": links}
