# Nexent Generic Benchmark Runner

[Chinese version](./README.zh-CN.md)

This directory contains the Langfuse-based benchmark harness for the Nexent SDK.
It executes real SDK agents, but it is not a full backend or frontend end-to-end
test.

## Entry points

| Script | Purpose |
|---|---|
| `run_benchmark.py` | Execute or rescore one immutable benchmark run |
| `run_legacy_p_comparison.py` | Compare a pinned Legacy worktree with current passthrough mode |
| `run_context_manager_comparison.py` | Compare current passthrough and adaptive-compaction modes |
| `run_failed_item_repeats.py` | Repeat only failed items from a completed run |
| `run_integrity.py` | Validate dataset linkage, evaluator scores, and manifests |

Operational commands live under `tools/`, while the optional Langfuse webhook
lives under `integrations/langfuse/`. Supporting packages provide task
adaptation, evaluators, manifests, parity snapshots, replay, and evidence
analysis.

## Repository and data layout

Source code and standard sample configurations are committed under this
directory. Datasets, attachments, logs, generated agent configurations, and run
artifacts stay outside the repository.

The default external root is:

```text
<repo-parent>/nexent-data/benchmark/
├── datasets/
└── artifacts/
```

Set `NEXENT_BENCHMARK_DATA_ROOT` to override it.

Committed standard configurations are:

- `configs/gaia_solver.yaml`
- `configs/gsm8k_solver_assistant.yaml`
- `configs/agent_7_test.yaml`

Experiment-specific variants and `configs/gaia_results/` remain local.

## Quick start

Run commands from the repository root with the backend Python environment.

```bash
backend/.venv/bin/python sdk/benchmark/generic/run_benchmark.py \
  --dataset gaia-level1-web-search \
  --run-name gaia-smoke-YYYYMMDD \
  --item-limit 1 \
  --agent-config sdk/benchmark/generic/configs/gaia_solver.yaml \
  --language en \
  --evaluators gaia_exact_match \
  --max-steps 15 \
  --temperature 0 \
  --model-factory openai
```

Use a new run name for every execution. The runners refuse local or Langfuse
collisions to protect experiment provenance.

## Documentation

- [Single-run executor](./RUN_BENCHMARK.md)
- [P/C comparison](./RUN_CONTEXT_MANAGER_COMPARISON.md)
- [Legacy/P comparison](./RUN_LEGACY_P_COMPARISON.md)
- [Agent configuration export](./tools/EXPORT_AGENT_CONFIG.md)
- [Web evidence and failed-item repeats](./integrations/langfuse/WEB_BENCHMARK_OPTIMIZATIONS.md)
- [Webhook server](./integrations/langfuse/README.md)
- [Webhook deployment](./integrations/langfuse/DEPLOY.md)

Public default documentation is English. Full Chinese versions use the
`.zh-CN.md` suffix. Historical experiment reports retain their original
language for provenance.
