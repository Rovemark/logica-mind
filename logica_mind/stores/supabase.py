"""Supabase store (PostgREST over stdlib urllib — no extra deps required).

Reads SUPABASE_URL and SUPABASE_SERVICE_KEY (or pass them in). Memories live in a
`logica_mind_memory` table; see `migrations/supabase.sql`. v0.1 fetches candidates
by namespace/layer and ranks in-process (like the other stores). Native pgvector
acceleration via an RPC is on the roadmap — the table already stores the vector.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import List, Optional

from ..types import Memory, MemoryLayer, SearchResult
from .base import Store, rank, apply_filter, matches_filter

TABLE = "logica_mind_memory"


class SupabaseStore(Store):
    name = "supabase"

    def __init__(
        self,
        url: Optional[str] = None,
        key: Optional[str] = None,
        table: str = TABLE,
        max_candidates: int = 2000,
        timeout: float = 15.0,
        use_rpc: bool = False,
        rpc: str = "search_logica_mind",
    ):
        self.url = (url or os.environ.get("SUPABASE_URL", "")).rstrip("/")
        self.key = key or os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY", "")
        self.table = table
        self.max_candidates = max_candidates
        self.timeout = timeout
        # use_rpc=True pushes vector search into Postgres (pgvector HNSW) via an
        # RPC instead of fetching candidates and ranking in Python — see migration
        self.use_rpc = use_rpc
        self.rpc = rpc
        if not self.url or not self.key:
            raise RuntimeError(
                "SupabaseStore needs SUPABASE_URL and SUPABASE_SERVICE_KEY "
                "(env vars or url=/key= args)."
            )

    # ---- low-level REST ----------------------------------------------------
    _PAGE_SIZE = 1000

    def _request(self, method: str, path: str, body=None, extra_headers=None):
        if method == "GET":
            base, _, query = path.partition("?")
            pairs = urllib.parse.parse_qsl(query, keep_blank_values=True)
            windows = {key: value for key, value in pairs if key in ("limit", "offset")}
            if sum(key == "limit" for key, _ in pairs) > 1 or sum(key == "offset" for key, _ in pairs) > 1:
                raise ValueError("Supabase GET has duplicate window parameters")
            try:
                limit = int(windows.get("limit", self._PAGE_SIZE))
                offset = int(windows.get("offset", 0))
            except (TypeError, ValueError) as error:
                raise ValueError("Supabase GET window must contain integers") from error
            if limit < 0 or offset < 0:
                raise ValueError("Supabase GET window must be nonnegative")
            params = [(key, value) for key, value in pairs if key not in ("limit", "offset")]
            if not any(key == "order" for key, _ in params):
                params.append(("order", "id.asc"))
            rows = []
            while len(rows) < limit:
                size = min(self._PAGE_SIZE, limit - len(rows))
                page_path = base + "?" + urllib.parse.urlencode(params + [("limit", str(size)), ("offset", str(offset + len(rows)))])
                page = self._request_once(method, page_path, body, extra_headers)
                if not isinstance(page, list) or len(page) > size:
                    raise RuntimeError("Supabase GET returned an invalid page")
                if not page:
                    break
                rows.extend(page)
                # A server may configure a smaller row cap. Continue even after
                # a short page; only an empty page proves exhaustion.
            return rows
        return self._request_once(method, path, body, extra_headers)

    def _request_once(self, method: str, path: str, body=None, extra_headers=None):
        endpoint = f"{self.url}/rest/v1/{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)
        req = urllib.request.Request(endpoint, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")
            raise RuntimeError(f"Supabase {method} {path} failed: {e.code} {detail}") from e

    @staticmethod
    def _to_row(m: Memory) -> dict:
        return {
            "id": m.id,
            "namespace": m.namespace,
            "content": m.content,
            "layer": m.layer.value,
            "embedding": m.embedding,
            "metadata": m.metadata,
            "importance": m.importance,
            "tags": m.tags,
            "source_ids": m.source_ids,
            "created_at": m.created_at,
            "access_count": m.access_count,
            "last_recalled_at": getattr(m, "last_recalled_at", None),
            "surprise_score": getattr(m, "surprise_score", 0.0),
        }

    @staticmethod
    def _to_memory(row: dict) -> Memory:
        return Memory(
            id=row["id"],
            namespace=row.get("namespace", "default"),
            content=row.get("content", ""),
            layer=MemoryLayer(row.get("layer", "semantic")),
            embedding=row.get("embedding"),
            metadata=row.get("metadata") or {},
            importance=row.get("importance", 0.5) or 0.5,
            tags=row.get("tags") or [],
            source_ids=row.get("source_ids") or [],
            created_at=row.get("created_at", ""),
            access_count=row.get("access_count", 0) or 0,
            last_recalled_at=row.get("last_recalled_at"),
            surprise_score=float(row.get("surprise_score") or 0.0),
        )

    # ---- Store API ---------------------------------------------------------
    def add(self, memories: List[Memory]) -> None:
        if not memories:
            return
        self._request(
            "POST", self.table,
            body=[self._to_row(m) for m in memories],
            extra_headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
        )

    def _candidates(self, namespace: str, layers: Optional[List[MemoryLayer]],
                    metadata_filter: Optional[dict] = None) -> List[Memory]:
        params = {
            "namespace": f"eq.{namespace}",
            "order": "created_at.desc,id.asc",
            "limit": str(self.max_candidates),
            "select": "*",
        }
        if layers:
            joined = ",".join(l.value for l in layers)
            params["layer"] = f"in.({joined})"
        # push metadata filter into PostgREST (jsonb ->>) so it applies BEFORE the
        # LIMIT window — older sessions outside the newest N would be missed otherwise
        if metadata_filter:
            for k, v in metadata_filter.items():
                if k.startswith("$"):   # operators ($not): apply_filter in search() applies them
                    continue
                key = f"metadata->>{k}"   # ->> extracts jsonb as text
                if isinstance(v, (list, tuple, set)):
                    params[key] = "in.(" + ",".join(self._pgrst_quote(x) for x in v) + ")"
                else:
                    params[key] = f"eq.{self._pg_text(v)}"
        rows = self._request("GET", f"{self.table}?{urllib.parse.urlencode(params)}") or []
        return [self._to_memory(r) for r in rows]

    @staticmethod
    def _has_list_filter(metadata_filter) -> bool:
        return bool(metadata_filter) and any(
            isinstance(v, (list, tuple, set)) for k, v in metadata_filter.items() if not k.startswith("$"))

    @staticmethod
    def _pg_text(x) -> str:
        if isinstance(x, bool):
            return "true" if x else "false"
        if x is None:
            return "null"
        return str(x)

    @staticmethod
    def _pgrst_quote(x) -> str:
        # PostgREST: double-quote values that may contain commas/spaces/reserved chars
        s = SupabaseStore._pg_text(x).replace("\\", "\\\\").replace('"', '\\"')
        return f'"{s}"'

    def search(self, namespace, query_embedding, query_text, layers=None, limit=20, metadata_filter=None) -> List[SearchResult]:
        # RPC handles scalar containment via p_metadata_filter; list ("one-of")
        # filters fall back to the correct in-process path
        if self.use_rpc and query_embedding and not self._has_list_filter(metadata_filter):
            try:
                return self._rpc_search(namespace, query_embedding, layers, limit, metadata_filter)
            except Exception as e:
                print(f"[logica-mind] supabase RPC search failed, ranking in-process ({e})", file=sys.stderr)
        try:
            cands = self._candidates(namespace, layers, metadata_filter)
        except Exception as e:
            print(f"[logica-mind] supabase metadata filter failed, fetching unfiltered ({e})", file=sys.stderr)
            cands = self._candidates(namespace, layers, None)
        return rank(apply_filter(cands, metadata_filter), query_embedding, query_text, limit)

    def _rpc_search(self, namespace, query_embedding, layers, limit, metadata_filter=None) -> List[SearchResult]:
        # the RPC only knows scalar containment: operators ($not) are applied to its rows here
        scalar = {k: v for k, v in (metadata_filter or {}).items() if not k.startswith("$")}
        body = {
            "p_namespace": namespace,
            "p_query_embedding": list(query_embedding),
            "p_limit": limit,
            "p_layers": [l.value for l in layers] if layers else None,
            "p_metadata_filter": scalar or None,
        }
        rows = self._request("POST", f"rpc/{self.rpc}", body=body) or []
        out: List[SearchResult] = []
        for r in rows:
            memory = self._to_memory(r)
            if not matches_filter(memory, metadata_filter):
                continue
            sim = float(r.get("similarity", 0.0) or 0.0)
            out.append(SearchResult(memory=memory, score=max(0.0, sim),
                                    components={"similarity": round(max(0.0, sim), 4)}))
        return out

    def get(self, namespace: str, memory_id: str) -> Optional[Memory]:
        params = {"namespace": f"eq.{namespace}", "id": f"eq.{memory_id}", "select": "*", "limit": "1"}
        rows = self._request("GET", f"{self.table}?{urllib.parse.urlencode(params)}") or []
        return self._to_memory(rows[0]) if rows else None

    def delete(self, namespace: str, memory_id: str) -> bool:
        params = {"namespace": f"eq.{namespace}", "id": f"eq.{memory_id}"}
        # return=representation makes PostgREST reply with the deleted rows, so we
        # can report whether anything was actually removed (contract parity with
        # the other stores; keeps forget()/dream counts honest)
        rows = self._request(
            "DELETE",
            f"{self.table}?{urllib.parse.urlencode(params)}",
            extra_headers={"Prefer": "return=representation"},
        )
        return bool(rows)

    def timerange(self, namespace: str, layers=None):
        # two index-only reads projecting ONLY created_at (no embeddings) — and the
        # true min/max regardless of how many rows the namespace holds, instead of
        # min/max over the truncated max_candidates window all() would return.
        def _one(order):
            params = {"namespace": f"eq.{namespace}", "select": "created_at",
                      "order": order, "limit": "1"}
            if layers:
                params["layer"] = "in.(" + ",".join(l.value for l in layers) + ")"
            rows = self._request("GET", f"{self.table}?{urllib.parse.urlencode(params)}") or []
            return rows[0]["created_at"] if rows else None
        return (_one("created_at.asc"), _one("created_at.desc"))

    def delete_layers(self, namespace: str, layers=None) -> int:
        params = {"namespace": f"eq.{namespace}"}
        if layers:
            params["layer"] = "in.(" + ",".join(l.value for l in layers) + ")"
        rows = self._request(
            "DELETE",
            f"{self.table}?{urllib.parse.urlencode(params)}",
            extra_headers={"Prefer": "return=representation"},
        )
        return len(rows or [])

    def touch(self, namespace: str, ids) -> None:
        """Bump access_count + stamp last_recalled_at on recalled rows. PostgREST
        can't do `col = col + 1` in a PATCH, so we read the current counts and
        write them back in one bulk-per-row PATCH (ids per recall are few)."""
        ids = list(ids or [])
        if not ids:
            return
        import datetime as _dt
        now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            rows = []
            # Bound ID queries by encoded byte size, not a silent row clamp.
            # Namespace remains in every batch and in every subsequent write.
            batch = []
            for memory_id in dict.fromkeys(ids):
                trial = batch + [memory_id]
                params = {"namespace": f"eq.{namespace}", "id": "in.(" + ",".join(self._pgrst_quote(i) for i in trial) + ")",
                          "select": "id,access_count", "limit": str(len(trial))}
                if batch and len(urllib.parse.urlencode(params).encode("ascii")) > 3000:
                    rows.extend(self._touch_rows(namespace, batch))
                    batch = [memory_id]
                else:
                    batch = trial
            if batch:
                rows.extend(self._touch_rows(namespace, batch))
            for r in rows:
                p = {"namespace": f"eq.{namespace}", "id": f"eq.{r['id']}"}
                self._request(
                    "PATCH", f"{self.table}?{urllib.parse.urlencode(p)}",
                    body={"access_count": (r.get("access_count") or 0) + 1,
                          "last_recalled_at": now},
                    extra_headers={"Prefer": "return=minimal"},
                )
        except Exception as e:
            print(f"[logica-mind] supabase touch failed, skipping ({e})", file=sys.stderr)

    def _touch_rows(self, namespace, ids):
        params = {"namespace": f"eq.{namespace}", "id": "in.(" + ",".join(self._pgrst_quote(i) for i in ids) + ")",
                  "select": "id,access_count", "limit": str(len(ids))}
        return self._request("GET", f"{self.table}?{urllib.parse.urlencode(params)}") or []

    def all(self, namespace, layers=None, with_embeddings=True) -> List[Memory]:
        return self._candidates(namespace, layers)

    def namespaces(self) -> List[str]:
        # PostgREST caps a response at its server-side max (default 1000 rows), so
        # a single GET silently misses namespaces past that window. Page through
        # with limit/offset until a short page tells us we've seen everything.
        seen: set = set()
        page, offset = 1000, 0
        while True:
            params = {"select": "namespace", "order": "namespace.asc,id.asc",
                      "limit": str(page), "offset": str(offset)}
            rows = self._request("GET", f"{self.table}?{urllib.parse.urlencode(params)}") or []
            for r in rows:
                seen.add(r.get("namespace", "default"))
            if len(rows) < page:
                break
            offset += page
        return sorted(seen)
