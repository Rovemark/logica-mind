"""Coding-context devtools — the non-memory half of a coding-agent context server.

These give an agent the same token-saving / project-awareness powers a dedicated
context tool has, with no third-party deps (stdlib subprocess/os/json):

  execute       run a command and return a TOKEN-SAVING summary (truncated I/O)
  scan          Project DNA — languages, frameworks, key files, structure
  git           branch, ahead/behind, staged files, recent commits, diff stat
  mcp_aggregate read .mcp.json, list MCP servers + estimated context cost
  budget_bar    render a context-budget meter from token counts

Note: `execute` runs in the host process (timeout + output cap), not a hardened
security sandbox — its value is collapsing huge command output into a few tokens.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

_SKIP_DIRS = {".git", "node_modules", "dist", "build", ".next", ".venv", "venv",
              "__pycache__", ".pytest_cache", "target", ".idea", ".turbo", "coverage"}

_EXT_LANG = {
    ".py": "Python", ".ts": "TypeScript", ".tsx": "TypeScript", ".js": "JavaScript",
    ".jsx": "JavaScript", ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".java": "Java",
    ".kt": "Kotlin", ".swift": "Swift", ".c": "C", ".h": "C", ".cpp": "C++",
    ".cs": "C#", ".php": "PHP", ".sql": "SQL", ".sh": "Shell", ".scala": "Scala",
    ".ex": "Elixir", ".dart": "Dart", ".lua": "Lua", ".r": "R",
}

_KEY_FILES = ["package.json", "tsconfig.json", "pyproject.toml", "requirements.txt",
              "go.mod", "Cargo.toml", "Gemfile", "pom.xml", "Dockerfile",
              "docker-compose.yml", "Makefile", ".env.example", "vercel.json"]


def _truncate(text: str, max_chars: int) -> Tuple[str, bool]:
    text = text or ""
    if max_chars <= 0:
        return "", bool(text)          # nothing to keep; flag input was dropped
    if len(text) <= max_chars:
        return text, False
    half = max_chars // 2
    head = text[:half]
    tail = text[-half:] if half else ""   # avoid text[-0:] == whole string
    return head + f"\n… [{len(text) - max_chars} chars elided] …\n" + tail, True


def execute(command: str, lang: str = "bash", cwd: Optional[str] = None,
            timeout: int = 30, max_output: int = 4000) -> Dict[str, Any]:
    cwd = cwd or os.getcwd()
    lang = (lang or "bash").lower()
    try:
        if lang in ("bash", "sh", "shell", ""):
            args, kwargs = command, {"shell": True}
        elif lang == "python":
            args, kwargs = [sys.executable, "-c", command], {}
        elif lang in ("node", "javascript", "js"):
            args, kwargs = ["node", "-e", command], {}
        elif lang in ("ruby", "rb"):
            args, kwargs = ["ruby", "-e", command], {}
        elif lang == "deno":
            args, kwargs = ["deno", "eval", command], {}
        else:
            args, kwargs = command, {"shell": True}  # fall back to shell
        proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                              timeout=timeout, **kwargs)
        out, out_trunc = _truncate(proc.stdout, max_output)
        err, err_trunc = _truncate(proc.stderr, max_output)
        return {"exit_code": proc.returncode, "stdout": out, "stderr": err,
                "truncated": out_trunc or err_trunc}
    except subprocess.TimeoutExpired:
        return {"exit_code": None, "error": f"timed out after {timeout}s"}
    except FileNotFoundError as e:
        return {"exit_code": None, "error": f"interpreter not found: {e}"}


def _read_json(path: str) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def scan(cwd: Optional[str] = None, max_files: int = 20000) -> Dict[str, Any]:
    cwd = cwd or os.getcwd()
    counts: Dict[str, int] = {}
    n = 0
    for root, dirs, files in os.walk(cwd):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            if ext in _EXT_LANG:
                counts[ext] = counts.get(ext, 0) + 1
            n += 1
            if n >= max_files:
                break
        if n >= max_files:
            break

    langs: Dict[str, int] = {}
    for ext, c in counts.items():
        langs[_EXT_LANG[ext]] = langs.get(_EXT_LANG[ext], 0) + c
    languages = sorted(langs.items(), key=lambda kv: kv[1], reverse=True)

    frameworks: List[str] = []
    pkg = _read_json(os.path.join(cwd, "package.json"))
    if pkg:
        deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
        for name, label in (("next", "Next.js"), ("react", "React"), ("vue", "Vue"),
                            ("svelte", "Svelte"), ("@angular/core", "Angular"),
                            ("express", "Express"), ("fastify", "Fastify"),
                            ("prisma", "Prisma"), ("tailwindcss", "Tailwind CSS"),
                            ("vitest", "Vitest"), ("jest", "Jest")):
            if name in deps:
                frameworks.append(label)
    if os.path.isfile(os.path.join(cwd, "requirements.txt")) or os.path.isfile(os.path.join(cwd, "pyproject.toml")):
        for marker, label in (("fastapi", "FastAPI"), ("django", "Django"), ("flask", "Flask")):
            for mf in ("requirements.txt", "pyproject.toml"):
                p = os.path.join(cwd, mf)
                if os.path.isfile(p):
                    try:
                        if marker in open(p, encoding="utf-8").read().lower():
                            frameworks.append(label)
                            break
                    except Exception:
                        pass
    if os.path.isfile(os.path.join(cwd, "go.mod")):
        frameworks.append("Go modules")

    key_files = [f for f in _KEY_FILES if os.path.isfile(os.path.join(cwd, f))]
    return {
        "project": os.path.basename(os.path.normpath(cwd)),
        "languages": [{"name": k, "files": v} for k, v in languages],
        "frameworks": sorted(set(frameworks)),
        "key_files": key_files,
        "file_count": n,
    }


def _git(cwd: str, *args: str) -> str:
    return _git_rc(cwd, *args)[0]


def _git_rc(cwd: str, *args: str) -> Tuple[str, int]:
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=15)
        return r.stdout.strip(), r.returncode
    except Exception:
        return "", -1


def _git_path(ln: str) -> str:
    # porcelain v1 renames look like "R  old -> new"; keep the new path
    p = ln[3:]
    return p.split(" -> ")[-1] if " -> " in p else p


def git(cwd: Optional[str] = None) -> Dict[str, Any]:
    cwd = cwd or os.getcwd()
    inside = _git(cwd, "rev-parse", "--is-inside-work-tree")
    if inside != "true":
        return {"error": "not a git repository"}
    branch = _git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    porcelain = _git(cwd, "status", "--porcelain")
    staged = [_git_path(ln) for ln in porcelain.splitlines() if ln[:1] in ("A", "M", "D", "R")]
    # worktree changes only; a rename (X='R') is a staged-only change → don't double-list
    modified = [_git_path(ln) for ln in porcelain.splitlines()
                if ln[1:2] in ("M", "D") and ln[:1] != "R"]
    commits = _git(cwd, "log", "-5", "--oneline").splitlines()
    # distinguish "no upstream configured" from "genuinely in sync"
    up_ref, up_rc = _git_rc(cwd, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if up_rc != 0 or not up_ref:
        upstream, ahead = None, None
    else:
        upstream = up_ref
        out, rc = _git_rc(cwd, "rev-list", "--count", "@{u}..HEAD")
        ahead = out if rc == 0 and out else "0"
    diffstat = _git(cwd, "diff", "--stat").splitlines()[-1:] if porcelain else []
    return {
        "branch": branch,
        "upstream": upstream,
        "ahead": ahead,   # None = no tracking branch; "0" = in sync
        "staged": staged[:50],
        "modified": modified[:50],
        "recent_commits": commits,
        "diff_summary": diffstat[0] if diffstat else "",
    }


def mcp_aggregate(cwd: Optional[str] = None) -> Dict[str, Any]:
    cwd = cwd or os.getcwd()
    servers: Dict[str, Any] = {}
    for path in (os.path.join(cwd, ".mcp.json"),
                 os.path.expanduser("~/.claude.json"),
                 os.path.join(cwd, ".claude", "settings.json")):
        cfg = _read_json(path)
        if not cfg:
            continue
        block = cfg.get("mcpServers") or cfg.get("servers") or {}
        if isinstance(block, dict):
            for name, spec in block.items():
                servers.setdefault(name, spec)
    # rough heuristic: each active server adds ~800 tokens of tool defs per cycle
    per_server = 800
    listing = [{"name": n, "est_tokens": per_server} for n in sorted(servers)]
    total = per_server * len(listing)
    recs = []
    if len(listing) > 5:
        recs.append(f"{len(listing)} MCP servers active — consider disabling unused ones.")
    return {"active": len(listing), "est_context_cost": total,
            "servers": listing, "recommendations": recs}


def budget_bar(used: int, limit: int = 200000, saved: int = 0, width: int = 20) -> str:
    used = max(0, int(used))
    limit = max(1, int(limit))
    pct = min(100, round(100 * used / limit))
    filled = round(width * used / limit)
    bar = "▓" * min(width, filled) + "·" * max(0, width - filled)
    lines = [
        "# Context Budget",
        "",
        f"[{bar}] {pct}% used",
        "",
        f"Tokens consumed: {used:,}",
        f"Tokens saved:    {int(saved):,}",
        f"Context limit:   {limit:,}",
    ]
    if pct >= 70:
        lines += ["", f"⚠ WARNING: context {pct}% full — use summarizing tools to save space."]
    return "\n".join(lines)
