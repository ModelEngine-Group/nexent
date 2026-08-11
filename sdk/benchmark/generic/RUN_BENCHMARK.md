# Running a Benchmark

[Chinese version](./RUN_BENCHMARK.zh-CN.md)

`run_benchmark.py` is the single-run executor used directly and by both
comparison orchestrators.

## Standard execution

```bash
backend/.venv/bin/python sdk/benchmark/generic/run_benchmark.py \
  --dataset gaia-level1-web-search \
  --run-name gaia-web-smoke-YYYYMMDD \
  --item-limit 1 \
  --agent-config sdk/benchmark/generic/configs/gaia_solver.yaml \
  --language en \
  --evaluators gaia_exact_match \
  --max-steps 15 \
  --temperature 0 \
  --model-factory openai \
  --context-processing-mode passthrough
```

Important options:

| Option | Meaning |
|---|---|
| `--dataset` | Langfuse dataset name |
| `--run-name` | Immutable dataset-run name |
| `--item-id` / `--item-limit` | Restrict the selected items |
| `--agent-config` | YAML agent snapshot |
| `--evaluators` | One or more registered evaluators |
| `--context-processing-mode` | `passthrough` or `adaptive_compact` |
| `--soft-input-budget` | Adaptive-compaction trigger budget |
| `--hard-input-budget` | Non-negotiable input ceiling |
| `--context-window-tokens` | Provider/model context window |
| `--budget-profile` | Budget provenance label |
| `--experiment-time` | Frozen prompt time shared by comparison arms |
| `--dry-run` | Validate configuration without running the dataset |

Legacy `--enable-context-manager` and `--disable-context-manager` flags are
compatibility aliases. New commands should use `--context-processing-mode`.

CLI arguments override YAML values. Missing values fall back to the runner
defaults.

## Parity snapshot trust

`tools/export_parity_snapshot.py` reconstructs a snapshot from Agent YAML and is
labelled `benchmark_reconstructed`. Passing its strict gate produces
`simulation_fidelity=benchmark_reconstructed_snapshot`, not a production claim.
Schema v2 checks prompt, ContextItems, resources, tools, model, capacity, policy,
and runtime flags captured by the benchmark-assembled `AgentRunInfo`.

## Rescoring

Rescoring reuses existing traces and does not call the model.

```bash
backend/.venv/bin/python sdk/benchmark/generic/run_benchmark.py \
  --rescore \
  --dataset gaia-level1-web-search \
  --existing-run EXISTING_RUN \
  --run-name EXISTING_RUN-rescore-v2 \
  --evaluators gaia_exact_match
```

## Outputs

Each run writes:

- a Langfuse dataset run and trace links;
- evaluator scores;
- a manifest under
  `$NEXENT_BENCHMARK_DATA_ROOT/artifacts/manifests/`;
- web evidence under
  `$NEXENT_BENCHMARK_DATA_ROOT/artifacts/web_evidence/` when applicable.

Always preserve the run name, manifest, source revision, dataset item set,
evaluator names, model configuration, prompt/tool hashes, and budget settings
when interpreting results.

## Integrity check

```bash
backend/.venv/bin/python sdk/benchmark/generic/run_integrity.py \
  --dataset gaia-level1-web-search \
  --run-name YOUR_RUN_NAME \
  --manifest "$NEXENT_BENCHMARK_DATA_ROOT/artifacts/manifests/YOUR_RUN_NAME.manifest.json" \
  --evaluator gaia_exact_match
```
