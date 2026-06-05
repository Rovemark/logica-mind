"""Command-line interface for Logica Mind.

    logica-mind ui [--db PATH] [--namespace NS] [--port 8420]
    logica-mind remember "<text>" [--db ...] [--namespace ...]
    logica-mind recall "<query>" [--limit 8]
    logica-mind dream
    logica-mind stats
"""
from __future__ import annotations

import argparse
import sys

from .core import LogicaMind
from .stores.sqlite import SQLiteStore


def _mind(args) -> LogicaMind:
    # default to the SAME store/embedder/namespace the hooks capture into, so
    # `recall`/`stats`/`ui`/`mcp` see what was auto-captured (matching the vector
    # dimension too). Explicit --db/--namespace override.
    from .hooks import active_store
    db, embedder, ns = active_store(args.db, args.namespace)
    return LogicaMind(namespace=ns, store=SQLiteStore(db), embedder=embedder)


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    p = argparse.ArgumentParser(prog="logica-mind", description="Pluggable multi-store memory.")
    p.add_argument("--db", default=None, help="SQLite path (default: the shared hook store under ~/.logica-mind)")
    p.add_argument("--namespace", default=None, help="memory namespace (default: derived from the current directory)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s_ui = sub.add_parser("ui", help="launch the web dashboard")
    s_ui.add_argument("--host", default="127.0.0.1")
    s_ui.add_argument("--port", type=int, default=8420)
    s_ui.add_argument("--no-open", action="store_true", help="don't open the browser")

    s_rem = sub.add_parser("remember", help="store a fact")
    s_rem.add_argument("text")

    s_rec = sub.add_parser("recall", help="retrieve memories")
    s_rec.add_argument("query")
    s_rec.add_argument("--limit", type=int, default=8)

    sub.add_parser("dream", help="run a consolidation cycle")
    sub.add_parser("stats", help="show per-layer counts")
    sub.add_parser("mcp", help="run as an MCP server over stdio")

    s_demo = sub.add_parser("demo", help="load a fictional demo dataset (or clear it)")
    s_demo.add_argument("--clear", action="store_true", help="remove the demo data instead of loading it")
    s_demo.add_argument("--serve", action="store_true", help="open the dashboard after loading")

    s_hook = sub.add_parser("hook", help="run a session hook (reads host JSON on stdin)")
    s_hook.add_argument("event", choices=["sessionstart", "userpromptsubmit", "stop", "precompact"])

    s_inst = sub.add_parser("install-hooks", help="install session hooks into a settings.json")
    s_inst.add_argument("--settings", default="~/.claude/settings.json",
                        help="target settings.json (default: ~/.claude/settings.json)")

    args = p.parse_args(argv)

    # hooks manage their own store/namespace (per the host's cwd) — handle first
    if args.cmd == "hook":
        from .hooks import run as run_hook
        # explicit --db/--namespace override; otherwise the hook uses its shared
        # ~/.logica-mind store + a cwd-derived namespace
        out = run_hook(args.event, db_override=args.db, namespace_override=args.namespace)
        if out:
            print(out)
        return
    if args.cmd == "install-hooks":
        from .hooks import install
        path, added = install(args.settings)
        print(f"hooks installed in {path}")
        print("added: " + (", ".join(added) if added else "(already present)"))
        return

    mind = _mind(args)

    if args.cmd == "ui":
        mind.serve(host=args.host, port=args.port, open_browser=not args.no_open)
    elif args.cmd == "remember":
        created = mind.remember(args.text)
        print(f"stored {len(created)} memor{'y' if len(created)==1 else 'ies'}:")
        for m in created:
            print(f"  · [{m.layer.value}] {m.content}")
    elif args.cmd == "recall":
        for r in mind.recall(args.query, limit=args.limit):
            print(f"{r.score:.3f}  [{r.memory.layer.value}]  {r.memory.content}")
    elif args.cmd == "dream":
        print("💤 dreaming…")
        print(mind.dream().to_dict())
    elif args.cmd == "stats":
        for k, v in mind.stats().items():
            print(f"{k:>10}: {v}")
    elif args.cmd == "mcp":
        from .mcp_server import serve_stdio
        serve_stdio(mind)
    elif args.cmd == "demo":
        from . import demo as _demo
        if args.clear:
            print(f"🧹 removed {_demo.clear(mind)} demo memories")
        else:
            n = _demo.seed(mind)
            print(f"🌱 loaded {n} fictional demo memories across {len(mind.store.namespaces())} agents")
            print("   clear anytime with:  logica-mind demo --clear")
            if args.serve:
                mind.serve(open_browser=True)


if __name__ == "__main__":
    main()
