"""Self-model — the evolving, versioned identity of an *agent*.

This is the dual of :class:`DialecticUserModel` (which models the *user*): the
self-model lets an agent **become what it learned**, instead of merely looking it
up. It is the first organ of the **continuity substrate** built on top of Logica
Mind's memory.

Design choices (all matching the rest of the engine):

* **Dependency-injected & self-contained.** Receives a ``store`` (and an optional
  ``clock``); imports nothing outside ``logica_mind``. Because the state lives in
  the store, the identity is *portable*: load it on another machine and the agent
  wakes up as itself, not from zero.
* **Versioned & immutable.** Every :meth:`save` writes a brand-new immutable
  *version* memory **and** upserts a mutable *current* pointer (a fixed id) — both
  in a single :meth:`Store.add` call, so a reader never sees a half-written self.
* **Hash-chained.** Each version carries ``prev_hash``/``hash`` (sha256 over the
  canonical content), giving the identity a tamper-evident, auditable line of
  continuity — you can prove the agent is the same agent, and detect surgery.
* **Optimistic concurrency (compare-and-set).** A save re-reads ``current`` right
  before committing and refuses to fork the chain if someone wrote in between,
  retrying with the fresh state. Single-writer safety without file locks.
* **No catastrophic forgetting.** The merge is an exponential moving average for
  ``skills``/``drives``/``beliefs`` (they *evolve*, never jump) and append-with-cap
  for the hot ``recent`` wins/errors. The full line of versions is kept forever,
  so any past self can be restored.

Quickstart::

    from logica_mind.continuity import SelfModel
    me = SelfModel(store, namespace="astro")
    me.save({"skills": {"copy": 0.8}, "direction": "ângulos de oferta"})
    state = me.load()                 # the current self
    ok, n, why = me.verify_chain()    # tamper-evident integrity check
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..types import Memory, MemoryLayer, now_iso

# Tunables — kept module-level so they are easy to audit and override in tests.
ALPHA = 0.3          # weight of new experience in the moving average (evolve, don't jump)
HOT_RECENT = 12      # how many wins/errors stay "hot" in the current model
MAX_BELIEFS = 30     # cap of hot beliefs (full history lives in the version line)
_CAS_RETRIES = 4     # compare-and-set attempts before giving up


def _drives_default() -> Dict[str, float]:
    return {"curiosity": 0.5, "mastery": 0.5, "coherence": 0.5, "legacy": 0.5}


def _ema(old: Any, new: Any, alpha: float = ALPHA) -> float:
    """Exponential moving average; if there is no prior value, adopt the new one."""
    n = float(new)
    if not isinstance(old, (int, float)):
        return round(n, 3)
    return round(float(old) * (1.0 - alpha) + n * alpha, 3)


class SelfModel:
    """The structured, versioned identity of the agent named by ``namespace``."""

    # fields that constitute the *state* (everything except chain/bookkeeping)
    _STATE_KEYS = ("identity", "skills", "recent", "direction", "drives", "beliefs")

    def __init__(
        self,
        store,
        namespace: str,
        *,
        llm: Optional[object] = None,
        embedder: Optional[object] = None,
        clock: Optional[Callable[[], str]] = None,
    ) -> None:
        self.store = store
        self.namespace = namespace          # the agent this self belongs to
        self.llm = llm                      # reserved (future: LLM-assisted introspection)
        self.embedder = embedder            # reserved (future: embed beliefs)
        self._now = clock or now_iso
        self._current_id = f"self-model::{namespace}::current"

    # ── skeleton & merge ──────────────────────────────────────────────────────
    def _skeleton(self) -> Dict[str, Any]:
        return {
            "agent": self.namespace,
            "version": 0,
            "updated_at": self._now(),
            "identity": "",                       # stable; seeded from the agent's .md
            "skills": {},                         # {domain: confidence 0..1}
            "recent": {"wins": [], "errors": []}, # the HOT_RECENT most recent
            "direction": "",                      # where the agent is evolving
            "drives": _drives_default(),          # internal motivations 0..1
            "beliefs": [],                        # [{text, confidence, ts}]
        }

    def _merge_reweight(self, prev: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
        """Non-destructive merge: EMA for skills/drives/beliefs, append+cap for
        recent. Never deletes — only limits what stays *hot* in the current self.
        """
        nxt = json.loads(json.dumps(prev))   # deep copy
        nxt["version"] = int(prev.get("version", 0)) + 1
        nxt["updated_at"] = self._now()
        nxt["agent"] = self.namespace
        if patch.get("identity"):
            nxt["identity"] = patch["identity"]
        if patch.get("direction"):
            nxt["direction"] = patch["direction"]

        for k, v in (patch.get("skills") or {}).items():
            nxt.setdefault("skills", {})[k] = _ema(nxt.get("skills", {}).get(k), v)
        for k, v in (patch.get("drives") or {}).items():
            nxt.setdefault("drives", _drives_default())[k] = _ema(nxt["drives"].get(k), v)

        recent = patch.get("recent") or {}
        for kind in ("wins", "errors"):
            incoming = recent.get(kind)
            if isinstance(incoming, list) and incoming:
                nxt["recent"][kind] = ([*incoming, *nxt["recent"].get(kind, [])])[:HOT_RECENT]

        incoming_beliefs = patch.get("beliefs")
        if isinstance(incoming_beliefs, list) and incoming_beliefs:
            by_text = {b["text"]: b for b in nxt.get("beliefs", []) if b.get("text")}
            for b in incoming_beliefs:
                if not b or not b.get("text"):
                    continue
                ex = by_text.get(b["text"])
                conf = b.get("confidence", 0.5)
                if ex:
                    ex["confidence"] = _ema(ex.get("confidence"), conf)
                    ex["ts"] = b.get("ts") or self._now()
                else:
                    by_text[b["text"]] = {"text": b["text"], "confidence": round(float(conf), 3),
                                          "ts": b.get("ts") or self._now()}
            nxt["beliefs"] = sorted(by_text.values(), key=lambda x: x["confidence"], reverse=True)[:MAX_BELIEFS]
        return nxt

    # ── hash chain ────────────────────────────────────────────────────────────
    @staticmethod
    def _hash(state: Dict[str, Any]) -> str:
        payload = {k: v for k, v in state.items() if k != "hash"}
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()

    # ── persistence ───────────────────────────────────────────────────────────
    def load(self) -> Dict[str, Any]:
        """The current self (a fresh skeleton if none exists yet)."""
        m = self.store.get(self.namespace, self._current_id)
        if m:
            try:
                state = json.loads(m.content)
                if isinstance(state, dict) and state.get("agent"):
                    return state
            except (ValueError, TypeError):
                pass  # corrupted current → fall through to skeleton (history still intact)
        return self._skeleton()

    def _commit(self, state: Dict[str, Any], prev_hash: str) -> Dict[str, Any]:
        """Write an immutable version + upsert the current pointer, atomically."""
        state["prev_hash"] = prev_hash
        state.pop("hash", None)
        state["hash"] = self._hash(state)
        body = json.dumps(state, ensure_ascii=False)
        meta_common = {"continuity": "self-model", "version": state["version"], "hash": state["hash"]}
        version = Memory(
            content=body, namespace=self.namespace, layer=MemoryLayer.USER,
            id=f"self-model::{self.namespace}::v{state['version']}",
            importance=0.9, metadata={**meta_common, "kind": "version", "prev_hash": prev_hash},
        )
        current = Memory(
            content=body, namespace=self.namespace, layer=MemoryLayer.USER,
            id=self._current_id, importance=0.9, metadata={**meta_common, "kind": "current"},
        )
        self.store.add([version, current])   # single atomic batch — no half-written self
        return state

    def save(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        """Merge ``patch`` into the current self and commit a new version.

        Uses compare-and-set on the current pointer: if another writer committed
        between our read and our write, we re-read and retry instead of forking
        the chain (single-writer safety without locks).
        """
        for _ in range(_CAS_RETRIES):
            prev = self.load()
            prev_hash = prev.get("hash", "")
            nxt = self._merge_reweight(prev, patch or {})
            # CAS: has `current` moved since we read it?
            check = self.store.get(self.namespace, self._current_id)
            check_hash = ""
            if check:
                try:
                    check_hash = json.loads(check.content).get("hash", "")
                except (ValueError, TypeError):
                    check_hash = ""
            if check_hash == prev_hash:
                return self._commit(nxt, prev_hash)
        raise RuntimeError(f"self-model[{self.namespace}]: CAS conflict — concurrent writers, retries exhausted")

    # ── history / integrity / restore ─────────────────────────────────────────
    def versions(self) -> List[Dict[str, Any]]:
        """All immutable versions, oldest → newest."""
        out: List[Dict[str, Any]] = []
        for m in self.store.all(self.namespace, layers=[MemoryLayer.USER]):
            meta = m.metadata or {}
            if meta.get("continuity") == "self-model" and meta.get("kind") == "version":
                try:
                    out.append(json.loads(m.content))
                except (ValueError, TypeError):
                    continue
        out.sort(key=lambda d: d.get("version", 0))
        return out

    def verify_chain(self) -> Tuple[bool, int, str]:
        """Validate the hash chain. Returns ``(ok, version_count, reason)``."""
        prev_hash = ""
        versions = self.versions()
        for v in versions:
            if self._hash(v) != v.get("hash"):
                return (False, v.get("version", -1), "hash mismatch (content tampered)")
            if v.get("prev_hash", "") != prev_hash:
                return (False, v.get("version", -1), "broken link (missing/forked version)")
            prev_hash = v["hash"]
        return (True, len(versions), "ok")

    def restore(self, version: int) -> Dict[str, Any]:
        """Restore an earlier version as the new *current* — recorded as a fresh
        forward version (the line stays linear and auditable; nothing is erased).
        """
        target = next((v for v in self.versions() if v.get("version") == version), None)
        if target is None:
            raise ValueError(f"self-model[{self.namespace}]: version {version} not found")
        cur = self.load()
        restored = {k: json.loads(json.dumps(target.get(k))) for k in self._STATE_KEYS}
        restored["agent"] = self.namespace
        restored["version"] = int(cur.get("version", 0)) + 1
        restored["updated_at"] = self._now()
        restored["restored_from"] = version
        return self._commit(restored, cur.get("hash", ""))

    # ── prompt surface ────────────────────────────────────────────────────────
    def format_for_prompt(self, model: Optional[Dict[str, Any]] = None) -> str:
        """A short block describing who the agent *is* right now, for injection."""
        m = model or self.load()
        skills = ", ".join(f"{k}({v})" for k, v in sorted(
            (m.get("skills") or {}).items(), key=lambda kv: kv[1], reverse=True)[:6])
        beliefs = "\n".join(f"• {b['text']}" for b in (m.get("beliefs") or [])[:4])
        errors = (m.get("recent") or {}).get("errors") or []
        lines = [
            f"EU ({m.get('agent')}, v{m.get('version')}):",
            f"direção: {m['direction']}" if m.get("direction") else None,
            f"forças: {skills}" if skills else None,
            f"erros recentes: {'; '.join(errors[:3])}" if errors else None,
            f"crenças:\n{beliefs}" if beliefs else None,
        ]
        return "\n".join(x for x in lines if x)


# ── tiny CLI: show / history / verify / restore ───────────────────────────────
def _main(argv: Optional[List[str]] = None) -> int:
    import argparse

    from ..stores.sqlite import SQLiteStore

    p = argparse.ArgumentParser(prog="python -m logica_mind.continuity.self_model")
    p.add_argument("cmd", choices=["show", "history", "verify", "restore"])
    p.add_argument("agent")
    p.add_argument("version", nargs="?", type=int)
    args = p.parse_args(argv)

    sm = SelfModel(SQLiteStore(), args.agent)
    if args.cmd == "show":
        print(json.dumps(sm.load(), indent=2, ensure_ascii=False))
    elif args.cmd == "history":
        for v in sm.versions():
            print(f"v{v['version']:<4} {v.get('updated_at')}  hash={v.get('hash', '')[:12]}"
                  f"  dir={v.get('direction', '')[:50]}")
    elif args.cmd == "verify":
        ok, n, why = sm.verify_chain()
        print(f"{'OK' if ok else 'FALHOU'} — {n} versões — {why}")
        return 0 if ok else 1
    elif args.cmd == "restore":
        if args.version is None:
            p.error("restore requer <version>")
        out = sm.restore(args.version)
        print(f"restaurado v{args.version} → nova v{out['version']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
