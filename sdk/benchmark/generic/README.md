# Nexent Generic Benchmark Runner

[Chinese version](./README.zh-CN.md)

This directory contains the standalone, Langfuse-based benchmark harness for
the Nexent SDK. It executes real SDK agents without starting the Nexent backend
or frontend. Langfuse stores datasets, traces, scores, and dataset runs; local
artifacts preserve manifests, evidence, and comparison reports.

## Entry points

| Script | Purpose |
|---|---|
| `run_benchmark.py` | Execute or rescore one immutable benchmark run |
| `run_context_manager_comparison.py` | Compare current passthrough (P) and adaptive-compaction (C) modes |
| `run_legacy_p_comparison.py` | Compare a pinned Legacy worktree (L) with current passthrough mode (P) |
| `run_failed_item_repeats.py` | Repeat only failed items from a completed run |
| `run_integrity.py` | Validate dataset linkage, evaluator scores, trace status, and manifests |

Operational commands live under `tools/`, while the optional Langfuse webhook
lives under `integrations/langfuse/`. Supporting packages provide task
adaptation, evaluators, manifests, replay, and evidence analysis.

## Repository and data layout

Source code and standard sample configurations are committed under this
directory. Datasets, attachments, logs, generated configurations, and run
artifacts stay outside the repository.

The default external root is:

```text
<repo-parent>/nexent-data/benchmark/
├── datasets/
└── artifacts/
```

Set `NEXENT_BENCHMARK_DATA_ROOT` to use another location.

Committed standard configurations include:

`configs/gaia_example.yaml`

Experiment-specific configuration variants and generated result files remain
local.

## End-to-end pipeline

```text
Prepare Python and credentials
  -> start Langfuse
  -> import or select a dataset
  -> run one-item smoke
  -> run a single, P/C, or L/P experiment
  -> inspect Langfuse and local reports
  -> validate run integrity
```

Run all commands below from the repository root unless a step explicitly
changes directory.

### 1. Prepare the environment

Requirements:

- Python 3.11 in `backend/.venv` with the SDK installed for development;
- Docker with the Compose plugin for the local Langfuse stack;
- `LLM_API_KEY`, `LLM_MODEL_NAME`, and `LLM_API_URL` for real model calls;
- tool credentials referenced by the selected agent YAML, such as
  `EXA_API_KEY`, when those tools are enabled.

Optionally select an external data and artifact root:

```bash
export NEXENT_BENCHMARK_DATA_ROOT=/path/to/benchmark-data
```

Do not commit service, model, or tool secrets.

### 2. Start and configure Langfuse

For the first startup, copy the environment template and replace every
`replace-me` value:

```bash
cd sdk/benchmark/infra/langfuse
cp .env.example .env
# Edit .env before continuing.
docker compose -p nexent-benchmark-langfuse up -d
docker compose -p nexent-benchmark-langfuse ps
curl -s http://localhost:3100/api/public/health
cd ../../../..
```

Export the project credentials for the benchmark processes:

```bash
set -a
source sdk/benchmark/infra/langfuse/.env
set +a
export LANGFUSE_HOST=http://localhost:3100
export LANGFUSE_PUBLIC_KEY="$LANGFUSE_INIT_PROJECT_PUBLIC_KEY"
export LANGFUSE_SECRET_KEY="$LANGFUSE_INIT_PROJECT_SECRET_KEY"
```

Open `http://localhost:3100` and sign in with the initialization account from
the same `.env` file. See [Local Langfuse deployment](../infra/langfuse/README.md)
for lifecycle and security details. The generic runners connect directly to
Langfuse; `ctx_debugger` is not required.

### 3. Import or select a dataset

If the dataset already exists in the selected Langfuse project, keep its name
and continue to the smoke run. For a new JSONL dataset, each line should contain
the configured input and expected-output keys, for example:

```json
{"question": "What is 2 + 2?", "answer": "4"}
```

Upload it without calling the model:

