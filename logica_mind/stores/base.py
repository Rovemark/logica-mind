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
    scored = []
    for i, m in enumerate(mems):
        if use_vec[i]:
            s = max(0.0, cosine(query_embedding, m.embedding))
        else:
            s = lex[i] if lex is not None else 0.0
        if s <= 0.0:
            continue
        scored.append(SearchResult(memory=m, score=s, components={"similarity": round(s, 4)}))
    scored.sort(key=lambda r: r.score, reverse=True)
    return scored[:limit]


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

    def close(self) -> None:  # optional resource cleanup
        pass
