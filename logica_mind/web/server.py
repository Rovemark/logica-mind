"""Self-hosted dashboard for Logica Mind — store-wide (all agents / clones).

Zero-dependency: stdlib http.server serves a single-page app over a tiny JSON API
backed by a LogicaMind instance and its store. Launch with `mind.serve()` or the
`logica-mind ui` CLI.

Endpoints (all accept ?namespace=, default __all__ = aggregate across agents):
    GET /                       the dashboard SPA
    GET /api/namespaces         agents/clones with per-layer counts
    GET /api/stats              aggregate or per-namespace counts
    GET /api/recall?q=&limit=   ranked recall (one namespace or across all)
    GET /api/memories?layer=    raw memories
    GET /api/graph?history=     {nodes, links} — general graph or per namespace
    GET /api/user               dialectic user profile (per namespace)
"""
from __future__ import annotations

import hmac
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from ..types import MemoryLayer
from ..stores.base import _tokset


def _session_names_path(store) -> str | None:
    p = getattr(store, "path", None)
    if not p or p in (":memory:", ""):
        return None
    return os.path.splitext(p)[0] + "_session_names.json"


def _load_session_names(store) -> dict:
    path = _session_names_path(store)
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_session_names(store, names: dict) -> None:
    path = _session_names_path(store)
    if not path:
        return
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(names, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _auto_name_session(mind, namespace: str, session_id: str) -> str:
    """Generate an auto-name from the session's first user message."""
    for m in sorted(mind.store.all(namespace, with_embeddings=False), key=lambda x: x.created_at or ""):
        md = m.metadata or {}
        if md.get("session") != session_id:
            continue
        role = md.get("role", "")
        if role in ("user", "") and m.content:
            txt = m.content.strip()
            # strip common prefixes like "User: " or "[user]"
            txt = re.sub(r"^(?:user|human|you):\s*", "", txt, flags=re.IGNORECASE)
            return txt[:60] + ("…" if len(txt) > 60 else "")
    return session_id[:16]


def _try_import_claude_sessions(session_names: dict) -> int:
    """Scan ~/.claude/projects/ for session .jsonl files and auto-name matching sessions."""
    claude_dir = os.path.expanduser("~/.claude/projects")
    if not os.path.isdir(claude_dir):
        return 0
    added = 0
    try:
        for proj_hash in os.listdir(claude_dir):
            proj_path = os.path.join(claude_dir, proj_hash)
            if not os.path.isdir(proj_path):
                continue
            for fname in os.listdir(proj_path):
                if not fname.endswith(".jsonl"):
                    continue
                session_id = fname[:-6]  # strip .jsonl
                if session_id in session_names:
                    continue
                fpath = os.path.join(proj_path, fname)
                try:
                    title = _extract_claude_session_title(fpath)
                    if title:
                        session_names[session_id] = {"name": title, "source": "claude-code", "auto": True}
                        added += 1
                except Exception:
                    pass
    except Exception:
        pass
    return added


def _extract_claude_session_title(jsonl_path: str) -> str | None:
    """Extract the first human message from a Claude Code .jsonl session file."""
    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                # Claude Code format: {type: "user", message: {role:"user", content:[...]}}
                msg = obj.get("message") or obj
                role = msg.get("role", "")
                if role != "user":
                    continue
                content = msg.get("content", "")
                if isinstance(content, list):
                    # content blocks: [{type:"text", text:"..."}]
                    parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
                    content = " ".join(p for p in parts if p)
                if isinstance(content, str) and content.strip():
                    txt = content.strip()[:80]
                    return txt + ("…" if len(content.strip()) > 80 else "")
    except Exception:
        pass
    return None

_HERE = os.path.dirname(__file__)
_DIST = os.path.join(_HERE, "dist")          # built React/Vite app (preferred)
_ALL = ("", "__all__", "*", "all")
_NS_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")   # a well-formed namespace id
_MIME = {
    ".html": "text/html; charset=utf-8", ".js": "application/javascript",
    ".mjs": "application/javascript", ".css": "text/css", ".json": "application/json",
    ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
    ".ico": "image/x-icon", ".woff2": "font/woff2", ".woff": "font/woff",
    ".map": "application/json", ".webp": "image/webp", ".txt": "text/plain",
}


def _dist_index() -> str:
    """Built SPA index if present, else the legacy single-file dashboard."""
    built = os.path.join(_DIST, "index.html")
    path = built if os.path.exists(built) else os.path.join(_HERE, "index.html")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# kept as an alias so any external caller / test importing _load_index still works
_load_index = _dist_index


def _safe_static(url_path: str):
    """Resolve a URL path to a file inside dist/ (path-traversal safe), or None."""
    if not os.path.isdir(_DIST):
        return None
    rel = url_path.lstrip("/")
    full = os.path.normpath(os.path.join(_DIST, rel))
    if not (full == _DIST or full.startswith(_DIST + os.sep)) or not os.path.isfile(full):
        return None
    return full


def _strip(mem_dict: dict) -> dict:
    mem_dict = dict(mem_dict)
    mem_dict.pop("embedding", None)
    return mem_dict


def _is_internal(m) -> bool:
    """Internal bookkeeping rows (entity aliases) — kept in the GRAPH layer but
    never shown as real memories in listings/changelog/calendar."""
    return "alias" in (m.tags or [])


# in-process API metrics for the Analytics view — the dashboard's server
# self-measures the requests it serves (count, latency, errors). Reset per process.
_OPS = {"requests": 0, "errors": 0, "total_ms": 0.0}


class _Http400(Exception):
    """A client-input error → 400, kept distinct from a server-side 500 so a bad
    query param (e.g. limit=abc) returns a clean 400 instead of leaking a 500."""


def make_handler(mind, allow_writes: bool = True, token: str = None):
    token = token if token is not None else os.environ.get("LOGICA_MIND_TOKEN")

    _LAYER_VALUES = {l.value for l in MemoryLayer}

    def first(qs, key, default=""):
        return (qs.get(key, [default])[0] or default).strip()

    def _int(qs, key, default):
        try:
            return int(first(qs, key, str(default)))
        except (ValueError, TypeError):
            raise _Http400(f"invalid integer for '{key}'")

    def _float(qs, key, default):
        try:
            return float(first(qs, key, str(default)))
        except (ValueError, TypeError):
            raise _Http400(f"invalid number for '{key}'")

    def layers_of(qs):
        layer = first(qs, "layer")
        if not layer:
            return None
        if layer not in _LAYER_VALUES:
            raise _Http400(f"invalid layer '{layer}' (expected one of {sorted(_LAYER_VALUES)})")
        return [MemoryLayer(layer)]

    def _names(ns, is_all):
        """The namespaces a read should span: all of them in __all__ mode, else one."""
        return mind.store.namespaces() if is_all else [ns]

    def _user_ns(ns, is_all):
        """The dialectic user model is about ONE namespace. In __all__ mode pick the
        namespace that actually HAS a profile (the richest one) — and resolve it the
        SAME way for both the displayed profile and the ask box, so they never point
        at different users (the bug where the shown profile and the answer disagreed)."""
        if not is_all:
            return ns
        best, best_len = mind.namespace, -1
        for n in mind.store.namespaces():
            p = mind.for_namespace(n).user_profile() or ""
            if len(p) > best_len:
                best, best_len = n, len(p)
        return best

    # GET endpoints that expose memory CONTENT (or spend LLM $) require auth on a
    # non-loopback caller — loopback stays trusted so the local dashboard works
    # with zero config. Only the namespace list (counts, no content) is anonymous;
    # the SPA shell and static assets aren't under /api/ so they stay open too.
    _PUBLIC_GET = {"/api/namespaces", "/api/health"}
    _LOOPBACK = ("127.0.0.1", "::1", "::ffff:127.0.0.1")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _authed(self) -> bool:
            # loopback callers are trusted; otherwise a valid bearer token is required
            if self.client_address and self.client_address[0] in _LOOPBACK:
                return True
            if not token:
                return False
            auth = self.headers.get("Authorization", "")
            return auth.startswith("Bearer ") and hmac.compare_digest(auth[7:], token)

        def _cors(self):
            # the server binds loopback only, so a permissive ACAO is safe and lets
            # a same-host dashboard (e.g. http://localhost:3001) fetch /api/* and
            # embed the UI without cross-origin breakage.
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

        def _send(self, code, body: bytes, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            # never let the browser serve a STALE /api response, nor a stale app
            # shell (index.html) that would reference an old JS bundle — both must
            # always be fresh. The hashed JS/CSS assets can cache forever (their
            # name changes on rebuild), so only /api and HTML get no-store.
            if self.path.startswith("/api/") or "text/html" in ctype:
                self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            # CORS preflight — browsers send this before a cross-origin POST/custom
            # request. Answer 204 with the CORS headers so the real call proceeds.
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self._cors()
            self.end_headers()

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj).encode("utf-8"), "application/json")
            # self-measure API ops (request count, latency, errors) for the
            # Analytics view — counted once per request, /api/ only
            t0 = getattr(self, "_t0", None)
            if t0 is not None and self.path.startswith("/api/"):
                import time as _t
                _OPS["requests"] += 1
                _OPS["total_ms"] += (_t.time() - t0) * 1000.0
                if code >= 400:
                    _OPS["errors"] += 1
                self._t0 = None

        def _body(self) -> dict:
            try:
                n = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(n).decode("utf-8") if n else ""
                data = json.loads(raw) if raw.strip() else {}
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}

        def do_POST(self):
            import time as _t
            self._t0 = _t.time()
            parsed = urlparse(self.path)
            path = parsed.path
            if not allow_writes:
                return self._json({"error": "writes disabled"}, 403)
            if not self._authed():  # loopback-trusted or constant-time bearer check
                return self._json({"error": "unauthorized"}, 401)
            body = self._body()
            ns = (body.get("namespace") or mind.namespace)
            # the caller is already authorized (loopback or bearer token); the known
            # set just catches cross-tenant typos. A well-formed NEW namespace is
            # allowed so a first write can bootstrap a fresh agent; junk is rejected.
            known = {n["namespace"] for n in mind.list_namespaces()} | {mind.namespace}
            if ns not in known and not _NS_RE.match(ns):
                return self._json({"error": "invalid namespace"}, 400)
            target = mind.for_namespace(ns)
            try:
                if path == "/api/remember":
                    created = target.remember(str(body.get("text", "")), session=body.get("session"))
                    self._json({"stored": [c.content for c in created], "count": len(created)})
                elif path == "/api/add":
                    # rich "learning" add — runs extraction + dedup + (with an LLM)
                    # graph linking, then returns exactly what the engine learned so
                    # the UI can animate it: each created fact (new vs updated), any
                    # belief it superseded, new graph edges, and dedup/no-op.
                    text = str(body.get("text", "")).strip()
                    kind = str(body.get("kind") or "memory")
                    if not text:
                        return self._json({"error": "text required"}, 400)
                    has_llm = bool(getattr(target.llm, "available", False))
                    if kind == "observation":
                        mem = target.observe_user(text)
                        items = ([{"content": mem.content, "layer": "user", "op": "new",
                                   "superseded": None, "category": None}] if mem else [])
                        self._json({"ok": True, "namespace": ns, "kind": kind, "llm": has_llm,
                                    "created": items, "graph_edges": 0,
                                    "user_updated": bool(mem), "deduped": not bool(mem)})
                    else:
                        before = len(target.graph.edges()) if has_llm else 0
                        created = target.remember(text, build_graph=has_llm, session=body.get("session"))
                        after = len(target.graph.edges()) if has_llm else 0
                        items = []
                        for mm in created:
                            layer = str(getattr(mm.layer, "value", mm.layer))
                            if layer == "graph":
                                continue
                            md = mm.metadata or {}
                            items.append({
                                "content": mm.content, "layer": layer,
                                "op": "updated" if md.get("supersedes") else "new",
                                "superseded": (md.get("superseded_belief") or {}).get("content"),
                                "category": md.get("category"),
                                "dimension": md.get("dimension"),
                            })
                        self._json({"ok": True, "namespace": ns, "kind": kind, "llm": has_llm,
                                    "created": items, "graph_edges": max(0, after - before),
                                    "user_updated": False, "deduped": len(items) == 0})
                elif path == "/api/log":
                    m = target.log(str(body.get("text", "")), role=body.get("role"), session=body.get("session"))
                    self._json({"ok": bool(m), "id": m.id if m else None})
                elif path == "/api/forget":
                    self._json({"deleted": target.forget(memory_id=body.get("id"), query=body.get("query"))})
                elif path == "/api/forget_about":
                    entity = str(body.get("entity", "")).strip()
                    if not entity:
                        return self._json({"error": "entity required"}, 400)
                    # GDPR erase must cover EVERY agent when the dashboard is on the
                    # aggregate (__all__) view — otherwise the call resolves to the
                    # never-persisted '__all__' namespace and silently deletes nothing
                    # while the UI reports success. Loop across all real namespaces.
                    if ns in _ALL:
                        deleted = sum(mind.for_namespace(nm).forget_about(entity)
                                      for nm in mind.store.namespaces())
                    else:
                        deleted = target.forget_about(entity)
                    self._json({"deleted": deleted, "entity": entity})
                elif path == "/api/observe_user":
                    mem = target.observe_user(str(body.get("text", "")))
                    self._json({"ok": bool(mem), "id": mem.id if mem else None})
                elif path == "/api/observe_peer":
                    mem = target.observe_peer(str(body.get("observer", "")), str(body.get("observed", "")),
                                              str(body.get("text", "")))
                    self._json({"ok": bool(mem), "id": mem.id if mem else None})
                elif path == "/api/ingest":
                    self._json(target.ingest_conversation(body.get("messages") or [], session=body.get("session")))
                elif path == "/api/record":
                    title = str(body.get("title", "")).strip()
                    if not title:
                        return self._json({"error": "title required"}, 400)
                    rec = target.record_session(
                        title=title,
                        session_id=body.get("session_id") or body.get("session"),
                        participants=body.get("participants") or [],
                        status=str(body.get("status", "completed")),
                        metrics=body.get("metrics") or {},
                        links=body.get("links") or {},
                        tags=body.get("tags") or [],
                        summary=body.get("summary"),
                        store_contributions=bool(body.get("store_contributions", True)),
                    )
                    md = rec.metadata or {}
                    self._json({"ok": True, "id": rec.id, "session": md.get("session")})
                elif path == "/api/import-bundle":
                    n = target.import_bundle(body.get("bundle") or {}, secret=body.get("secret"),
                                             verify=bool(body.get("secret")))
                    self._json({"imported": n})
                elif path == "/api/sessions/rename":
                    sid = str(body.get("session_id", "")).strip()
                    new_name = str(body.get("name", "")).strip()
                    if not sid or not new_name:
                        return self._json({"error": "session_id and name required"}, 400)
                    snames = _load_session_names(mind.store)
                    snames[sid] = {"name": new_name[:80], "source": "manual", "auto": False}
                    _save_session_names(mind.store, snames)
                    self._json({"ok": True, "session_id": sid, "name": new_name[:80]})
                elif path == "/api/clear":
                    # danger-zone: clear memories by layer / age / full namespace reset
                    layer_str = body.get("layer")
                    older_than_days = body.get("older_than_days")
                    purge_all = bool(body.get("purge_all"))
                    tgt_ns = (body.get("namespace") or mind.namespace)
                    # validate the layer up front (clean 400, not a 500 from MemoryLayer())
                    if layer_str and layer_str not in {l.value for l in MemoryLayer}:
                        return self._json({"error": f"invalid layer '{layer_str}'"}, 400)
                    tgt = mind.for_namespace(tgt_ns)
                    deleted = 0
                    if purge_all:
                        tgt.purge()
                        deleted = -1  # unknown count after purge
                    elif older_than_days is not None:
                        import time as _time
                        try:
                            cutoff_ts = _time.time() - float(older_than_days) * 86400
                        except (ValueError, TypeError):
                            return self._json({"error": "older_than_days must be a number"}, 400)
                        layers = [MemoryLayer(layer_str)] if layer_str else None
                        to_del = [m for m in mind.store.all(tgt_ns, layers, with_embeddings=False)
                                  if m.created_at and
                                  _time.mktime(_time.strptime(m.created_at[:19], "%Y-%m-%dT%H:%M:%S")) < cutoff_ts]
                        for m in to_del:
                            if mind.store.delete(tgt_ns, m.id):
                                deleted += 1
                    elif layer_str:
                        deleted = mind.store.delete_layers(tgt_ns, [MemoryLayer(layer_str)])
                    else:
                        return self._json({"error": "specify layer, older_than_days, or purge_all"}, 400)
                    self._json({"ok": True, "deleted": deleted, "namespace": tgt_ns})
                elif path == "/api/demo/seed":
                    from .. import demo as _demo
                    n = _demo.seed(mind)
                    self._json({"ok": True, "seeded": n})
                elif path == "/api/demo/clear":
                    from .. import demo as _demo
                    self._json({"ok": True, "deleted": _demo.clear(mind)})
                else:
                    self._json({"error": "not found"}, 404)
            except _Http400 as e:
                self._json({"error": str(e)}, 400)
            except Exception as e:
                self._json({"error": str(e)}, 500)

        def do_GET(self):
            import time as _t
            self._t0 = _t.time()
            parsed = urlparse(self.path)
            path, qs = parsed.path, parse_qs(parsed.query)
            ns = first(qs, "namespace")
            is_all = ns in _ALL
            # any /api read that can return memory content requires auth on a
            # non-loopback caller (loopback trusted); namespace list is the only
            # anonymous /api endpoint
            if path.startswith("/api/") and path not in _PUBLIC_GET and not self._authed():
                return self._json({"error": "unauthorized"}, 401)
            try:
                if path in ("/", "/index.html"):
                    self._send(200, _dist_index().encode("utf-8"), "text/html; charset=utf-8")

                elif not path.startswith("/api/"):
                    # static asset from the built SPA (js/css/fonts/icons)
                    f = _safe_static(path)
                    if f:
                        import mimetypes
                        ext = os.path.splitext(f)[1].lower()
                        ctype = _MIME.get(ext) or mimetypes.guess_type(f)[0] or "application/octet-stream"
                        with open(f, "rb") as fh:
                            self._send(200, fh.read(), ctype)
                    else:
                        # SPA fallback: unknown non-API route → serve the app shell
                        self._send(200, _dist_index().encode("utf-8"), "text/html; charset=utf-8")

                elif path == "/api/namespaces":
                    self._json({"namespaces": mind.list_namespaces()})

                elif path == "/api/stats":
                    if is_all:
                        agg = {l.value: 0 for l in MemoryLayer}
                        agg["total"] = 0
                        for item in mind.list_namespaces():
                            for k, v in item["stats"].items():
                                agg[k] += v
                            agg["total"] += item["total"]
                        self._json({"namespace": "__all__", "stats": agg})
                    else:
                        self._json({"namespace": ns, "stats": mind.for_namespace(ns).stats()})

                elif path == "/api/recall":
                    q = first(qs, "q")
                    limit = _int(qs, "limit", 12)
                    layers = layers_of(qs)
                    if not q:
                        results = []
                    elif is_all:
                        results = mind.recall_across(q, layers=layers, limit=limit)
                    else:
                        results = mind.for_namespace(ns).recall(q, layers=layers, limit=limit)
                    self._json({"query": q, "results": [
                        {"score": round(r.score, 4), "components": r.components,
                         "memory": _strip(r.memory.to_dict())}
                        for r in results
                    ]})

                elif path == "/api/search":
                    # global Spotlight: memories (recall across all), entities
                    # (graph node names) and namespaces — for the ⌘K palette.
                    q = (first(qs, "q") or "").strip()
                    limit = max(1, _int(qs, "limit", 6))
                    if not q:
                        self._json({"memories": [], "entities": [], "namespaces": [], "categories": []})
                    else:
                        ql = q.lower()
                        mems = mind.recall_across(q, limit=limit)
                        ents, seen = [], set()
                        for nm in mind.store.namespaces():
                            try:
                                for node in mind.for_namespace(nm).graph_nodes():
                                    name = node.get("name") or ""
                                    k = name.lower()
                                    if name and ql in k and k not in seen:
                                        seen.add(k)
                                        ents.append({"name": name, "namespace": nm,
                                                     "degree": node.get("degree", 0), "type": node.get("type", "")})
                            except Exception:
                                continue
                        ents.sort(key=lambda e: -e["degree"])
                        nss = [n for n in mind.store.namespaces() if ql in n.lower()]
                        # categories: distinct fact categories matching the query
                        catc = {}
                        for nm in mind.store.namespaces():
                            for m in mind.store.all(nm, with_embeddings=False):
                                c = (m.metadata or {}).get("category")
                                if c and ql in c.lower():
                                    catc[c] = catc.get(c, 0) + 1
                        cats = sorted(catc.items(), key=lambda x: -x[1])[:limit]
                        self._json({
                            "memories": [{"score": round(r.score, 3), "memory": _strip(r.memory.to_dict())} for r in mems],
                            "entities": ents[:limit],
                            "namespaces": nss[:limit],
                            "categories": [{"name": c, "count": n} for c, n in cats],
                        })

                elif path == "/api/context":
                    # Smart context assembly: rank candidates for `q`, then fit the
                    # most relevant into a token budget and return BOTH — the ranked
                    # pool (with which ones made the cut) and the assembled block.
                    q = first(qs, "q") or ""
                    budget = _int(qs, "budget", 1200)
                    if is_all:
                        # context() is per-namespace; show the busiest one so the
                        # block is populated, and let the UI switch namespaces.
                        counts = {n["namespace"]: n.get("total", 0) for n in mind.list_namespaces()}
                        tgt = max(counts, key=counts.get) if counts else mind.namespace
                    else:
                        tgt = ns
                    sub = mind.for_namespace(tgt)
                    cands = sub.recall(q, limit=20) if q.strip() else []
                    block = sub.context(q, token_budget=budget) if q.strip() else ""
                    tokens = mind._approx_tokens(block) if block else 0
                    items = []
                    for r in cands:
                        c = r.memory.content or ""
                        items.append({
                            "score": round(r.score, 4),
                            "components": r.components,
                            "included": bool(block) and c[:60] in block,
                            "memory": _strip(r.memory.to_dict()),
                        })
                    self._json({"namespace": tgt, "query": q, "budget": budget,
                                "tokens": tokens, "block": block, "candidates": items})

                elif path == "/api/observations":
                    # structural patterns over the temporal graph (hubs +
                    # co-occurrences) — recurrences that no single fact holds.
                    limit = max(1, _int(qs, "limit", 12))
                    if is_all:
                        seen, merged = set(), []
                        for nm in mind.store.namespaces():
                            for o in mind.for_namespace(nm).observations(limit=limit):
                                key = (o["kind"], tuple(o["entities"]))
                                if key in seen:
                                    continue
                                seen.add(key)
                                merged.append({**o, "namespace": nm})
                        merged.sort(key=lambda x: x["count"], reverse=True)
                        self._json({"observations": merged[:limit]})
                    else:
                        obs = mind.for_namespace(ns).observations(limit=limit)
                        self._json({"observations": [{**o, "namespace": ns} for o in obs]})

                elif path == "/api/dimensions":
                    # the life-dimension profile: every categorized fact grouped by
                    # dimension and Maslow tier — powers the Profile view + filters.
                    from ..extract.taxonomy import DIMENSIONS, MASLOW
                    names = mind.store.namespaces() if is_all else [ns]
                    agg = {}
                    uncategorized = 0
                    for nm in names:
                        for m in mind.store.all(nm, with_embeddings=False):
                            if _is_internal(m):
                                continue
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
                    self._json({"dimensions": out, "uncategorized": uncategorized, "maslow": MASLOW})

                elif path == "/api/integrations":
                    # the live stack (store + redundancy, embedder, llm, reranker)
                    # plus the catalog of what's available to enable — drives the
                    # Settings → Integrations panel.
                    from ..providers import detect
                    emb, st = mind.embedder, mind.store
                    if getattr(st, "name", "") == "multi":
                        store_info = {"id": "multi", "backends": [getattr(s, "name", "?") for s in getattr(st, "stores", [])]}
                    else:
                        store_info = {"id": getattr(st, "name", "store"), "backends": []}
                    dims = getattr(emb, "dim", None) or getattr(emb, "_dim", None) or getattr(emb, "dimension", None)
                    active = {
                        "store": store_info,
                        "embedder": {"id": getattr(emb, "name", "?"), "model": getattr(emb, "model", None), "dims": dims},
                        "llm": {"id": getattr(mind.llm, "name", "null"), "model": getattr(mind.llm, "model", None),
                                "available": bool(getattr(mind.llm, "available", False))},
                        "reranker": (getattr(mind.reranker, "name", None) if getattr(mind, "reranker", None) else None),
                    }
                    self._json({"active": active, "available": detect()})

                elif path == "/api/memories":
                    layers = layers_of(qs)
                    session = first(qs, "session")     # optional: scope to one session
                    dim = first(qs, "dimension")       # optional: a life-dimension filter
                    category = first(qs, "category")   # optional: an exact-category filter
                    lim = int(first(qs, "limit", "200") or 200)
                    off = int(first(qs, "offset", "0") or 0)
                    pager = getattr(mind.store, "page", None)
                    # Fast path: no metadata filters → SQL LIMIT/OFFSET (newest first),
                    # materializing ~200 rows instead of every row in every namespace.
                    if callable(pager) and not (session or dim or category):
                        mems = [m for m in pager(None if is_all else ns, layers, lim, off)
                                if not _is_internal(m)]
                        self._json({"memories": [_strip(m.to_dict()) for m in mems]})
                    else:
                        names = mind.store.namespaces() if is_all else [ns]
                        mems = []
                        for name in names:
                            for m in mind.store.all(name, layers, with_embeddings=False):
                                if _is_internal(m):
                                    continue
                                md = m.metadata or {}
                                if session and md.get("session") != session:
                                    continue
                                if dim and md.get("dimension") != dim:
                                    continue
                                if category and md.get("category") != category:
                                    continue
                                mems.append(m)
                        mems.sort(key=lambda m: m.created_at or "", reverse=True)
                        self._json({"memories": [_strip(m.to_dict()) for m in mems[off:off + lim]]})

                elif path == "/api/sessions":
                    # distinct sessions with counts + time span + names
                    session_names = _load_session_names(mind.store)
                    names_list = mind.store.namespaces() if is_all else [ns]
                    sess = {}
                    for name in names_list:
                        for m in mind.store.all(name, with_embeddings=False):
                            md = m.metadata or {}
                            sid = md.get("session")
                            if not sid:
                                continue
                            e = sess.setdefault((name, sid), {"id": sid, "namespace": name,
                                                              "count": 0, "first": None, "last": None,
                                                              "_src": {}, "_first_content": None,
                                                              "record": None, "_record_at": None})
                            e["count"] += 1
                            src = md.get("source")
                            if src:
                                e["_src"][src] = e["_src"].get(src, 0) + 1
                            # a structured session record surfaces its title/status/
                            # participants/metrics to the list (generic, framework-free).
                            # If an id was re-used for two records, the NEWEST wins
                            # (deterministic, matching session_record()).
                            if md.get("record") and (e["_record_at"] is None or (m.created_at or "") >= e["_record_at"]):
                                e["_record_at"] = m.created_at or ""
                                e["record"] = {"title": md.get("title"), "status": md.get("status"),
                                               "participants": md.get("participants") or [],
                                               "metrics": md.get("metrics") or {},
                                               "links": md.get("links") or {}}
                            c = m.created_at or ""
                            if c and (e["first"] is None or c < e["first"]):
                                e["first"] = c
                                if not e["_first_content"] and m.content:
                                    e["_first_content"] = m.content.strip()[:60]
                            if c and (e["last"] is None or c > e["last"]):
                                e["last"] = c
                    for e in sess.values():
                        e["source"] = max(e["_src"], key=e["_src"].get) if e["_src"] else None
                        e.pop("_src", None)
                        e.pop("_record_at", None)
                        sid = e["id"]
                        stored = session_names.get(sid, {})
                        if stored.get("name"):
                            e["name"] = stored["name"]
                        elif e.get("record") and e["record"].get("title"):
                            e["name"] = e["record"]["title"]      # record title wins as the name
                        else:
                            fc = e.pop("_first_content", None) or sid[:16]
                            e["name"] = fc
                        e.pop("_first_content", None)
                    out = sorted(sess.values(), key=lambda s: s["last"] or "", reverse=True)
                    self._json({"sessions": out})

                elif path == "/api/session":
                    # the full structured record for one session id + its contributions
                    sid = first(qs, "id")
                    tgt = ns if not is_all else mind.namespace
                    rec = None
                    for nm in _names(ns, is_all):
                        rec = mind.for_namespace(nm).session_record(sid)
                        if rec:
                            tgt = nm
                            break
                    self._json({"namespace": tgt, "id": sid, "record": rec})

                elif path == "/api/export":
                    # full dump of a namespace (or all) — for the download button
                    names = mind.store.namespaces() if is_all else [ns]
                    mems = []
                    for name in names:
                        mems.extend(mind.store.all(name, with_embeddings=False))
                    mems.sort(key=lambda m: m.created_at or "")
                    self._json({"namespace": "__all__" if is_all else ns,
                                "count": len(mems), "memories": [m.to_dict() for m in mems]})

                elif path == "/api/graph":
                    hist = first(qs, "history", "1") == "1"
                    at = first(qs, "at") or None     # point-in-time view
                    lyr = first(qs, "layers")        # csv: relation,co_mention,semantic
                    layers = [s for s in lyr.split(",") if s] if lyr else None
                    foc = first(qs, "focus") or None
                    dep = int(first(qs, "depth", "1") or 1)
                    # cap the rendered graph to the most-central nodes (0 = no cap).
                    # 300 stays smooth now that physics is grid-partitioned (~O(N))
                    # and edges draw in one batched stroke. Raise via ?limit= if your
                    # machine handles more (the 2D canvas tops out well below WebGL).
                    lim = int(first(qs, "limit", "300") or 300)
                    self._json(mind.graph_viz(namespace=None if is_all else ns,
                                              include_history=hist, at=at,
                                              layers=layers, focus=foc, depth=dep, limit=lim))

                elif path == "/api/timerange":
                    # true min/max created_at via a cheap data-layer MIN/MAX (no row
                    # materialization, not bounded by the candidate window). Use the
                    # lightweight namespaces() list, not list_namespaces() (which does
                    # per-layer counts) — for the scrubber.
                    names = mind.store.namespaces() if is_all else [ns]
                    lo, hi = None, None
                    for name in names:
                        a, b = mind.store.timerange(name)
                        if a and (lo is None or a < lo):
                            lo = a
                        if b and (hi is None or b > hi):
                            hi = b
                    self._json({"min": lo, "max": hi})

                elif path == "/api/communities":
                    tgt = ns if not is_all else (
                        (mind.list_namespaces()[0]["namespace"]) if mind.list_namespaces() else mind.namespace)
                    comms = mind.for_namespace(tgt).graph_communities(include_history=False)
                    self._json({"namespace": tgt, "communities": [
                        {"nodes": c["nodes"], "size": len(c["nodes"]),
                         "facts": [e.label() for e in c["edges"]][:12]} for c in comms]})

                elif path == "/api/entity":
                    name = first(qs, "name")
                    depth = _int(qs, "depth", 2)
                    tgt = ns if not is_all else mind.namespace
                    g = mind.for_namespace(tgt).graph
                    bfs = g.bfs(name, depth=depth) if name else {"nodes": [], "edges": [], "levels": {}}
                    self._json({
                        "center": name,
                        "nodes": [{"id": n, "level": bfs["levels"].get(n.lower(), 0)} for n in bfs["nodes"]],
                        "links": [{"source": e.subject, "target": e.object, "label": e.predicate,
                                   "confidence": e.confidence, "valid": e.is_valid} for e in bfs["edges"]],
                    })

                elif path == "/api/reflect":
                    tgt = ns if not is_all else (
                        (mind.list_namespaces()[0]["namespace"]) if mind.list_namespaces() else mind.namespace)
                    self._json({"namespace": tgt,
                                "insight": mind.for_namespace(tgt).reflect(window=12, store_result=False)})

                elif path == "/api/user":
                    target = _user_ns(ns, is_all)
                    self._json({"namespace": target, "profile": mind.for_namespace(target).user_profile()})

                elif path == "/api/ask_user":
                    # dialectic query is about ONE user; in __all__ mode resolve to the
                    # SAME namespace the profile is shown from (the richest one)
                    tgt = _user_ns(ns, is_all)
                    q = first(qs, "q")
                    if not q:
                        return self._json({"error": "q required"}, 400)
                    answer = mind.for_namespace(tgt).ask_about_user(q)
                    self._json({"namespace": tgt, "question": q, "answer": answer})

                elif path == "/api/calendar":
                    # per-day memory counts (+ per layer) for the Obsidian-style heatmap.
                    # Fast path: one GROUP BY via store.day_counts() (no row materialization).
                    # GRAPH excluded — its created_at is the extraction time, not a real
                    # event, so it'd pile onto a single day and swamp the heatmap.
                    dc = getattr(mind.store, "day_counts", None)
                    if callable(dc):
                        days = dc(None if is_all else ns, exclude_layers=["graph"])
                    else:
                        names = mind.store.namespaces() if is_all else [ns]
                        days = {}
                        for name in names:
                            for m in mind.store.all(name, with_embeddings=False):
                                if _is_internal(m) or m.layer == MemoryLayer.GRAPH:
                                    continue
                                d = (m.created_at or "")[:10]
                                if not d:
                                    continue
                                e = days.setdefault(d, {"total": 0, "episodic": 0,
                                                        "semantic": 0, "graph": 0, "user": 0})
                                e["total"] += 1
                                e[m.layer.value] = e.get(m.layer.value, 0) + 1
                    self._json({"days": days})

                elif path == "/api/day":
                    date = first(qs, "date")            # YYYY-MM-DD
                    layers = layers_of(qs)
                    names = mind.store.namespaces() if is_all else [ns]
                    mems = []
                    for name in names:
                        for m in mind.store.all(name, layers, with_embeddings=False):
                            if _is_internal(m):
                                continue
                            if date and (m.created_at or "").startswith(date):
                                mems.append(m)
                    mems.sort(key=lambda m: m.created_at or "", reverse=True)
                    self._json({"date": date, "memories": [_strip(m.to_dict()) for m in mems]})

                elif path == "/api/node":
                    # entity detail (Obsidian-style): `connected` = counterparty
                    # entity chips pulled from the GRAPH edges that mention this name;
                    # `memories` = EVERY memory (episodic/semantic/user/graph) that
                    # mentions it, all openable. Both aggregate across namespaces in
                    # __all__ (so a cross-agent entity shared across agents shows all its edges).
                    # Graph edges intentionally appear in BOTH sections — as a chip in
                    # `connected` and as an openable note in `memories`.
                    name = first(qs, "name")
                    etoks = _tokset(name or "")
                    nlow = (name or "").lower()
                    scan = mind.store.namespaces() if is_all else [ns]
                    mems, connected = [], {}
                    for nm in scan:
                        for m in mind.store.all(nm, with_embeddings=False):
                            if _is_internal(m):
                                continue
                            md = m.metadata or {}
                            mentions = ((etoks and etoks <= _tokset(m.content))
                                        or str(md.get("subject", "")).lower() == nlow
                                        or str(md.get("object", "")).lower() == nlow
                                        or str(md.get("observed", "")).lower() == nlow)
                            if not mentions:
                                continue
                            mems.append(m)   # everything mentioning it — graph edges + notes, all openable
                            if m.layer == MemoryLayer.GRAPH and md.get("subject"):
                                s, o = str(md.get("subject")), str(md.get("object"))
                                other = o if s.lower() == nlow else s
                                if other and other.lower() != nlow:
                                    connected.setdefault(other.lower(), other)
                    mems.sort(key=lambda m: m.created_at or "", reverse=True)
                    # first-class entity info (type + aliases) from the resolving ns
                    ent = mind.for_namespace(ns if not is_all else mind.namespace).entity(name)
                    base = ns if not is_all else mind.namespace
                    unlinked = mind.for_namespace(base).entity_unlinked(name, namespaces=scan)
                    self._json({"name": ent.get("name") or name, "type": ent.get("type", ""),
                                "aliases": ent.get("aliases", []),
                                "connected": list(connected.values()),
                                "unlinked": unlinked,
                                "memories": [_strip(m.to_dict()) for m in mems[:60]]})

                elif path == "/api/contradictions":
                    # aggregate across namespaces in __all__ mode (parity with
                    # /api/diff and /api/peers, which the same Changes view renders)
                    names = mind.store.namespaces() if is_all else [ns]
                    items = []
                    for nm in names:
                        for c in mind.for_namespace(nm).contradictions():
                            c["namespace"] = nm
                            items.append(c)
                    self._json({"namespace": "__all__" if is_all else ns, "contradictions": items})

                elif path == "/api/diff":
                    since = first(qs, "since") or "1970-01-01T00:00:00Z"
                    until = first(qs, "until") or None
                    names = mind.store.namespaces() if is_all else [ns]
                    items = []
                    for nm in names:
                        for d in mind.for_namespace(nm).diff(since, until=until):
                            d["namespace"] = nm
                            items.append(d)
                    items.sort(key=lambda d: d.get("created_at", ""), reverse=True)
                    self._json({"since": since, "until": until, "diff": items[:300]})

                elif path == "/api/peers":
                    names = mind.store.namespaces() if is_all else [ns]
                    pairs = {}
                    for nm in names:
                        for m in mind.store.all(nm, [MemoryLayer.USER]):
                            md = m.metadata or {}
                            obr, obd = md.get("observer"), md.get("observed")
                            if obr and obd:
                                k = (nm, obr, obd)
                                pairs.setdefault(k, {"namespace": nm, "observer": obr, "observed": obd, "count": 0})
                                pairs[k]["count"] += 1
                    self._json({"peers": list(pairs.values())})

                elif path == "/api/peer_card":
                    tgt = ns if not is_all else mind.namespace
                    obr, obd = first(qs, "observer"), first(qs, "observed")
                    self._json({"observer": obr, "observed": obd,
                                "card": mind.for_namespace(tgt).peer_card(obr, obd)})

                # ---- moats ----
                elif path == "/api/provenance":      # why do I believe this?
                    tgt = ns if not is_all else mind.namespace
                    self._json(mind.for_namespace(tgt).provenance(first(qs, "id")))

                elif path == "/api/connected":        # derived backlinks for a memory
                    tgt = ns if not is_all else mind.namespace
                    self._json(mind.for_namespace(tgt).connections(first(qs, "id")))

                elif path == "/api/path":             # "how is A related to B?"
                    frm, to = first(qs, "from"), first(qs, "to")
                    if not frm or not to:
                        return self._json({"error": "from & to required"}, 400)
                    nss = mind.store.namespaces() if is_all else [ns]
                    base = nss[0] if nss else mind.namespace
                    self._json(mind.for_namespace(base).how_related(frm, to, namespaces=nss))

                elif path == "/api/bridges":          # load-bearing connectors
                    nss = mind.store.namespaces() if is_all else [ns]
                    base = nss[0] if nss else mind.namespace
                    self._json({"bridges": mind.for_namespace(base).bridges(namespaces=nss)})

                elif path == "/api/suggested":        # predict the missing edge
                    nss = mind.store.namespaces() if is_all else [ns]
                    base = nss[0] if nss else mind.namespace
                    self._json({"suggested": mind.for_namespace(base).suggested_links(namespaces=nss)})

                elif path == "/api/stale":           # epistemic self-doubt
                    min_age = _float(qs, "min_age_days", 30)
                    items = []
                    for nm in _names(ns, is_all):
                        for s in mind.for_namespace(nm).stale_beliefs(min_age_days=min_age):
                            s["namespace"] = nm
                            items.append(s)
                    items.sort(key=lambda x: x.get("confidence", 0))
                    self._json({"namespace": "__all__" if is_all else ns, "stale": items})

                elif path == "/api/gap":             # what `other` knows that ns doesn't
                    tgt = ns if not is_all else mind.namespace
                    other = first(qs, "other")
                    self._json({"namespace": tgt, "other": other,
                                "gap": mind.for_namespace(tgt).knowledge_gap(other) if other else []})

                elif path == "/api/bundle":          # portable signed memory bundle
                    tgt = ns if not is_all else mind.namespace
                    self._json(mind.for_namespace(tgt).export_bundle(secret=first(qs, "secret") or None))

                # ---- new moats ----
                elif path == "/api/dreams":
                    from ..dreaming import load_dreams
                    tgt_ns = ns if not is_all else None
                    self._json({"dreams": load_dreams(mind.store, tgt_ns,
                                                      limit=_int(qs, "limit", 50))})

                elif path == "/api/contested":
                    thresh = _float(qs, "threshold", 0.65)
                    items = []
                    for nm in _names(ns, is_all):
                        for c in mind.for_namespace(nm).contested_beliefs(thresh):
                            c["namespace"] = nm
                            items.append(c)
                    items.sort(key=lambda x: x.get("surprise_score", 0), reverse=True)
                    self._json({"namespace": "__all__" if is_all else ns, "contested": items})

                elif path == "/api/surprises":
                    since = first(qs, "since") or None
                    items = []
                    for nm in _names(ns, is_all):
                        for s in mind.for_namespace(nm).surprise_events(since):
                            s["namespace"] = nm
                            items.append(s)
                    items.sort(key=lambda x: x.get("surprise_score", 0), reverse=True)
                    self._json({"namespace": "__all__" if is_all else ns, "surprises": items})

                elif path == "/api/forget_curve":
                    halflife = _float(qs, "halflife", 30)
                    items = []
                    for nm in _names(ns, is_all):
                        for e in mind.for_namespace(nm).forget_curve(halflife):
                            e["namespace"] = nm
                            items.append(e)
                    items.sort(key=lambda x: x.get("projected_strength_7d", 0))
                    self._json({"namespace": "__all__" if is_all else ns, "curve": items})

                elif path == "/api/sessions/claude-import":
                    session_names = _load_session_names(mind.store)
                    added = _try_import_claude_sessions(session_names)
                    if added:
                        _save_session_names(mind.store, session_names)
                    self._json({"imported": added})

                # ---- workspace / Project DNA (codebase understanding) ----
                elif path == "/api/scan":
                    from .. import devtools
                    self._json(devtools.scan(first(qs, "path") or None))

                elif path == "/api/demo":
                    # whether the fictional demo dataset is currently loaded
                    from .. import demo as _demo
                    self._json({"present": _demo.count(mind) > 0, "count": _demo.count(mind)})

                # ---- observability ----
                elif path == "/api/health":
                    self._json({"ok": True, "store": getattr(mind.store, "name", "?"),
                                "namespaces": len(mind.store.namespaces())})

                elif path == "/api/analytics":
                    # everything the Analytics view needs, in one call (all real data)
                    import datetime as _dt
                    names = mind.store.namespaces() if is_all else [ns]
                    by_layer = {l.value: 0 for l in MemoryLayer}
                    by_source, by_day, sessions, ns_rows = {}, {}, set(), {}
                    entities_total = relations_total = contradictions_total = 0
                    _bc = getattr(mind.store, "bucket_counts", None)
                    _gcounts = _bc() if callable(_bc) else {}
                    for nm in names:
                        ent = facts = rel = 0
                        last = None
                        day_spark = {}
                        total_ns = 0
                        for m in mind.store.all(nm, with_embeddings=False):
                            if _is_internal(m):
                                continue
                            total_ns += 1
                            md = m.metadata or {}
                            lv = m.layer.value
                            by_layer[lv] = by_layer.get(lv, 0) + 1
                            src = md.get("source")
                            if src:
                                by_source[src] = by_source.get(src, 0) + 1
                            d = (m.created_at or "")[:10]
                            if d:
                                by_day[d] = by_day.get(d, 0) + 1
                                day_spark[d] = day_spark.get(d, 0) + 1
                            if md.get("session"):
                                sessions.add((nm, md["session"]))
                            c = m.created_at or ""
                            if c and (last is None or c > last):
                                last = c
                            if m.layer == MemoryLayer.GRAPH and md.get("subject"):
                                rel += 1
                            elif lv in ("semantic", "user"):
                                facts += 1
                        # entities + contradictions via the graph — only for namespaces
                        # that actually HAVE a graph (skip the empty ones; most are).
                        if _gcounts.get(nm, {}).get("graph", 0) > 0:
                            try:
                                sub = mind.for_namespace(nm)
                                ent = len(sub.graph_nodes())
                                relations_total += rel
                                entities_total += ent
                                contradictions_total += len(sub.contradictions())
                            except Exception:
                                pass
                        # last-7-day sparkline for the Context-Lake-style row
                        spark = []
                        base = _dt.datetime.now(_dt.timezone.utc)
                        for i in range(13, -1, -1):
                            dd = (base - _dt.timedelta(days=i)).strftime("%Y-%m-%d")
                            spark.append(day_spark.get(dd, 0))
                        ns_rows[nm] = {"namespace": nm, "total": total_ns, "entities": ent,
                                       "facts": facts, "relations": rel, "last": last, "spark": spark}
                    # timeseries over the requested window (range<=0 → all-time
                    # from the earliest recorded day), gaps filled with 0
                    range_days = _int(qs, "range", 30)
                    base = _dt.datetime.now(_dt.timezone.utc)
                    if range_days and range_days > 0:
                        span = range_days
                    elif by_day:
                        try:
                            ed = _dt.datetime.strptime(min(by_day), "%Y-%m-%d").replace(tzinfo=_dt.timezone.utc)
                            span = (base - ed).days + 1
                        except Exception:
                            span = 30
                    else:
                        span = 30
                    span = max(1, min(span, 366))
                    series = []
                    for i in range(span - 1, -1, -1):
                        dd = (base - _dt.timedelta(days=i)).strftime("%Y-%m-%d")
                        series.append({"date": dd, "count": by_day.get(dd, 0)})
                    reqs = _OPS["requests"]
                    self._json({
                        "totals": {
                            "memories": sum(by_layer.values()),
                            **by_layer,
                            "namespaces": len(names),
                            "entities": entities_total,
                            "relations": relations_total,
                            "sessions": len(sessions),
                            "contradictions": contradictions_total,
                        },
                        "timeseries": series,
                        "by_source": sorted(({"source": k, "count": v} for k, v in by_source.items()),
                                            key=lambda x: x["count"], reverse=True),
                        "by_namespace": sorted(ns_rows.values(), key=lambda x: x["total"], reverse=True),
                        "ops": {
                            "requests": reqs,
                            "avg_latency_ms": round(_OPS["total_ms"] / reqs, 1) if reqs else 0,
                            "error_rate": round(_OPS["errors"] / reqs * 100, 2) if reqs else 0,
                        },
                    })

                elif path == "/api/metrics":
                    agg = {l.value: 0 for l in MemoryLayer}
                    agg["total"] = 0
                    nss = mind.list_namespaces()
                    for item in nss:
                        for k, v in item["stats"].items():
                            agg[k] += v
                        agg["total"] += item["total"]
                    self._json({"namespaces": len(nss), "memories": agg["total"], "by_layer": agg})

                else:
                    self._json({"error": "not found"}, 404)
            except _Http400 as e:
                self._json({"error": str(e)}, 400)
            except Exception as e:
                self._json({"error": str(e)}, 500)

    return Handler


