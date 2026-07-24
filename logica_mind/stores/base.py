"""Store interface + shared ranking helpers.

A Store is *where memory lives*. The interface is deliberately small so a backend
can be a local file, SQLite, Postgres/pgvector, a markdown vault, or a cloud API.

Helpers here let any in-process store do a decent hybrid (vector + lexical) rank
without duplicating math. Backends that have native vector search (Supabase) can
ignore them and push the work into the database.
"""
from __future__ import annotations

import math
import re
from abc import ABC, abstractmethod
from typing import List, Optional, Sequence

from ..types import Memory, MemoryLayer, SearchResult
from .._vector import cosine

_TOKEN_RE = re.compile(r"[a-zà-ÿ0-9]{2,}", re.IGNORECASE)


def _tokset(text: str) -> set:
    return {t.lower() for t in _TOKEN_RE.findall(text)}


def _tokens(text: str) -> List[str]:
    """Tokens WITH repetition (BM25 needs term frequencies, not just presence)."""
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def bm25_scores(query: str, docs: Sequence[str], k1: float = 1.5, b: float = 0.75) -> List[float]:
    """Okapi BM25 over a candidate batch, normalized to [0, 1] so it blends with
    cosine. Term frequency + IDF + length normalization beat plain Jaccard overlap
    on corpora with repeated/rare terms and varying lengths. IDF is computed over
    the candidate set (not the whole corpus) — an approximation that's correct for
    re-ranking a recall pool and needs no global stats."""
    n = len(docs)
    qtoks = _tokset(query)
    if not n or not qtoks:
        return [0.0] * n
    doc_toks = [_tokens(d) for d in docs]
    df: dict = {}
    for dt in doc_toks:
        for t in set(dt):
            df[t] = df.get(t, 0) + 1
    avgdl = (sum(len(dt) for dt in doc_toks) / n) or 1.0
    out: List[float] = []
    for dt in doc_toks:
        dl = len(dt) or 1
        tf: dict = {}
        for t in dt:
            tf[t] = tf.get(t, 0) + 1
        s = 0.0
        for t in qtoks:
            f = tf.get(t)
            if not f:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / avgdl))
        out.append(s)
    mx = max(out) or 1.0
    return [s / mx for s in out]


# entity names too short/common to use for entity-linking (avoid 'ai' ∈ 'rain')
_BOOST_STOP = {"the", "a", "an", "is", "of", "to", "in", "on", "it", "us",
               "and", "or", "ai", "do"}


def entity_tokset(name: str):
    """Tokens of a graph-entity name, or None if it shouldn't be used for
    entity-linking (empty / <3 chars / stopword). Single policy shared by the
    entity-boost (core) and the NodeDistanceReranker so they never diverge."""
    nl = (name or "").strip()
    if not nl or len(nl) < 3 or nl.lower() in _BOOST_STOP:
        return None
    ts = frozenset(_tokset(nl))
    return ts or None


def lexical_score(query: str, content: str) -> float:
    """Jaccard token overlap in [0, 1] — the no-embedding fallback."""
    q, c = _tokset(query), _tokset(content)
    if not q or not c:
        return 0.0
    inter = len(q & c)
    if not inter:
        return 0.0
    return inter / len(q | c)


def similarity(memory: Memory, query_embedding: Optional[Sequence[float]], query_text: str) -> float:
    """Best available similarity for one memory, always in [0, 1].

    Falls back to lexical overlap when there is no vector OR when the two
    vectors have different dimensions (e.g. the embedder was swapped on existing
    data). The lexical fallback keeps dedup and recall working during a migration
    instead of silently returning 0 for every legacy memory."""
    if (
        query_embedding
        and memory.embedding
        and len(query_embedding) == len(memory.embedding)
    ):
        return max(0.0, cosine(query_embedding, memory.embedding))
    return lexical_score(query_text, memory.content)


def matches_filter(memory: Memory, metadata_filter: Optional[dict]) -> bool:
    """True if the memory's metadata matches every key/value in the filter.

    A list value means "metadata[key] is one of these". Used for scoping recall
    by session/run or any custom attribute."""
    if not metadata_filter:
        return True
    md = memory.metadata or {}
    for k, v in metadata_filter.items():
        actual = md.get(k)
        if isinstance(v, (list, tuple, set)):
            if actual not in v:
                return False
        elif actual != v:
            return False
    return True


