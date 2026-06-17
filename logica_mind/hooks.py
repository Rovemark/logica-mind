"""Agent session hooks — automatic capture + injection of long-term memory.

This is the piece that makes Logica Mind *remember your sessions on its own*,
the way Logica Context does: instead of relying on the agent to call a memory
tool, these run on the editor/agent's lifecycle events (Claude Code, and any
host with the same hook contract):

  SessionStart      → inject a brief of what we know about you + past sessions
  UserPromptSubmit  → save what you said + inject memory relevant to this prompt
  Stop              → save what the assistant did (last turn)
  PreCompact        → consolidate before the context window is compacted

Each hook is a fresh process: it reads the host's JSON event on stdin and prints
the host's hook output (additionalContext) on stdout. Hard rules:
  * NEVER raise — a memory hiccup must not break the agent's session.
  * NEVER write anything but the final JSON to stdout (the host reads stdout as
    the hook's output) — all diagnostics go to stderr.
  * Fail fast — a broken/misconfigured embedder must degrade to offline instantly,
    not stall the prompt path on retry backoff.

Wire it up with:  logica-mind install-hooks
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shlex
import shutil
import sys
import threading
import time
from typing import Any, Dict, Optional

from .core import LogicaMind
from .embeddings.base import Embedder
from .stores.sqlite import SQLiteStore

EVENT_NAMES = {
    "sessionstart": "SessionStart",
    "userpromptsubmit": "UserPromptSubmit",
    "stop": "Stop",
    "precompact": "PreCompact",
}

_PROVIDER_DOWN_TTL = 300.0  # seconds a provider stays marked-down before re-probe
_MIN_TURN_LEN = 12          # skip trivial turns ("hi", "ok") when capturing
_CATCHUP_WINDOW = 800       # lines scanned from the transcript tail on every Stop


def _root_dir() -> str:
    d = os.path.expanduser("~/.logica-mind")
    os.makedirs(d, exist_ok=True)
    return d


def _capture_log_path() -> str:
    return os.path.join(_root_dir(), "capture.log")


def _log_failure(msg: str) -> None:
    """Capture is fail-soft, so a broken capture path would otherwise lose memory
    silently. Append failures to a log so they can be noticed and fixed."""
    try:
        with open(_capture_log_path(), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}\n")
    except Exception:
        pass


def default_db_path(fingerprint: str = "default") -> str:
    # one db file per embedder fingerprint, so vectors of different dimensions
    # (voyage-1024 / openai-1024 / hashing-256) never share a store and corrupt recall
    return os.path.join(_root_dir(), f"memory-{fingerprint}.db")


def _sentinel_path() -> str:
    return os.path.join(_root_dir(), ".provider-down")


def _provider_is_down(provider: str) -> bool:
    try:
        with open(_sentinel_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("provider") == provider and float(data.get("expiry", 0)) > time.time()
    except Exception:
        return False


def _mark_provider_down(provider: str) -> None:
    try:
        with open(_sentinel_path(), "w", encoding="utf-8") as f:
            json.dump({"provider": provider, "expiry": time.time() + _PROVIDER_DOWN_TTL}, f)
    except Exception:
        pass


class _GuardedEmbedder(Embedder):
    """Wraps a real embedder so its FIRST failure trips the provider-down
    sentinel (core swallows the exception, so the hook layer can't otherwise see
    it). Subsequent hooks then skip the dead provider and use hashing instantly."""

    def __init__(self, inner: Embedder, provider: str):
        self.inner = inner
        self.provider = provider
        self.name = provider

    @property
    def dim(self) -> int:
        return self.inner.dim

    def embed(self, texts):
        try:
            return self.inner.embed(texts)
        except Exception:
            _mark_provider_down(self.provider)
            raise

    def embed_query(self, text):
        try:
            return self.inner.embed_query(text)
        except Exception:
            _mark_provider_down(self.provider)
            raise


def _resolve_embedder():
    """Return (embedder_or_None, fingerprint). Fail-fast (no retry ladders) and
    skip a provider already marked down. None → caller uses HashingEmbedder."""
    if os.environ.get("VOYAGE_API_KEY") and not _provider_is_down("voyage"):
        try:
            from .embeddings import VoyageEmbedder, BatchedEmbedder
            # pin 1024 dims (Matryoshka) so voyage/openai stay interchangeable;
            # max_retries=1 / base_backoff=0 → at most one network timeout, no sleeps
            inner = BatchedEmbedder(
                VoyageEmbedder(output_dimension=1024, max_retries=1, base_backoff=0.0),
                min_interval=0.0, max_retries=1, base_backoff=0.0,
            )
            return _GuardedEmbedder(inner, "voyage"), "voyage-1024"
        except Exception as e:
            print(f"[logica-mind] voyage embedder unavailable ({e})", file=sys.stderr)
    if os.environ.get("OPENAI_API_KEY") and not _provider_is_down("openai"):
        try:
            from .embeddings import OpenAIEmbedder
            return _GuardedEmbedder(OpenAIEmbedder(dimensions=1024), "openai"), "openai-1024"
        except Exception as e:
            print(f"[logica-mind] openai embedder unavailable ({e})", file=sys.stderr)
    return None, "hashing-256"


def _sanitize(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", (name or "").strip()).strip("-")


def _project_root(cwd: str) -> str:
    """The git/project root for cwd (so subfolders share memory), else cwd."""
    cur = os.path.realpath(cwd)
    for _ in range(40):
        if any(os.path.exists(os.path.join(cur, m)) for m in (".git", "pyproject.toml", "package.json")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return os.path.realpath(cwd)


def _namespace(payload: Dict[str, Any]) -> str:
    pin = os.environ.get("LOGICA_MIND_NAMESPACE")  # monorepo / explicit override
    if pin:
        return _sanitize(pin) or "default"
    cwd = payload.get("cwd") or os.getcwd()
    root = _project_root(cwd)
    base = _sanitize(os.path.basename(root)) or "default"
    # hash the absolute root so two different projects sharing a basename
    # ('app', 'site', a git worktree…) never collide in the shared db
    h = hashlib.sha1(root.encode("utf-8")).hexdigest()[:8]
    return f"{base}-{h}"


def active_store(db_override: Optional[str] = None, namespace_override: Optional[str] = None):
    """The (db_path, embedder, namespace) the hooks use right now, so the
    standalone CLI / MCP server can point at the SAME captured memory + matching
    embedder dimension. Namespace defaults to the current working directory."""
    embedder, fingerprint = _resolve_embedder()
    db = db_override or default_db_path(fingerprint)
    ns = namespace_override or _namespace({})
    return db, embedder, ns


def _build_mind(payload: Dict[str, Any], db_override: Optional[str] = None,
                namespace_override: Optional[str] = None) -> LogicaMind:
    embedder, fingerprint = _resolve_embedder()
    db = db_override or default_db_path(fingerprint)
    ns = namespace_override or _namespace(payload)
    return LogicaMind(namespace=ns, store=SQLiteStore(db), embedder=embedder)


# ---- per-event handlers (return additionalContext text, or None) -----------
def _sessionstart(payload: Dict[str, Any], mind: LogicaMind) -> Optional[str]:
    return mind.session_brief() or None


def _hook_source() -> str:
    """Which client captured this turn (so the dashboard can attribute it).
    Defaults to 'claude-code' since these are Claude Code hooks; override with
    LOGICA_MIND_SOURCE for other hosts."""
    return os.environ.get("LOGICA_MIND_SOURCE", "claude-code")


def _userpromptsubmit(payload: Dict[str, Any], mind: LogicaMind) -> Optional[str]:
    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        return None
    session = payload.get("session_id")
    # retrieval gate: don't embed+recall+inject on trivial turns (greetings, "ok",
    # shell commands); DO force it when the prompt references memory. Saves tokens
    # and stops noise injection on every keystroke-level turn.
    from .guard import should_retrieve
    retrieve, _forced = should_retrieve(prompt)
    # recall PAST memory first, THEN capture — otherwise the current prompt is in
    # the store when we search and gets injected back as "relevant memory".
    # context() returns the sanitized, instruction-framed block (safe=True default).
    ctx = mind.context(prompt, token_budget=800, include_user=False) if retrieve else None
    if not _is_duplicate_of_last(mind, prompt, session):
        mind.log(prompt, role="user", session=session, metadata={"source": _hook_source()})
    return ctx or None


def _is_duplicate_of_last(mind: LogicaMind, prompt: str, session: Optional[str]) -> bool:
    """Skip re-logging a prompt byte-identical to the last user turn in this
    session (the 'continue' / 'fix it' repeat pattern)."""
    if not session:
        return False
    from .types import MemoryLayer
    rows = [m for m in mind.store.all(mind.namespace, [MemoryLayer.EPISODIC])
            if (m.metadata or {}).get("session") == session and (m.metadata or {}).get("role") == "user"]
    if not rows:
        return False
    rows.sort(key=lambda m: m.created_at or "", reverse=True)
    norm = " ".join(prompt.lower().split())
    return " ".join(rows[0].content.lower().split()) == norm


def _norm(s: str) -> str:
    return " ".join((s or "").split()).lower()


def _turn_hash(text: str) -> str:
    return hashlib.sha1(_norm(text).encode("utf-8")).hexdigest()


def _iter_transcript_turns(transcript_path: str, window: Optional[int] = None):
    """Yield (role, text) for every user/assistant TEXT turn in the transcript.
    Tool-result turns, slash commands and injected blocks are skipped. `window`
    bounds the scan to the last N lines (None = whole file, used by backfill)."""
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return
    if window:
        lines = lines[-window:]
    for line in lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = obj.get("message", obj)
        if not isinstance(msg, dict):
            continue
        role = msg.get("role") or obj.get("type")
        if role not in ("user", "assistant"):
            continue
        content = msg.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = "\n".join(c.get("text", "") for c in content
                             if isinstance(c, dict) and c.get("type") == "text")
        else:
            text = ""
        text = (text or "").strip()
        if len(text) < _MIN_TURN_LEN:
            continue
        # skip slash commands and host-injected blocks (e.g. <logica-memory>…)
        if role == "user" and (text.startswith("/") or text.startswith("<")):
            continue
        yield role, text[:4000]


def _session_seen_hashes(mind: LogicaMind, session: Optional[str]) -> set:
    """Normalized-content hashes already stored for this session, so catch-up
    never double-logs what UserPromptSubmit (or a prior Stop) already captured."""
    from .types import MemoryLayer
    seen = set()
    try:
        for m in mind.store.all(mind.namespace, [MemoryLayer.EPISODIC]):
            if not session or (m.metadata or {}).get("session") == session:
                seen.add(_turn_hash(m.content))
    except Exception:
        pass
    return seen


def _capture_turns(mind: LogicaMind, transcript_path: str, session: Optional[str],
                   window: Optional[int] = None) -> int:
    """Reconcile a transcript against the store: log every user/assistant turn
    not already captured. This is the self-healing core — it recovers turns whose
    live capture failed and whole sessions that predate the hook. Returns the
    number of new turns stored."""
    seen = _session_seen_hashes(mind, session)
    n = 0
    for role, text in _iter_transcript_turns(transcript_path, window):
        h = _turn_hash(text)
        if h in seen:
            continue
        seen.add(h)
        try:
            mind.log(text, role=role, session=session, metadata={"source": _hook_source()})
            n += 1
        except Exception as e:
            # leave the rest for the next Stop to retry, but record why
            _log_failure(f"capture failed (session={session}, role={role}): {e}")
            break
    return n


def _stop(payload: Dict[str, Any], mind: LogicaMind) -> None:
    """Capture the whole turn (user + assistant), reconciling against the store so
    nothing is double-logged and any previously-missed turn is recovered."""
    tp = payload.get("transcript_path")
    if not tp or not os.path.exists(tp):
        return
    try:
        _capture_turns(mind, tp, payload.get("session_id"), window=_CATCHUP_WINDOW)
    except Exception as e:
        _log_failure(f"stop catch-up failed: {e}")


def _transcript_cwd(transcript_path: str) -> Optional[str]:
    """The working directory recorded in a transcript, so a backfill lands in the
    SAME namespace the live hook would have used (not the transcript's folder)."""
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(o, dict) and o.get("cwd"):
                    return o["cwd"]
    except OSError:
        pass
    return None


def backfill(transcript_path: str, db_override: Optional[str] = None,
             namespace_override: Optional[str] = None) -> Dict[str, Any]:
    """Import a past transcript into memory (whole file, dedup-aware). For sessions
    that predate the hook or ran while capture was down. Idempotent: re-running
    only adds turns not already stored."""
    transcript_path = os.path.expanduser(transcript_path)
    cwd = _transcript_cwd(transcript_path) or os.path.dirname(os.path.abspath(transcript_path))
    mind = _build_mind({"cwd": cwd}, db_override, namespace_override)
    session = os.path.splitext(os.path.basename(transcript_path))[0]
    n = _capture_turns(mind, transcript_path, session, window=None)
    return {"transcript": transcript_path, "namespace": mind.namespace, "captured": n}


def _precompact(payload: Dict[str, Any], mind: LogicaMind) -> None:
    # consolidate (distill + reinforce + prune stale episodic) before context is
    # lost, but never block the host's compaction beyond a small wall-clock budget
    budget = float(os.environ.get("LOGICA_MIND_PRECOMPACT_BUDGET", "5"))

    def _work():
        try:
            mind.dream(prune=True, synthesize_user=False)
        except Exception:
            pass

    t = threading.Thread(target=_work, daemon=True)
    t.start()
    t.join(timeout=budget)  # if it overruns, the daemon finishes in the background


def handle(event: str, payload: Dict[str, Any], mind: LogicaMind) -> Optional[Dict[str, Any]]:
    ev = (event or "").lower()
    ctx: Optional[str] = None
    if ev == "sessionstart":
        ctx = _sessionstart(payload, mind)
    elif ev == "userpromptsubmit":
        ctx = _userpromptsubmit(payload, mind)
    elif ev == "stop":
        _stop(payload, mind)
    elif ev == "precompact":
        _precompact(payload, mind)

    if ctx:
        return {"hookSpecificOutput": {
            "hookEventName": EVENT_NAMES.get(ev, event),
            "additionalContext": ctx,
        }}
    return None


def run(event: str, stdin_text: Optional[str] = None,
        db_override: Optional[str] = None, namespace_override: Optional[str] = None) -> str:
    """Read the host's hook JSON, act, and return the hook output (or '').
    Never raises and never writes anything but the returned JSON to stdout."""
    try:
        raw = stdin_text if stdin_text is not None else sys.stdin.read()
    except Exception:
        raw = ""
    try:
        payload = json.loads(raw) if raw and raw.strip() else {}
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    out = None
    try:
        # any library stdout chatter (embedder/graph diagnostics) must NOT land on
        # the channel the host reads as the hook's output → send it to stderr
        with contextlib.redirect_stdout(sys.stderr):
            mind = _build_mind(payload, db_override, namespace_override)
            out = handle(event, payload, mind)
    except Exception as e:
        print(f"[logica-mind] hook {event} failed: {e}", file=sys.stderr)
        out = None
    return json.dumps(out) if out else ""


# ---- install ----------------------------------------------------------------
def _hook_invocation() -> str:
    """The command the host should run. Prefer the console script if on PATH,
    else pin the exact interpreter that has the package installed."""
    exe = shutil.which("logica-mind")
    if exe:
        return shlex.quote(exe)
    return f"{shlex.quote(sys.executable)} -m logica_mind"


def hook_config() -> Dict[str, Any]:
    base = _hook_invocation()
    cfg = {}
    for event_name, sub in (
        ("SessionStart", "sessionstart"),
        ("UserPromptSubmit", "userpromptsubmit"),
        ("Stop", "stop"),
        ("PreCompact", "precompact"),
    ):
        cfg[event_name] = [{"hooks": [{"type": "command", "command": f"{base} hook {sub}"}]}]
    return cfg


def install(settings_path: str):
    """Merge the session hooks into a settings.json (idempotent). Refuses to
    overwrite an existing-but-invalid file; writes atomically. Returns
    (resolved_path, list_of_events_added)."""
    settings_path = os.path.expanduser(settings_path)
    parent = os.path.dirname(settings_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    data: Dict[str, Any] = {}
    if os.path.isfile(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            raise SystemExit(f"logica-mind: cannot read {settings_path}: {e}")
        if text.strip():
            try:
                data = json.loads(text)
            except json.JSONDecodeError as e:
                raise SystemExit(
                    f"logica-mind: {settings_path} is not valid JSON ({e}); refusing to "
                    f"overwrite. Fix or remove it, then re-run install-hooks."
                )
            if not isinstance(data, dict):
                raise SystemExit(f"logica-mind: {settings_path} is JSON but not an object; refusing to overwrite.")

    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise SystemExit(f"logica-mind: 'hooks' in {settings_path} is not an object; refusing to overwrite.")
    added = []
    for event_name, entry in hook_config().items():
        existing = hooks.get(event_name, [])
        if not isinstance(existing, list):
            existing = []
        cmd = entry[0]["hooks"][0]["command"]
        already = False
        for grp in existing:
            if not isinstance(grp, dict):
                continue
            hlist = grp.get("hooks")
            if not isinstance(hlist, list):
                hlist = []
            if any(isinstance(h, dict) and h.get("command") == cmd for h in hlist):
                already = True
                break
        if already:
            continue
        hooks[event_name] = existing + entry
        added.append(event_name)

    if added:  # don't rewrite (and renormalize) the file when nothing changed
        tmp = settings_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, settings_path)  # atomic
    return settings_path, added
