# Web Benchmark Evidence and Repeats

[Chinese version](./WEB_BENCHMARK_OPTIMIZATIONS.zh-CN.md)

## Web evidence

`run_benchmark.py` records search, extraction, terminal-fetch, and final-answer
boundary evidence under:

```text
$NEXENT_BENCHMARK_DATA_ROOT/artifacts/web_evidence/<run-name>.web-evidence.json
```

Use this artifact to distinguish retrieval failure, missing page fetches,
evidence loss, validation failure, and answer-format drift.

## Exa record and replay

Record a live run:

```bash
backend/.venv/bin/python sdk/benchmark/generic/run_benchmark.py \
  --dataset DATASET \
  --run-name RUN-record \
  --agent-config sdk/benchmark/generic/configs/gaia_solver.yaml \
  --exa-cache-mode record \
  --evaluators gaia_exact_match
```

Replay preserves recorded Exa responses for debugging; it does not make model
generation deterministic.

## Failed-item repeats

```bash
backend/.venv/bin/python sdk/benchmark/generic/run_failed_item_repeats.py \
  --dataset DATASET \
  --baseline-run BASELINE_RUN \
  --run-prefix BASELINE_RUN-failed-repeat \
  --repeat 3 \
  --evaluator gaia_exact_match \
  --runner-args \
    --agent-config sdk/benchmark/generic/configs/gaia_solver.yaml \
    --language en \
    --max-steps 15 \
    --temperature 0
```

Reports are written to
`$NEXENT_BENCHMARK_DATA_ROOT/artifacts/targeted_repeats/`.

State whether counts refer to unique dataset items or repeated traces. Never
combine targeted-repeat accuracy with full-dataset accuracy without preserving
that denominator.
