# Automatic Capture Hooks

Hooks let Logica Mind remember your sessions on its own — capturing what you say and what the assistant does, injecting relevant memory back, and preserving context right before the window is compacted.

## Why hooks?

Most memory libraries only remember what the agent explicitly decides to save by calling a tool. Hooks flip that around: they run on the host's lifecycle events, so capture and recall happen automatically — no tool call required, nothing for the model to forget.

Each hook is a short-lived process. It reads a JSON event from the host on stdin and prints the host's hook output (an `additionalContext` block) on stdout. The design has three hard rules:

- **Never raise.** A memory hiccup must never break the agent's session.
- **Never write anything but the final JSON to stdout.** The host reads stdout as the hook's output, so all diagnostics go to stderr.
- **Fail fast.** A misconfigured embedder degrades to the offline hashing embedder instantly instead of stalling the prompt path on retries.

Everything runs offline and zero-key by default: a [SQLite store](./stores.md) plus the [hashing embedder](./embeddings-and-reranking.md). Set `VOYAGE_API_KEY` or `OPENAI_API_KEY` to opt into a real embedding provider — the hooks pick it up automatically and fall back the moment it errors.

## The four lifecycle events

Logica Mind installs one hook per event. Each maps to a handler in `logica_mind/hooks.py`.

| Event | What it does | Injects context? |
| --- | --- | --- |
| `SessionStart` | Injects a brief of what's known about you plus highlights from past sessions. | Yes |
| `UserPromptSubmit` | Recalls memory relevant to your prompt, then saves the prompt. | Yes |
| `Stop` | Reconciles the whole turn (yours + the assistant's) against the store, recovering anything an earlier hook missed. | No |
| `PreCompact` | Consolidates memory before the context window is compacted. | No |

### SessionStart

At the start of a session there is no query yet, so the hook calls `session_brief()` and injects the result. The brief is ranked by importance and recency and contains, budget permitting:

- **What I know about you** — the evolving [user model](./user-model-and-peers.md).
- **From past sessions** — the most important distilled [semantic](./concepts.md) facts.
- **Recent activity** — the latest raw episodic turns, even if they were never distilled (the offline / no-LLM case).

### UserPromptSubmit

This hook recalls *before* it captures. If it saved your prompt first, that same text would still be in the store when it searched and would be injected straight back as "relevant memory." So the order is:

1. Build a context block with `mind.context(prompt, token_budget=800, include_user=False)`.
2. Log the prompt as an `episodic` `user` turn — unless it is byte-identical to the last user turn in this session (the "continue" / "fix it" repeat pattern is skipped via `_is_duplicate_of_last`).
3. Return the recalled context for the host to inject.

### Stop — the self-healing reconcile

When a turn ends, the hook reads the host's transcript (`transcript_path`) and **reconciles it against the store**: it walks the recent turns (both yours and the assistant's) and logs every one that is not already captured, deduplicated by normalized content so nothing is stored twice. It injects nothing.

This is what makes capture robust. `UserPromptSubmit` captures your prompt live, but it is fire-and-forget — if the store is briefly unreachable, or you enabled the hooks halfway through a session, that turn would otherwise be lost forever. Because `Stop` re-reads the transcript and captures whatever is missing, a turn that slipped through is picked up at the end of the turn instead of disappearing. If a capture fails, the rest is left for the next `Stop` to retry.

Both `UserPromptSubmit` and `Stop` tag what they capture with a `source` of `claude-code` by default, so the dashboard can attribute each turn to the client that produced it. Override the label with `LOGICA_MIND_SOURCE` when running under a different host.

#### Failures are logged, not swallowed

Capture is fail-soft by design (a memory hiccup must never break your session), which used to mean a broken capture path lost memory *silently*. Now every capture failure is appended to `~/.logica-mind/capture.log` with a timestamp, so a misconfigured store or embedder is visible instead of mysterious. The session still proceeds uninterrupted.

### PreCompact — surviving compaction

This is the event that fixes "the host compacted the conversation and we lost everything." Just before the host truncates the context window, the `PreCompact` hook runs a consolidation cycle so the important parts of the conversation are distilled into durable memory before they vanish:

```python
mind.dream(prune=True, synthesize_user=False)
```

That [dream cycle](./dreaming.md) distills raw episodic turns into semantic facts, reinforces what matters, and prunes stale episodic entries. Because the surviving facts now live in the store, the next `SessionStart` (and every `UserPromptSubmit`) can bring the relevant slice back automatically.

Consolidation must never block the host's compaction, so the hook runs the work on a daemon thread and waits only a small wall-clock budget — 5 seconds by default. If it overruns, the thread keeps finishing in the background while the host proceeds. Tune the budget with `LOGICA_MIND_PRECOMPACT_BUDGET` (seconds):

```bash
export LOGICA_MIND_PRECOMPACT_BUDGET=10
```

## Installing the hooks

The `install-hooks` command merges the four hooks into a host `settings.json`. It targets `~/.claude/settings.json` by default:

```bash
logica-mind install-hooks
```

Point it at any other settings file with `--settings`:

```bash
logica-mind install-hooks --settings ~/.config/myhost/settings.json
```

On success it prints the resolved path and which events were added:

```
hooks installed in /Users/maya/.claude/settings.json
added: SessionStart, UserPromptSubmit, Stop, PreCompact
```

The installer is safe to run repeatedly:

- **Idempotent.** It checks for the exact command before adding it, so re-running prints `added: (already present)` and changes nothing.
- **Non-destructive.** It merges into the existing `hooks` object rather than replacing it.
- **Atomic.** It writes to a temporary file and then renames it into place.
- **Defensive.** If the target file exists but is not valid JSON, or is JSON but not an object, the installer refuses to overwrite it and exits with a clear message.

### What gets written

Each event is wired to invoke the `logica-mind hook <event>` subcommand. The installer prefers the `logica-mind` console script if it is on `PATH`, otherwise it pins the exact interpreter that has the package installed (`<python> -m logica_mind`). A generated `settings.json` looks like this:

```json
{
  "hooks": {
    "SessionStart": [
      { "hooks": [{ "type": "command", "command": "logica-mind hook sessionstart" }] }
    ],
    "UserPromptSubmit": [
      { "hooks": [{ "type": "command", "command": "logica-mind hook userpromptsubmit" }] }
    ],
    "Stop": [
      { "hooks": [{ "type": "command", "command": "logica-mind hook stop" }] }
    ],
    "PreCompact": [
      { "hooks": [{ "type": "command", "command": "logica-mind hook precompact" }] }
    ]
  }
}
```

### Running a hook by hand

Each hook reads the host's event JSON on stdin, so you can exercise one directly to see exactly what it would inject:

```bash
echo '{"prompt": "what timezone does Maya work in?", "session_id": "s1", "cwd": "."}' \
  | logica-mind hook userpromptsubmit
```

If there is anything relevant in memory, the command prints the host's hook-output JSON; otherwise it prints nothing.

## Importing past sessions (backfill)

The `Stop` reconcile heals an *active* session, but a session that finished before you installed the hooks never ran them at all, so its memory was never captured. `backfill` imports those past transcripts:

```bash
# one transcript
logica-mind backfill ~/.claude/projects/<project>/<session>.jsonl

# or a whole folder, scanned recursively
logica-mind backfill ~/.claude/projects
```

It reads each transcript, lands every user and assistant turn in the namespace the live hook *would* have used (it reads the working directory recorded in the transcript), and skips tool-result turns, slash commands and host-injected blocks. It is **idempotent and dedup-aware**: re-running only adds turns that are not already stored, so it is safe to point at your whole history and run it again later. Pass `--namespace` to force a destination, or `--db` to target a specific store.

## The per-project shared store

Hooks keep memory separate per project, and the standalone CLI and MCP server read that *same* captured memory.

**One database per embedder fingerprint.** The store lives under `~/.logica-mind`, with one file per embedder so vectors of different dimensions never share a database and corrupt recall:

- `memory-hashing-256.db` — the default offline hashing embedder.
- `memory-voyage-1024.db` — when `VOYAGE_API_KEY` is set.
- `memory-openai-1024.db` — when `OPENAI_API_KEY` is set.

If an embedding provider errors once, a short-lived sentinel marks it down for 5 minutes so subsequent hooks skip it and use hashing instantly instead of retrying on the prompt path.

**One namespace per project.** Within a database, memory is partitioned by [namespace](./concepts.md). The hook derives the namespace from the host's working directory: it walks up from `cwd` to the nearest project root — the first ancestor containing a `.git`, `pyproject.toml`, or `package.json` — so subfolders of the same project share memory. The namespace combines the project's base name with a short hash of its absolute path, so two different projects that happen to share a directory name (for example two folders called `app`, or a git worktree) never collide.

Override the namespace with `LOGICA_MIND_NAMESPACE` — handy in a monorepo where you want several packages to share one memory, or to pin an explicit name:

```bash
export LOGICA_MIND_NAMESPACE=acme-platform
```

Because `active_store()` resolves the same `(db, embedder, namespace)` that the hooks use, the CLI sees what was auto-captured without any extra configuration:

```bash
# inspect what the hooks captured for the current project
logica-mind stats
logica-mind recall "timezone"

# or open the dashboard on the same store
logica-mind ui
```

Pass `--db` or `--namespace` to any command to point at a different store or partition explicitly.

## See also

- [Concepts](./concepts.md) — memory layers and namespaces.
- [Dreaming & consolidation](./dreaming.md) — what the `PreCompact` hook runs.
- [Stores](./stores.md) — the SQLite store the hooks write to.
- [Embeddings & reranking](./embeddings-and-reranking.md) — the offline hashing embedder and optional providers.
- [User model & peers](./user-model-and-peers.md) — what `SessionStart` injects about you.
- [Quickstart](./quickstart.md) — the fastest path to a working setup.
- [Installation](./installation.md) — install the package and CLI.