```bash
backend/.venv/bin/python sdk/benchmark/generic/run_benchmark.py \
  --dataset my-benchmark \
  --upload /path/to/dataset.jsonl \
  --evaluators exact_match \
  --dry-run
```

The default JSONL keys are `question` and `answer`; use `--input-key` and
`--output-key` for another schema. Re-uploading to an existing dataset can add
duplicate items, so verify the dataset in Langfuse before repeating an import.

GSM8K can also be downloaded and uploaded with
`datasets/gsm8k_loader.py`. GAIA file-based tasks additionally require their
attachments to be available at the S3/MinIO paths stored in the dataset; use
`tools/gaia/upload_files.py` when preparing those attachments. Dataset-specific
runner options are covered in [Single-run executor](./RUN_BENCHMARK.md).

### 4. Run a real one-item smoke

Use a new run name for every execution:

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

Confirm that the console result, Langfuse evaluator score, dataset-run item,
and trace status agree before starting a larger experiment. The runners reject
local or Langfuse run-name collisions to protect experiment provenance.

### 5. Choose an experiment

#### Single run

Use `run_benchmark.py` to evaluate one configuration or processing policy. It
is also the lower-level executor used by both comparison orchestrators. See
[Running a benchmark](./RUN_BENCHMARK.md) for all options, rescoring, outputs,
and integrity checks.

#### P/C comparison on the current revision

P/C keeps the code revision, dataset items, model, prompts, tools, evaluator,
and experiment time aligned. P uses `passthrough`; C uses
`adaptive_compact`. A one-item paired acceptance run is:

```bash
backend/.venv/bin/python sdk/benchmark/generic/run_context_manager_comparison.py \
  --dataset gaia-level1-web-search \
  --run-prefix gaia-web-pc-smoke-YYYYMMDD \
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

See [P/C context processing comparison](./RUN_CONTEXT_MANAGER_COMPARISON.md)
for controlled arguments, parity requirements, paired outcomes, and report
interpretation.

#### L/P comparison across revisions

L/P compares a pinned Legacy worktree and Python environment with the current
passthrough candidate. This is an end-to-end cross-revision regression test;
it must not be described as a ContextManager-only comparison unless assembly
parity is proven. Both worktrees need usable Python environments and inherit
the same exported Langfuse, model, and tool credentials.

```bash
export REPO_ROOT="$(pwd)"
export LEGACY_ROOT=/path/to/legacy-worktree

backend/.venv/bin/python sdk/benchmark/generic/run_legacy_p_comparison.py \
  --dataset gaia-level1-reasoning \
  --run-prefix gaia-reasoning-lp-smoke-YYYYMMDD \
  --legacy-root "$LEGACY_ROOT" \
  --smoke-only \
  --smoke-items 1 \
  --candidate-soft-input-budget 10000 \
  --candidate-hard-input-budget 900000 \
  --candidate-context-window-tokens 1000000 \
  --candidate-budget-profile synthetic_trigger \
  --runner-args \
    --agent-config "$REPO_ROOT/sdk/benchmark/generic/configs/gaia_solver.yaml" \
    --language en \
    --evaluators gaia_exact_match \
    --max-steps 15 \
    --temperature 0
```

See [Legacy/P cross-revision comparison](./RUN_LEGACY_P_COMPARISON.md) for
worktree preparation, interpreter verification, formal runs, and causal-scope
rules.

### 6. Inspect and validate results

Use the Langfuse dataset page to inspect run items, traces, outputs, and scores.
Local comparison reports are written below:

```text
$NEXENT_BENCHMARK_DATA_ROOT/artifacts/comparisons/          # P/C
$NEXENT_BENCHMARK_DATA_ROOT/artifacts/legacy_p_comparisons/ # L/P
```

For a single run, perform the read-only integrity check described in
[Running a benchmark](./RUN_BENCHMARK.md). Treat `INCOMPLETE` as a failed
acceptance result until missing scores, missing links, empty outputs, or trace
errors have been explained. Preserve run names, manifests, source revisions,
dataset item IDs, evaluator names, and reports with every experiment result.

## Additional documentation

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