def serve(mind, host: str = "127.0.0.1", port: int = 8420, open_browser: bool = True,
          allow_writes=None):
    is_local = host in ("127.0.0.1", "::1", "localhost")
    token = os.environ.get("LOGICA_MIND_TOKEN")
    if allow_writes is None:
        allow_writes = is_local                # writes on by default only on loopback
    if allow_writes and not is_local and not token:
        raise SystemExit("logica-mind: refusing to enable write endpoints on a non-loopback "
                         "host without LOGICA_MIND_TOKEN set.")
    if allow_writes and not is_local:
        print("⚠️  write endpoints exposed on a non-loopback host — bearer token required.")
    if not is_local and not token:
        # reads are now auth-gated too, so a tokenless non-loopback bind 401s every
        # API call — warn the operator instead of silently shipping a broken board
        print("⚠️  non-loopback host without LOGICA_MIND_TOKEN — all /api reads will "
              "return 401. Set LOGICA_MIND_TOKEN to use the dashboard remotely.")
    httpd = ThreadingHTTPServer((host, port), make_handler(mind, allow_writes=allow_writes, token=token))
    url = f"http://{host}:{port}"
    n = len(mind.store.namespaces())
    print(f"🧠 Logica Mind dashboard → {url}  ({n} namespace{'s' if n != 1 else ''})")
    print("   Ctrl+C to stop.")
    if open_browser:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 dashboard stopped")
    finally:
        httpd.server_close()
