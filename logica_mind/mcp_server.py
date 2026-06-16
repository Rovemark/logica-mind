"""Model Context Protocol (MCP) server for Logica Mind.

Exposes the memory verbs as MCP tools so any MCP client — Claude Code, Cursor,
Windsurf — can use Logica Mind as its memory. Implements JSON-RPC 2.0 over stdio
(newline-delimited) with the standard handshake, using only the standard library.

Run it via the CLI:  logica-mind mcp --db mind.db --namespace my-agent
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
from typing import Any, Dict, Optional

from . import devtools

PROTOCOL_VERSION = "2024-11-05"
SUPPORTED_VERSIONS = {PROTOCOL_VERSION}  # extend as new revisions are implemented

# Tools that act on the MACHINE THE CLIENT RUNS ON (sandboxed execute, repo scan,
# git context, token budget…). They are never forwarded to a remote brain — the
# repo being scanned is the local one, not the server's.
LOCAL_TOOLS = {"lm_execute", "lm_scan", "lm_git", "lm_mcp", "lm_budget"}

TOOLS = [
    {
        "name": "lm_remember",
        "description": "Store a durable fact/note in long-term memory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "the fact to remember"},
                "session": {"type": "string", "description": "optional session/run scope"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "lm_recall",
        "description": "Retrieve the most relevant memories for a query.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 8},
                "session": {"type": "string"},
                "compact": {"type": "boolean", "description": "return bare content lines (token-cheap)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "lm_context",
        "description": "Assemble a context block (user model + relevant memory) within a token budget.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "profile": {"type": "string", "enum": ["speed", "balanced", "deep"],
                            "description": "speed = sub-second (skip graph), deep = wider pool"},
                "token_budget": {"type": "integer", "default": 1500},
            },
            "required": ["query"],
        },
    },
    {
        "name": "lm_ask_about_user",
        "description": "Answer a question about the user, reasoning over the dialectic user model.",
        "inputSchema": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
    },
    {
        "name": "lm_observe_user",
        "description": "Record an observation about the user (feeds the dialectic user model).",
        "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    },
    {
        "name": "lm_observe_peer",
        "description": "Record what one peer (observer) learned about another (observed) — directional theory-of-mind.",
        "inputSchema": {
            "type": "object",
            "properties": {"observer": {"type": "string"}, "observed": {"type": "string"}, "text": {"type": "string"}},
            "required": ["observer", "observed", "text"],
        },
    },
    {
        "name": "lm_peer_card",
        "description": "What `observer` knows/believes about `observed` (a directional profile).",
        "inputSchema": {
            "type": "object",
            "properties": {"observer": {"type": "string"}, "observed": {"type": "string"}},
            "required": ["observer", "observed"],
        },
    },
    {
        "name": "lm_peer_query",
        "description": "Ask what `observer` would say about `observed` (theory-of-mind query).",
        "inputSchema": {
            "type": "object",
            "properties": {"observer": {"type": "string"}, "observed": {"type": "string"}, "question": {"type": "string"}},
            "required": ["observer", "observed", "question"],
        },
    },
    {
        "name": "lm_ingest_conversation",
        "description": "Ingest a full conversation (list of {role, content}): logs turns, extracts facts, derives user observations.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "messages": {"type": "array", "items": {"type": "object",
                    "properties": {"role": {"type": "string"}, "content": {"type": "string"}}}},
                "session": {"type": "string"},
            },
            "required": ["messages"],
        },
    },
    {
        "name": "lm_reflect",
        "description": "Synthesize insights from recent memories (what changed / what's notable).",
        "inputSchema": {"type": "object", "properties": {"window": {"type": "integer", "default": 12}}},
    },
    {
        "name": "lm_contradictions",
        "description": "Facts whose object changed over time (a subject+predicate with more than one value in its history).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "lm_diff",
        "description": "Memory changelog — what was learned within a time window [since, until].",
        "inputSchema": {
            "type": "object",
            "properties": {"since": {"type": "string", "description": "ISO timestamp"}, "until": {"type": "string"}},
            "required": ["since"],
        },
    },
    {
        "name": "lm_forget",
        "description": "Delete memories by id or by semantic query.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "query": {"type": "string"},
            },
        },
    },
    {
        "name": "lm_stats",
        "description": "Per-layer counts of stored memories.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "lm_dimensions",
        "description": "The categorization profile: facts grouped by life/work dimension and Maslow tier, with the open categories under each.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "lm_connected",
        "description": "Derived backlinks for a memory — entities it mentions, the relations among them, and other memories that touch the same entities or category. No manual links needed.",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string", "description": "the memory id"}},
            "required": ["id"],
        },
    },
    {
        "name": "lm_how_related",
        "description": "How is entity A related to entity B? Returns the confidence-weighted shortest path between them as an ordered chain of typed relationships.",
        "inputSchema": {
            "type": "object",
            "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
            "required": ["a", "b"],
        },
    },
    {
        "name": "lm_bridges",
        "description": "Load-bearing connectors: entities whose removal would fragment the graph (articulation points) — the brokers between otherwise-separate clusters.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "lm_suggested_links",
        "description": "Predict the missing edge: entity pairs with no direct relation but a strong shared neighbourhood (Adamic-Adar). The links you probably should have but never authored.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    # ---- coding-context devtools ----
    {
        "name": "lm_execute",
        "description": "Run a command and return a token-saving summary (truncated output).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "lang": {"type": "string", "description": "bash | python | node | ruby | deno", "default": "bash"},
                "cwd": {"type": "string", "description": "working directory (defaults to server cwd)"},
                "timeout": {"type": "integer", "default": 30},
            },
            "required": ["command"],
        },
    },
    {
        "name": "lm_scan",
        "description": "Project DNA — detect languages, frameworks, key files, structure.",
        "inputSchema": {"type": "object", "properties": {"cwd": {"type": "string"}}},
    },
    {
        "name": "lm_git",
        "description": "Git-aware status — branch, ahead/behind, staged files, recent commits, diff.",
        "inputSchema": {"type": "object", "properties": {"cwd": {"type": "string"}}},
    },
    {
        "name": "lm_mcp",
        "description": "List active MCP servers and estimate their context cost.",
        "inputSchema": {"type": "object", "properties": {"cwd": {"type": "string"}}},
    },
    {
        "name": "lm_budget",
        "description": "Render a context-budget meter from token counts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "used": {"type": "integer"},
                "limit": {"type": "integer", "default": 200000},
                "saved": {"type": "integer", "default": 0},
            },
            "required": ["used"],
        },
    },
    {
        "name": "lm_team_push",
        "description": "Push knowledge to the shared team knowledge base.",
        "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    },
    {
        "name": "lm_team_search",
        "description": "Search the shared team knowledge base.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "default": 8}},
            "required": ["query"],
        },
    },
    {
        "name": "lm_forget_about",
        "description": "GDPR-native erase: delete every memory that mentions a given entity across all layers + the graph. One call covers the full namespace — use for right-to-be-forgotten or cleaning up a person/project.",
        "inputSchema": {
            "type": "object",
            "properties": {"entity": {"type": "string", "description": "Entity name to erase (e.g. 'Acme Inc', 'ProjectX')"}},
            "required": ["entity"],
        },
    },
    {
        "name": "lm_forget_curve",
        "description": "Ebbinghaus forgetting curve: list beliefs predicted to decay in the next 7 days, sorted by most-at-risk first. Shows current retention %, projected strength, and days since last recall. Use to decide what to re-read or reinforce.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "days_halflife": {"type": "number", "default": 30, "description": "Half-life of retention in days"},
                "limit": {"type": "integer", "default": 20},
                "apply": {"type": "boolean", "default": False, "description": "If true, actually apply decay to importance scores"},
            },
        },
    },
    {
        "name": "lm_contested_beliefs",
        "description": "Return pairs of beliefs where BOTH sides had high confidence when one superseded the other — epistemic contests. The system admits conflicting beliefs rather than silently overwriting. Use to surface uncertainty.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "threshold": {"type": "number", "default": 0.65, "description": "Minimum confidence to flag as contested"},
            },
        },
    },
    {
        "name": "lm_surprise_events",
        "description": "List paradigm shifts: beliefs that contradicted prior high-confidence beliefs with large divergence. surprise_score = old_importance × cosine_distance. High score = the agent's worldview changed significantly.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "since": {"type": "string", "description": "ISO datetime lower bound (optional)"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "lm_dream",
        "description": "Run a sleep-time memory consolidation cycle: consolidate episodic→semantic, reinforce recalled memories, prune stale, derive user observations, infer new links. Returns a structured report of what happened.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "infer_links": {"type": "boolean", "default": False, "description": "Also infer new knowledge via inductive reasoning"},
                "extract_graph": {"type": "boolean", "default": False, "description": "Extract graph edges from episodic batch"},
            },
        },
    },
    {
        "name": "lm_record_session",
        "description": "Record a structured multi-agent/multi-step RUN as a rich memory: a title, the participants (any agent/human/tool/model, each with a free-form role, optional contribution text and metrics), aggregate metrics (tokens/cost/score/duration…), status, and links. Generic — maps onto any framework (CrewAI, LangGraph, AutoGen, your own). Stores one rich session-record + one linked memory per participant contribution, so the run becomes queryable, recallable history. Use this at the end of an orchestrated task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Headline / task of the run"},
                "session_id": {"type": "string", "description": "Optional id to group the run (auto-generated if omitted)"},
                "participants": {
                    "type": "array",
                    "description": "Who took part",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "role": {"type": "string", "description": "Free-form: agent, clone, mentor, human, tool, model…"},
                            "contribution": {"type": "string", "description": "What this participant produced"},
                            "metrics": {"type": "object", "description": "Per-participant metrics (e.g. {score: 100})"},
                        },
                        "required": ["name"],
                    },
                },
                "status": {"type": "string", "default": "completed"},
                "metrics": {"type": "object", "description": "Aggregate metrics, e.g. {tokens: 28713, cost_usd: 0.2, score: 95}"},
                "links": {"type": "object", "description": "Related references, e.g. {daily: '2026-04-09', parent: 'sess_…'}"},
                "summary": {"type": "string", "description": "Optional human-readable outcome/body"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title"],
        },
    },
]


class MCPServer:
    def __init__(self, mind, name: str = "logica-mind", remote_url: Optional[str] = None):
        self.mind = mind
        self.name = name
        self._team = None  # memoized remote team mind (or None)
        # the connecting client (e.g. 'claude-code', 'cursor', 'chatgpt'), learned
        # from the MCP initialize handshake; tags captured memories with their origin
        self.source = os.environ.get("LOGICA_MIND_SOURCE")
        # CLUSTER MODE: when the brain lives on another machine (one server, many
        # clients), LOGICA_MIND_URL points the MCP at it — every memory tool is
        # forwarded to the server's /api/mcp/dispatch (which runs the SAME dispatch
        # against the real store + embedder), while LOCAL_TOOLS keep running here.
        if remote_url is None:
            remote_url = os.environ.get("LOGICA_MIND_URL", "")
        self.remote_url = (remote_url or "").rstrip("/") or None

    # ---- JSON-RPC plumbing -------------------------------------------------
    @staticmethod
    def _result(rid: Any, result: Any) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    @staticmethod
    def _error(rid: Any, code: int, message: str) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}

    @staticmethod
    def _text(payload: Any, is_error: bool = False) -> Dict[str, Any]:
        text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        return {"content": [{"type": "text", "text": text}], "isError": is_error}

    def handle(self, req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle one JSON-RPC request. Returns a response dict, or None for
        notifications (no id / fire-and-forget)."""
        method = req.get("method")
        rid = req.get("id")
        is_notification = "id" not in req

        resp: Optional[Dict[str, Any]] = None
        if method == "initialize":
            # negotiate: honor the client's version only if we support it, else
            # advertise our own latest and let the client decide
            params = req.get("params") or {}
            client_proto = params.get("protocolVersion")
            proto = client_proto if client_proto in SUPPORTED_VERSIONS else PROTOCOL_VERSION
            # remember WHICH client connected, so captured memories are attributable.
            # Any spec-compliant MCP client sends clientInfo.name automatically
            # (claude-code, cursor, antigravity, windsurf…). If a client omits it,
            # fall back to a generic 'mcp' so the capture is still marked as "via MCP".
            ci = params.get("clientInfo") or {}
            if not self.source:
                self.source = str(ci.get("name") or "mcp")
            resp = self._result(rid, {
                "protocolVersion": proto,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": self.name, "version": "0.1.0"},
            })
        elif method in ("notifications/initialized", "initialized"):
            resp = None
        elif method == "ping":
            resp = self._result(rid, {})
        elif method == "tools/list":
            resp = self._result(rid, {"tools": TOOLS})
        elif method == "tools/call":
            resp = self._tools_call(rid, req.get("params") or {})
        elif not is_notification:
            resp = self._error(rid, -32601, f"Method not found: {method}")

        # a notification (no 'id') must NEVER get a reply, whatever the method
        return None if is_notification else resp

    # ---- tools -------------------------------------------------------------
    def _tools_call(self, rid: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            spec = next((t for t in TOOLS if t["name"] == name), None)
            if spec is None:
                raise ValueError(f"Unknown tool: {name}")
            # clean message for missing required args instead of a raw KeyError
            for req_key in spec["inputSchema"].get("required", []):
                if args.get(req_key) in (None, ""):
                    raise ValueError(f"missing required argument: {req_key}")
            # library diagnostics (embedder/graph) must not pollute the JSON-RPC
            # stdout stream — keep them on stderr
            with contextlib.redirect_stdout(sys.stderr):
                payload = self._dispatch(name, args)
            return self._result(rid, self._text(payload))
        except Exception as e:  # surface tool errors as isError content, not RPC error
            return self._result(rid, self._text(f"{type(e).__name__}: {e}", is_error=True))

    def _remote_dispatch(self, name: str, args: Dict[str, Any]) -> Any:
        """Forward one memory-tool call to the remote brain's /api/mcp/dispatch."""
        import urllib.error
        import urllib.request
        body = json.dumps({"name": name, "args": args, "source": self.source,
                           "namespace": getattr(self.mind, "namespace", None)}).encode()
        headers = {"Content-Type": "application/json"}
        token = os.environ.get("LOGICA_MIND_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(f"{self.remote_url}/api/mcp/dispatch",
                                     data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r).get("result")
        except urllib.error.HTTPError as e:
            detail = ""
            with contextlib.suppress(Exception):
                detail = json.loads(e.read()).get("error", "")
            raise RuntimeError(f"remote brain rejected {name}: HTTP {e.code} {detail}".strip())
        except Exception as e:
            raise RuntimeError(f"remote brain unreachable at {self.remote_url}: {e}")

    def _dispatch(self, name: str, args: Dict[str, Any]) -> Any:
        if self.remote_url and name not in LOCAL_TOOLS:
            return self._remote_dispatch(name, args)
        m = self.mind
        src_meta = {"source": self.source} if self.source else None
        if name == "lm_remember":
            created = m.remember(args["text"], session=args.get("session"), metadata=src_meta)
            return {"stored": [c.content for c in created], "count": len(created),
                    "facts": [{"content": c.content,
                               "category": (c.metadata or {}).get("category"),
                               "dimension": (c.metadata or {}).get("dimension")} for c in created]}
        if name == "lm_recall":
            hits = m.recall(args["query"], limit=int(args.get("limit", 8)), session=args.get("session"))
            # compact=true → bare content lines, ~3x cheaper tokens for the agent
            if args.get("compact"):
                return [h.memory.content for h in hits]
            return [{"score": round(h.score, 4), "layer": h.memory.layer.value,
                     "content": h.memory.content,
                     "category": (h.memory.metadata or {}).get("category"),
                     "dimension": (h.memory.metadata or {}).get("dimension")} for h in hits]
        if name == "lm_dimensions":
            return m.dimensions()
        if name == "lm_connected":
            return m.connections(args["id"])
        if name == "lm_how_related":
            return m.how_related(args["a"], args["b"])
        if name == "lm_bridges":
            return {"bridges": m.bridges()}
        if name == "lm_suggested_links":
            return {"suggested": m.suggested_links()}
        if name == "lm_context":
            return m.context(args["query"], token_budget=int(args.get("token_budget", 1500)),
                             profile=args.get("profile", "balanced"))
        if name == "lm_ask_about_user":
            return m.ask_about_user(args["question"])
        if name == "lm_observe_user":
            mem = m.observe_user(args["text"])
            return {"ok": bool(mem)}
        if name == "lm_observe_peer":
            mem = m.observe_peer(args["observer"], args["observed"], args["text"])
            return {"ok": bool(mem)}
        if name == "lm_peer_card":
            return {"card": m.peer_card(args["observer"], args["observed"])}
        if name == "lm_peer_query":
            return {"answer": m.peer_query(args["observer"], args["observed"], args["question"])}
        if name == "lm_ingest_conversation":
            msgs = args["messages"]
            if not isinstance(msgs, list):
                raise ValueError("messages must be an array of {role, content} objects")
            return m.ingest_conversation(msgs, session=args.get("session"), source=self.source)
        if name == "lm_reflect":
            return {"insight": m.reflect(window=int(args.get("window", 12)), store_result=False)}
        if name == "lm_contradictions":
            return m.contradictions()
        if name == "lm_diff":
            return m.diff(args["since"], until=args.get("until"))
        if name == "lm_forget":
            return {"deleted": m.forget(memory_id=args.get("id"), query=args.get("query"))}
        if name == "lm_stats":
            return m.stats()

        # ---- coding-context devtools ----
        if name == "lm_execute":
            return devtools.execute(args["command"], lang=args.get("lang", "bash"),
                                    cwd=args.get("cwd"), timeout=int(args.get("timeout", 30)))
        if name == "lm_scan":
            return devtools.scan(args.get("cwd"))
        if name == "lm_git":
            return devtools.git(args.get("cwd"))
        if name == "lm_mcp":
            return devtools.mcp_aggregate(args.get("cwd"))
        if name == "lm_budget":
            return devtools.budget_bar(int(args.get("used", 0)),
                                       int(args.get("limit", 200000)),
                                       int(args.get("saved", 0)))
        if name == "lm_team_push":
            return self._team_op(lambda mind: {"stored": len(mind.remember(args["text"]))})
        if name == "lm_team_search":
            return self._team_op(lambda mind: [
                {"score": round(h.score, 4), "content": h.memory.content}
                for h in mind.recall(args["query"], limit=int(args.get("limit", 8)))
            ])
        if name == "lm_forget_about":
            return {"deleted": m.forget_about(args["entity"])}
        if name == "lm_forget_curve":
            return m.forget_curve(
                days_halflife=float(args.get("days_halflife", 30)),
                apply=bool(args.get("apply", False)),
                limit=int(args.get("limit", 20)),
            )
        if name == "lm_contested_beliefs":
            return m.contested_beliefs(confidence_threshold=float(args.get("threshold", 0.65)))
        if name == "lm_surprise_events":
            return m.surprise_events(since=args.get("since"), limit=int(args.get("limit", 20)))
        if name == "lm_dream":
            report = m.dream(
                infer_links=bool(args.get("infer_links", False)),
                extract_graph=bool(args.get("extract_graph", False)),
            )
            return report.to_dict()
        if name == "lm_record_session":
            rec = m.record_session(
                title=args["title"],
                session_id=args.get("session_id"),
                participants=args.get("participants") or [],
                status=str(args.get("status", "completed")),
                metrics=args.get("metrics") or {},
                links=args.get("links") or {},
                summary=args.get("summary"),
                tags=args.get("tags") or [],
            )
            return {"ok": True, "id": rec.id, "session": (rec.metadata or {}).get("session")}

        raise ValueError(f"Unknown tool: {name}")

    # ---- team knowledge base ----------------------------------------------
    def _team_op(self, op):
        """Run a team-KB op against the shared remote when available, falling back
        to the local 'team' namespace on ANY runtime failure (dead/misconfigured
        remote) — not just construction."""
        remote = self._remote_team_mind()
        if remote is not None:
            try:
                return op(remote)
            except Exception as e:
                print(f"[logica-mind] team KB remote op failed, using local ({e})", file=sys.stderr)
        return op(self.mind.for_namespace("team"))

    def _remote_team_mind(self):
        """Supabase-backed 'team' mind when configured AND a production embedder is
        active (a shared cross-machine table must stay in one coherent vector
        space — never write offline hashing vectors into it). Memoized."""
        if self._team is not None:
            return self._team
        has_supabase = os.environ.get("SUPABASE_URL") and (
            os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")
        )
        emb = self.mind.embedder
        # shared cross-machine table is vector(1024) → require a 1024-dim provider
        is_real = getattr(emb, "name", "") != "hashing" and getattr(emb, "dim", 0) == 1024
        if has_supabase and is_real:
            try:
                from .stores import SupabaseStore
                from .core import LogicaMind
                self._team = LogicaMind(namespace="team", store=SupabaseStore(), embedder=emb)
                return self._team
            except Exception as e:
                print(f"[logica-mind] team KB construction failed, using local ({e})", file=sys.stderr)
        elif has_supabase and not is_real:
            print(
                "[logica-mind] refusing the shared Supabase team KB with the offline "
                f"'{getattr(emb, 'name', 'hashing')}' embedder (dim={getattr(emb, 'dim', '?')}): "
                "it would mix vector dimensions in the cross-machine table. Set "
                "VOYAGE_API_KEY/OPENAI_API_KEY for a production embedder. Using local team store.",
                file=sys.stderr,
            )
        return None

    # ---- stdio loop --------------------------------------------------------
    def serve_stdio(self, stdin=None, stdout=None) -> None:
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                self._write(stdout, self._error(None, -32700, "Parse error"))
                continue
            if not isinstance(req, dict):
                # JSON-RPC batch arrays / bare scalars aren't supported objects
                self._write(stdout, self._error(None, -32600, "Invalid Request"))
                continue
            try:
                resp = self.handle(req)
            except Exception as e:  # one bad request must never kill the loop
                self._write(stdout, self._error(req.get("id"), -32603,
                                                f"Internal error: {type(e).__name__}: {e}"))
                continue
            if resp is not None:
                self._write(stdout, resp)

    @staticmethod
    def _write(stdout, obj: Dict[str, Any]) -> None:
        stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        stdout.flush()


def serve_stdio(mind, name: str = "logica-mind") -> None:
    MCPServer(mind, name=name).serve_stdio()
