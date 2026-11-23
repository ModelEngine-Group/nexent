# P/C Context Processing Comparison

[Chinese version](./RUN_CONTEXT_MANAGER_COMPARISON.zh-CN.md)

This runner performs a same-revision comparison over the same ContextItems
assembly:

| Arm | Processing mode |
|---|---|
| P | `passthrough` |
| C | `adaptive_compact` |

The comparison isolates processing policy only when manifest parity passes.

## One-item smoke

```bash
backend/.venv/bin/python sdk/benchmark/generic/run_context_manager_comparison.py \
  --dataset gaia-level1-web-search \
  --run-prefix gaia-pc-smoke-YYYYMMDD \
  --skip-smoke \
  --formal-items 1 \
  --repeat 1 \
  --soft-input-budget 10000 \
  --hard-input-budget 900000 \
  --budget-profile synthetic_trigger \
  --runner-args \
    --agent-config sdk/benchmark/generic/configs/gaia_solver.yaml \
    --language en \
    --evaluators gaia_exact_match \
    --max-steps 15 \
    --temperature 0 \
    --model-factory openai \
    --context-window-tokens 1000000
```

The runner owns dataset, run names, processing modes, item limits, experiment
time, and budgets. Do not pass those options through `--runner-args`.

## Report interpretation

The paired matrix uses:

- `PP`: both P and C pass;
- `PF`: P passes and C fails;
- `FP`: P fails and C passes;
- `FF`: both fail.

The report also separates provider prefix-cache metrics from ContextManager
summary-cache metrics and records budget/compaction evidence.

Report files are written to:

```text
$NEXENT_BENCHMARK_DATA_ROOT/artifacts/comparisons/<run-prefix>.comparison.json
$NEXENT_BENCHMARK_DATA_ROOT/artifacts/comparisons/<run-prefix>.comparison.md
```

Report generation waits for both complete dataset-run linkage and visible
evaluator scores. A missing score times out explicitly instead of being counted
as a failed answer.