def apply_filter(memories: Sequence[Memory], metadata_filter: Optional[dict]) -> List[Memory]:
    if not metadata_filter:
        return list(memories)
    return [m for m in memories if matches_filter(m, metadata_filter)]


def rank(
    memories: Sequence[Memory],
    query_embedding: Optional[Sequence[float]],
    query_text: str,
    limit: int,
) -> List[SearchResult]:
    """Rank a candidate set by similarity. Final importance/recency weighting is
    applied later by the core; stores return raw similarity so the core can
    re-rank consistently across backends.

    Vector path: cosine. No-vector path: BM25 over the candidate batch (computed
    once for all candidates, since BM25 needs cross-document term statistics)."""
    mems = list(memories)
    # which candidates can use a vector vs need the lexical fallback
    use_vec = [
        bool(query_embedding) and bool(m.embedding) and len(query_embedding) == len(m.embedding)
        for m in mems
    ]
    lex = bm25_scores(query_text, [m.content for m in mems]) if not all(use_vec) else None
    # PERF: cosseno de TODOS os candidatos vetoriais numa única operação BLAS (numpy) em vez de um
    # loop Python O(N×D) chamando cosine() por memória. Com max_candidates=5000 × 384d o loop puro
    # pendurava o recall em dezenas de segundos (o /api/recall travava >45s → cegava o resto). numpy
    # já vem via sentence-transformers; sem ele, cai no caminho antigo (paridade). Semântica idêntica.
    vec = _batch_cosine(query_embedding, mems, use_vec)
    scored = []
    for i, m in enumerate(mems):
        if use_vec[i]:
            s = vec[i]
        else:
            s = lex[i] if lex is not None else 0.0
        if s <= 0.0:
            continue
        scored.append(SearchResult(memory=m, score=s, components={"similarity": round(s, 4)}))
    scored.sort(key=lambda r: r.score, reverse=True)
    return scored[:limit]


def _batch_cosine(query_embedding, mems, use_vec):
    """Cosseno de todos os candidatos com use_vec de uma vez (numpy) → {i: score em [0,1]}.
    Fallback puro-Python (idêntico ao loop antigo) se numpy não estiver disponível."""
    idxs = [i for i in range(len(mems)) if use_vec[i]]
    if not idxs:
        return {}
    try:
        import numpy as np
    except Exception:
        return {i: max(0.0, cosine(query_embedding, mems[i].embedding)) for i in idxs}
    M = np.asarray([mems[i].embedding for i in idxs], dtype=np.float32)   # (K, D)
    q = np.asarray(query_embedding, dtype=np.float32)                     # (D,)
    dots = M @ q
    denom = np.linalg.norm(M, axis=1) * np.linalg.norm(q)
    with np.errstate(divide="ignore", invalid="ignore"):
        cos = np.where(denom > 0.0, dots / denom, 0.0)
    cos = np.clip(cos, 0.0, None)   # espelha o max(0.0, ...) do cosine() original
    return {idxs[k]: float(cos[k]) for k in range(len(idxs))}


