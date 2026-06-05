# LLM Providers & Auto-Detection

## Why an LLM?

An LLM unlocks three core capabilities in Logica Mind:

- **Extraction** — Raw user input (a conversation snippet, a journal entry, a transcribed thought) is decomposed into atomic, standalone facts that can be indexed independently.
- **Categorization** — Each extracted fact is tagged across life/work dimensions, so your memory organizes itself without manual filing.
- **Dialectic User Model** — Facts that conflict or refine earlier memories are identified and reconciled in place, letting your memory evolve without duplication.

Without an LLM, the library still deduplicates and stores everything, but extraction and categorization fall back to substring matching and heuristics.

## How Auto-Detection Works

Logica Mind is **zero-config by default**. On each `remember()` call, the system automatically detects which LLM is available:

1. **Check the `LOGICA_MIND_LLM` environment variable** — if set to `anthropic`, `openai`, or `claude-cli`, that provider is used.
2. **Fall back to API key order** — if not forced, try Anthropic (ANTHROPIC_API_KEY) → OpenAI (OPENAI_API_KEY).
3. **Return None if nothing is configured** — the library runs fully offline with only deduplication.

### Important: Claude CLI Is Opt-In

The local Claude CLI (Claude Code) is **detected but not auto-used**. Even if the `claude` binary is on your PATH, it will not be invoked unless you explicitly set:

```bash
export LOGICA_MIND_LLM=claude-cli
```

This keeps `LogicaMind()` deterministic by default and prevents the library from silently spawning subprocesses. If you want the convenience of local Claude without API keys, opt in deliberately.

## Provider Comparison

| Provider | Model | Enabled How | Needs API Key? | Local? | Cost |
|----------|-------|------------|----------------|--------|------|
| **Anthropic (Claude)** | claude-haiku-4-5 | `ANTHROPIC_API_KEY` env var | Yes | No | Pay-per-token |
| **OpenAI** | gpt-4o-mini | `OPENAI_API_KEY` env var | Yes | No | Pay-per-token |
| **Claude CLI (Claude Code)** | Your signed-in Claude instance | `LOGICA_MIND_LLM=claude-cli` | No | Yes | Free (runs locally) |

### Anthropic (Claude)

Enable by setting your Anthropic API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Then install the library with Anthropic support:

```bash
pip install 'logica-mind[anthropic]'
```

The system will automatically use `claude-haiku-4-5` (Logica Mind's default fast model) for extraction and categorization.

### OpenAI

Enable by setting your OpenAI API key:

```bash
export OPENAI_API_KEY=sk-proj-...
```

Then install the library with OpenAI support:

```bash
pip install 'logica-mind[openai]'
```

If Anthropic is also configured, it takes precedence. To force OpenAI, set:

```bash
export LOGICA_MIND_LLM=openai
```

### Claude CLI (Local)

If you have [Claude Code](https://www.anthropic.com/claude-code) installed and on your PATH, you can use your locally-installed Claude instance:

```bash
export LOGICA_MIND_LLM=claude-cli
```

The library will invoke `claude -p` (non-interactive prompt mode) for each extraction or categorization task. No API key needed; no per-token billing.

To use a custom binary name or location:

```bash
export LOGICA_MIND_CLAUDE_BIN=/path/to/my-claude-wrapper
export LOGICA_MIND_LLM=claude-cli
```

## Running Fully Offline (No LLM)

If no API key is set and `LOGICA_MIND_LLM` is unset, Logica Mind runs without an LLM:

```bash
unset ANTHROPIC_API_KEY
unset OPENAI_API_KEY
unset LOGICA_MIND_LLM
```

```python
from logica_mind import LogicaMind
brain = LogicaMind()
brain.remember("Just had coffee with Alex and discussed the Q4 roadmap.")
```

The library will:
- Store the memory in the configured backend (SQLite by default).
- Deduplicate on insertion using local hashing.
- Not extract or categorize automatically.

This is useful for offline-first applications or testing.

## Live Integration Status

Open the **Settings → Integrations** panel in the Logica Mind dashboard to see:

- Which providers are **detected** (API keys present, binaries on PATH).
- Which are **installed** (required Python packages available).
- The **current active provider** driving extraction and categorization.

The panel refreshes in real time, so changes to environment variables are reflected immediately.

## Examples

### Quick Start with Anthropic

```bash
pip install 'logica-mind[anthropic]'
export ANTHROPIC_API_KEY=sk-ant-...

python
```

```python
from logica_mind import LogicaMind

brain = LogicaMind()

# This automatically uses Anthropic, extracts facts, categorizes them, 
# and stores in SQLite.
brain.remember("""
Had a great conversation with Sarah about the new project charter.
The timeline moved to Q3, and we need a design review by June 15.
""")

# Query your memory
results = brain.recall("when is the design review?")
for r in results:
    print(r.memory.content, (r.memory.metadata or {}).get("category"))
```

### Using Claude CLI Locally

```bash
pip install logica-mind
export LOGICA_MIND_LLM=claude-cli

python
```

```python
from logica_mind import LogicaMind

brain = LogicaMind()

# Extraction happens via your local Claude Code instance—no API key, 
# no internet call.
brain.remember("Rescheduled dentist to Friday 2pm. Doctor recommended flossing daily.")

results = brain.recall("dentist appointment")
```

### Switching from OpenAI to Anthropic

If both keys are set, Anthropic takes precedence. To force OpenAI:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-proj-...
export LOGICA_MIND_LLM=openai
```

## See Also

- [**Categorization**](./categorization.md) — Deep dive into how life/work dimensions are inferred and applied.
- [**Embeddings & Reranking**](./embeddings-and-reranking.md) — Hosted and local vector search, hybrid scoring.
- [**Dashboard**](./dashboard.md) — UI for browsing, editing, and visualizing your memory graph.