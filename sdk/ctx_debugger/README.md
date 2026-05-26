# ctx_debugger — Nexent Context Debugger

Observation tool for the full process of **context construction and compression** in Nexent Agent. From system prompt, multi-turn history, compression decisions, LLM calls, to tool execution, observer events—all recorded as analyzable JSONL trace.

> **Core positioning**: Nexent agent runtime is already "self-talking" (observer events, compression logs, token statistics), ctx_debugger just "eavesdrops" and structurally records, **no Nexent source modification**.

---

## 1. What Problems It Solves

When Agent context compression (`ContextManager`) has issues, developers need to answer:

- Why did compression trigger/not trigger at this step?
- What did the compression LLM take in, produce, and how long?
- What does the context actually look like after compression?
- What information did the summary retain/lose?
- How much did tokens actually decrease (including compression call overhead)?

This information is scattered across `ContextManager` internal state, `step_metrics`, `MessageObserver` events, without unified, traceable view. ctx_debugger aggregates them into one trace.

---

## 2. Directory Structure

```
ctx_debugger/
├── __init__.py              # Package entry, re-export ContextDebugger / attach_debugger
├── __main__.py              # Entry point for python -m ctx_debugger.inspector
├── debugger.py              # Core: ContextDebugger, attach_debugger, layer proxies
├── interactive.py           # Interactive REPL (main debugging mode)
├── inspector.py             # Post-analysis CLI for trace files
├── langfuse_export.py       # Import trace into Langfuse for visual analysis
├── example_with_benchmark.py# Attach debugger to benchmark batch run
└── README.md
```

Dependency direction: **ctx_debugger → only import nexent SDK**, nexent doesn't reverse-depend on this package.

---

## 3. Prerequisites

> Commands below assume you're in this directory (README's location `ctx_debugger/`). Relative path conventions:
> `.` = `ctx_debugger/`, `..` = `sdk/`, `../..` = nexent repo root directory
> (where `sdk/`, `backend/`, `.env` reside).

- Use backend's venv Python (nexent SDK and dependencies installed):
  ```
  ../../backend/.venv/bin/python
  ```
- LLM credentials in repo root `.env`, i.e., `../../.env` (`agent_runner` will `load_dotenv`):
  ```
  LLM_API_KEY=...
  LLM_MODEL_NAME=...
  LLM_API_URL=...
  ```
- Trace output path controlled by environment variable `NEXENT_CONTEXT_DEBUG`, or explicitly pass `trace_path` in `attach_debugger`.

---

## 4. Three Usage Modes

### 4.1 Interactive REPL — Main Mode

You type user messages line by line, each line triggers one real agent execution; history accumulates, `ContextManager` shared across turns, compression triggers naturally when threshold reached.

```bash
# In ctx_debugger/ directory
../../backend/.venv/bin/python interactive.py
```

Each turn auto-displays agent answer + context construction panel (agent steps, main/compression LLM calls, compression triggered or not, token reduction, summary updated or not).

Panel token counts split into two types, labeled separately: `main LLM` / `compression LLM` rows with `(API)` are LLM-reported `token_usage`; `compression` row with `(est.)` is `ContextManager` heuristic estimation (`estimate_tokens_text`, CJK-aware, no real tokenizer). **Compression threshold judgment uses estimated value**, may differ from API measured (Chinese text heuristic usually overestimates).

Slash commands:

| Command | Purpose |
|---|---|
| `/help` | Command list |
| `/context [N]` | Last turn main LLM actually received context (compressed: system + summary + recent turns); `N` selects N-th main call |
| `/history` | Accumulated session raw ledger (each turn verbatim, pre-compression; REPL's own accounting, not what model sees) |
| `/summary` | Current compression summary full text |
| `/compress` | Last turn's compression LLM input prompt (fed in) and output summary (produced), separate from main answer |
| `/tokens` | Per-turn token timeline |
| `/stats` | Entire session compression statistics—key is "LLM-invoking semantic compression" cumulative count, plus cache hits, token cost |
| `/trace` | Last turn raw event table |
| `/step N` | Last turn step N all events JSON |
| `/config` | Current `ContextManagerConfig` |
| `/reset [threshold]` | Clear and restart, optional new threshold |
| `/quit` `/q` | Exit |

Default `token_threshold=3000`, few turns trigger compression.

Input line supports up/down arrow history recall (shell habit), history persisted in `~/.nexent_ctx_debugger_history`, retained across sessions.

### 4.2 Batch Attach to Benchmark

Without modifying benchmark code, monkey-patch `CoreAgent.__init__` so each agent auto-attaches debugger, entire benchmark run produces one trace.

```bash
# In ctx_debugger/ directory
NEXENT_CONTEXT_DEBUG=/tmp/trace.jsonl \
  ../../backend/.venv/bin/python example_with_benchmark.py
```

### 4.3 Post-analysis of Trace Files

```bash
# In parent sdk/ directory
cd ..
python -m ctx_debugger.inspector <subcommand> <trace.jsonl> [options]
```

| Subcommand | Purpose |
|---|---|
| `summary` | Overview: event count, run count, token totals, event histogram |
| `runs` | List all runs |
| `timeline [--run X]` | Chronological event list |
| `compress` | All compression cycles' decisions and token reductions |
| `llm [--tag main|compression]` | LLM call list (duration, tokens) |
| `step --step N [--run X]` | One step's all events JSON |

`--run` supports 8-char short suffix matching.

### 4.4 Import to Langfuse for Visual Analysis

Map trace into self-hosted [Langfuse](https://langfuse.com), get nested traces, per-call drill-down, token/duration views, session grouping—no need to build custom web UI.

```bash
# In parent sdk/ directory
cd ..
# First dry run, see mapping structure (offline)
python -m ctx_debugger.langfuse_export <trace.jsonl> --dry-run
# After configuring credentials, real import
LANGFUSE_HOST=http://localhost:3000 \
LANGFUSE_PUBLIC_KEY=pk-... LANGFUSE_SECRET_KEY=sk-... \
  python -m ctx_debugger.langfuse_export <trace.jsonl>
```

Mapping rules:

| ctx_debugger | Langfuse |
|---|---|
| Each agent turn (`agent_init`) | One trace |
| `llm_call_*` | generation (input/output, tokens, duration) |
| `compress_*` | span, nested compression generations inside |
| `tool_call_*` / `code_execute_*` | tool / span observation |
| Entire trace file | One Langfuse session (turn grouping) |

Depends on `langfuse` SDK (`uv pip install langfuse`). Self-hosted Langfuse can be started with official docker compose. **Known limitation**: Observations created at export time, single duration faithful, but absolute position on Langfuse timeline is export time, not original wall-clock time.

---

## 5. Core API

### `attach_debugger(target, ...)`

Attach debugger to an agent or `ContextManager`.

```python
from ctx_debugger import attach_debugger
from nexent.core.agents.agent_context import ContextManager

cm = ContextManager(config=...)
attach_debugger(cm, trace_path="/tmp/run.jsonl")          # Only attach compression layer
# Or attach entire agent, auto-cover five layers
attach_debugger(agent, trace_path="/tmp/run.jsonl")
```

Parameters:

| Parameter | Description |
|---|---|
| `target` | Nexent agent (CoreAgent/NexentAgent) or `ContextManager` |
| `trace_path` | Output JSONL path; fallback to `NEXENT_CONTEXT_DEBUG` env var when empty |
| `layers` | Subset of `{"compression","model","observer","tools","executor"}`, default all enabled |
| `run_id` | Explicit run identifier, auto-generated when omitted |
| `capture_full_summary` | Compression events include full summary text, default True |
| `capture_full_messages` | Main LLM calls also store full message text, default False; compression LLM calls always store full |
| `append` | Append to existing trace instead of overwriting |
| `existing` | Reuse an existing `ContextDebugger` (interactive session across multiple turns shares same trace/run_id) |

When no trace path resolved, returns `None` without any wrapping (zero overhead).

### Five Observation Layers

| Layer | Attach Point | Capture |
|---|---|
| `compression` | `ContextManager.compress_if_needed` wrapper | Compression decision, compression call records, summary before/after state |
| `model` | `agent.model` replaced with `_ModelProxy` | Each LLM call's input/output/tokens/duration, tagged with contextvar `main` vs `compression` |
| `observer` | `agent.observer.add_message` mirror | All Nexent's own observer events |
| `tools` | Each `agent.tools[name].forward` instance-level wrapper | Single-tool granularity args / return / duration |
| `executor` | `agent.python_executor` replaced with `_PyExecutorProxy` | Executed Python code full text + output + duration |

---

## 6. Trace Event Schema

Each line is JSON, unified outer fields:

```json
{
  "seq": 42,                 // Global monotonically increasing sequence number
  "ts": 1778813372.87,       // Unix timestamp
  "run_id": "run_a70c9017",  // One attach = one run
  "agent_step": 1,           // Current agent step number (from observer's step_count)
  "event": "compress_end",
  "data": { ... }            // Event-specific fields
}
```

Event types:

| Event | When emitted | Key data fields |
|---|---|---|
| `run_begin` | Debugger created | pid |
| `agent_init` | Attached to agent | system_prompt full text, tools list, cm config |
| `compress_begin` | `compress_if_needed` entry | `predicted_decision` (decision branch + compress_prev/curr), `estimated_tokens` |
| `compression_call` | Each compression call within step | call_type, cache_hit, in/out tokens |
| `compress_end` | `compress_if_needed` exit | `token_counts` (before/after), `summary_after`, `summary_changed` |
| `llm_call_begin` / `llm_call_end` | Each LLM call | `tag` (main/compression), input messages (compression calls each with full `text`), output (compression calls with `output_full`), tokens, duration |
| `code_execute_begin` / `code_execute_end` | Python executor execution | code full text, output, logs, duration |
| `tool_call_begin` / `tool_call_end` | Each tool call | tool name, args, return, duration |
| `observer_event` | Each Nexent observer message | process_type, content preview |
| `debug_error` | Debugger internal exception | phase, error (won't crash agent) |

Text fields all bounded truncation (head N chars + `...[N chars elided]...` + tail M chars),
avoid trace file infinite growth.

---

## 7. Design Principles

1. **Zero SDK source modification**: Via monkey-patch wrapping + proxy objects, no changes to `nexent/`.
2. **Read-only public interface + few stable internal interfaces**: Underscore interfaces like `_step_local_log`, `_effective_*_tokens` are also used by benchmark, treated as de-facto stable.
3. **Five optional layers**: `layers` parameter narrows as needed, trace size controllable.
4. **Failure isolation**: Each attach point try/except兜底, single layer failure only emits `debug_error` event, won't crash agent.
5. **Reuse Nexent's own events**: `observer` layer directly mirrors `MessageObserver`, no reinventing wheel.
6. **No frontend pollution**: Observer tap modifies instance's `add_message`, original method still called, frontend stream unaffected.

### Coupling Points with Nexent

Debugger "simulates/eavesdrops" on Nexent behavior, thus soft coupling exists—if Nexent changes following interfaces, debugger must adapt (other changes auto-compatible):

- `agent.model` / `agent.observer` / `agent.python_executor` / `agent.tools` renamed
- `tool.forward` method name changed
- `compress_if_needed` signature changed
- `observer.add_message` parameter order major change

---

## 8. Known Limitations

- **Main LLM calls default only store digest**: Compression LLM calls' input messages and output already stored verbatim in full (each message with `text`, output with `output_full`); Main LLM calls default still truncated digest, need full text pass `capture_full_messages=True` to `attach_debugger`. Interactive REPL already defaults this option on, so `/context` can see full text.
- **Trace file size unlimited**: Long session could be tens of MB; `inspector` currently one-time loads into memory.
- **Multi-agent nesting**: Each attach one run_id; interactive session uses `existing=` to reuse same debugger to unify run_id.
- **Interactive REPL requires real TTY**: Pipe feeding input works, but experience designed for interactive.