class Store(ABC):
    """Abstract storage backend."""

    name: str = "store"

    @abstractmethod
    def add(self, memories: List[Memory]) -> None:
        """Insert or upsert (by id) a batch of memories."""

    @abstractmethod
    def search(
        self,
        namespace: str,
        query_embedding: Optional[List[float]],
        query_text: str,
        layers: Optional[List[MemoryLayer]] = None,
        limit: int = 20,
        metadata_filter: Optional[dict] = None,
    ) -> List[SearchResult]:
        """Return up to `limit` candidates ranked by raw similarity, optionally
        restricted to memories whose metadata matches `metadata_filter`."""

    @abstractmethod
    def get(self, namespace: str, memory_id: str) -> Optional[Memory]:
        ...

    @abstractmethod
    def delete(self, namespace: str, memory_id: str) -> bool:
        ...

    @abstractmethod
    def all(self, namespace: str, layers: Optional[List[MemoryLayer]] = None,
            with_embeddings: bool = True) -> List[Memory]:
        ...

    @abstractmethod
    def namespaces(self) -> List[str]:
        """All namespaces present in this store (e.g. one per agent/clone)."""

    def count(self, namespace: str, layers: Optional[List[MemoryLayer]] = None) -> int:
        return len(self.all(namespace, layers))

    def session_stats(self, namespace: Optional[str] = None,
                      limit: Optional[int] = None, offset: int = 0) -> List[dict]:
        """Per-session rollup for the sessions list: one dict per distinct
        metadata.session — {id, namespace, count, first, last, source, first_content,
        record}, newest-active first. `namespace=None` spans all namespaces.

        Default implementation materializes all() (fine for small/in-process stores);
        SQL-backed stores OVERRIDE this with an indexed GROUP BY so the sessions
        endpoint never has to load the whole store into Python just to group it."""
        namespaces = [namespace] if namespace is not None else self.namespaces()
        sess: dict = {}
        for ns in namespaces:
            for m in self.all(ns, with_embeddings=False):
                md = m.metadata or {}
                sid = md.get("session")
                if not sid:
                    continue
                e = sess.setdefault((ns, sid), {"id": sid, "namespace": ns, "count": 0,
                                                "first": None, "last": None, "source": None,
                                                "first_content": None, "record": None,
                                                "_src": {}, "_rec_at": None})
                e["count"] += 1
                src = md.get("source")
                if src:
                    e["_src"][src] = e["_src"].get(src, 0) + 1
                if md.get("record") and (e["_rec_at"] is None or (m.created_at or "") >= e["_rec_at"]):
                    e["_rec_at"] = m.created_at or ""
                    e["record"] = {"title": md.get("title"), "status": md.get("status"),
                                   "participants": md.get("participants") or [],
                                   "metrics": md.get("metrics") or {}, "links": md.get("links") or {}}
                c = m.created_at or ""
                if c and (e["first"] is None or c < e["first"]):
                    e["first"] = c
                    if not e["first_content"] and m.content:
                        e["first_content"] = m.content.strip()[:60]
                if c and (e["last"] is None or c > e["last"]):
                    e["last"] = c
        out = []
        for e in sess.values():
            e["source"] = max(e["_src"], key=e["_src"].get) if e["_src"] else None
            e.pop("_src", None)
            e.pop("_rec_at", None)
            out.append(e)
        out.sort(key=lambda x: x["last"] or "", reverse=True)
        if limit is not None:
            out = out[int(offset):int(offset) + int(limit)]
        return out

    def timerange(self, namespace: str, layers: Optional[List[MemoryLayer]] = None):
        """(min_created_at, max_created_at) for a namespace, or (None, None) if
        empty. Default scans all() — fine for in-process stores; backends with a
        candidate cap or a network cost (Supabase) override with a cheap MIN/MAX so
        the value is TRUE (not bounded by a fetch window) and no rows are pulled."""
        cs = [m.created_at for m in self.all(namespace, layers) if m.created_at]
        return (min(cs), max(cs)) if cs else (None, None)

    def delete_layers(self, namespace: str, layers: Optional[List[MemoryLayer]] = None) -> int:
        """Bulk-delete every memory in `namespace` (optionally restricted to
        `layers`) in one pass. Default loops over delete(); backends with a set
        DELETE override this. Returns the number removed."""
        ids = [m.id for m in self.all(namespace, layers)]
        return sum(int(self.delete(namespace, i)) for i in ids)

    def touch(self, namespace: str, ids: List[str]) -> None:
        """Best-effort: bump access_count of EXISTING memories only — never
        insert. Default is a no-op; stores that can do a cheap in-place update
        override this. Recall uses it instead of add() so a read never writes a
        memory into a backend that didn't already hold it."""
        pass

    def bump_importance(self, namespace: str, pairs) -> None:
        """UPDATE-only da importância (pairs = [(id, importance), ...]). Default SEGURO: get→set→add,
        onde get() traz o embedding, então add() o preserva (nada de data-loss). Stores com UPDATE
        barato (SQLite) sobrescrevem. Usado pelo dream em vez de add() ao reforçar sem carregar vetor."""
        for mid, imp in (pairs or []):
            m = self.get(namespace, mid)
            if m is not None:
                m.importance = imp
                self.add([m])

    def close(self) -> None:  # optional resource cleanup
        pass
