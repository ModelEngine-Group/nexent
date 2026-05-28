# benchmark — Nexent Agent Context Compression Evaluation

Evaluate the practical effectiveness of **Agent Context Compression**: whether the compressed Agent can still complete tasks, remember key states, and tokens actually decrease. Does not measure text similarity between summary and original, only measures **functional retention**.

> For complete design documentation of the evaluation mechanism, see [`note_benchmark.md`](note_benchmark.md).
> This file only covers **how to run**.

---

## Prerequisites

- Use backend's venv (nexent SDK and dependencies already installed): `nexent/backend/.venv/bin/python`
- LLM credentials in repo root's `nexent/.env` (`agent_runner` will `load_dotenv`):
  `LLM_API_KEY` / `LLM_MODEL_NAME` / `LLM_API_URL`
- Commands below assume you're in this directory (`sdk/benchmark/`), using relative paths.

---

## Two Entry Points

### 1. `test_benchmark.py` — End-to-end Case Evaluation (Main Entry)

```bash
nexent/backend/.venv/bin/python test_benchmark.py
```

Automatically discovers all cases under `cases/*/case.json`, each case runs two comparison experiments:

| Group | Compression | Purpose |
|---|---|---|
| Baseline | `enabled=False` | Capability ceiling |
| Compressed | `enabled=True` + case custom params | Actual performance after compression |

Evaluates three dimensions: **Continuation** (multi-turn task continuation), **Probe** (early history memory retention), **Token Reduction** (token reduction rate). No CLI arguments; per-case reports written to `reports/<case_id>.json`, cross-case summary to `reports/summary.json`.

### 2. `summary_inspector.py` — Compressor Static Quality Check

Runs without Agent, directly checks whether summary text retains key information—used to distinguish "compressor missed it" vs "Agent didn't use it" failure root causes.

```bash
# Run all inspections under inspections/
nexent/backend/.venv/bin/python summary_inspector.py
# Run only one
nexent/backend/.venv/bin/python summary_inspector.py -n example_infra
# Custom compression params + also save raw summary text
nexent/backend/.venv/bin/python summary_inspector.py --config cfg.json --save-summary
```

---

## Directory Structure

```
manual_cases/
├── test_benchmark.py     # End-to-end case evaluation entry
├── summary_inspector.py  # Static summary quality check entry
├── agent_runner.py       # Agent run wrapper (build run info, run agent with tracking)
├── eval_utils.py         # LLM scoring tools (eval_text / average_score)
├── cases/<case_id>/      # End-to-end evaluation cases
│   ├── case.json         # Config: id / history_file / queries / probes /
│   │                     #         summary_checks / task_checks / compressed_config
│   └── history.json      # Initial multi-turn conversation history (user/assistant pairs)
├── inspections/<name>/   # Static quality check cases
│   ├── history.json      # Conversation history to compress
│   └── checks.json       # Summary key information check items
├── reports/              # test_benchmark.py output (<case_id>.json + summary.json)
└── note_benchmark.md     # Complete evaluation mechanism design documentation
```

---

## Adding a New Case

1. Create directory `cases/<id>/`, place `history.json` (initial history) and `case.json`.
2. `case.json` fields: `id`, `history_file`, `queries` (multi-turn continuation questions), `probes` (memory probes only targeting compressed region), `summary_checks`, `task_checks`, `compressed_config` (compression param overrides).
3. Run `test_benchmark.py`, results appear in `reports/<id>.json`.

> To see the full trace of context construction and compression during a benchmark run, use [`../../ctx_debugger/`](../../ctx_debugger/) (`example_with_benchmark.py` attaches debugger to batch-run benchmark).