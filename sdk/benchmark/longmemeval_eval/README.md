# longmemeval_eval — LongMemEval (S*) Long Memory Evaluation

Based on **LongMemEval (S\*)** dataset (from MemoryAgentBench, arXiv 2507.05257v3's "5 long conversations sharing 60 questions" reconstruction of original LongMemEval arXiv 2410.10813), evaluate **context compression**'s impact on **multi-session conversation long memory**.

> Evaluation methods and dimensions follow the rest of `sdk/benchmark`: **baseline (no compression) vs compressed (compression)** comparison. This file covers **dataset format**, **how to run** and **what each parameter means**.

---

## Dataset

| Dimension | Value |
|---|---|
| Long conversations | 5 (shared) |
| Per-conversation tokens | ~355K |
| Per-conversation atomic sessions | ~107–116 (user/assistant multi-turn pairs) |
| Per-conversation questions | 60 |
| Total questions | **300** |
| Question types (6 categories) | `multi-session` (75) · `temporal-reasoning` (75) · `single-session-user` (45) · `knowledge-update` (45) · `single-session-assistant` (30) · `single-session-preference` (30) |
| Answers | Free text (LLM-as-judge scoring) |

Data from HuggingFace `ai-hyz/MemoryAgentBench`'s `Accurate_Retrieval` split,
rows with `metadata.source == "longmemeval_s*"`. **Same parquet as `eventqa_eval`**.

Each row contains:
- `context` — Entire conversation flattened to plain text (for baseline truncation feed)
- `haystack_sessions` — Nested structure `list[60] of list[~2] of list[turn]`,
  `turn = {role, content, has_answer}`. `dataset.py` flattens to single-layer
  `list[session]`, concatenated in chronological order.
- `questions` / `answers` / `question_types` / `question_dates` / `question_ids`

---

## Prerequisites

- Use backend's venv: `nexent/backend/.venv/bin/python` (already contains `huggingface_hub`,
  `pyarrow`, `openai`)
- Tested LLM credentials: Repo root `nexent/.env`'s `LLM_API_KEY` / `LLM_MODEL_NAME` / `LLM_API_URL`
- **Judge model (optional)**: `JUDGE_API_KEY` / `JUDGE_MODEL_NAME` / `JUDGE_API_URL`
  - Leave empty auto fallback to `LLM_*` (same model as both tested and judge — simple but has
    self-judging bias)
  - Separate config后judge only runs scoring step, volume small, recommend stronger model to avoid bias
- Commands below assume you're in this directory (`sdk/benchmark/longmemeval_eval/`)

---

## Two Steps

### Step 1: Download Data

```bash
python download_data.py
```

Writes to `data/longmemeval_s_star.jsonl` (~30MB).

### Step 2: Run Evaluation

```bash
# Smoke test: 1 conversation, 1 question, only ingest first 6 sessions (must trigger compression)
python run_longmemeval.py \
    --dialogue_index 0 --limit 1 \
    --max_ingest_sessions 6 --sessions_per_batch 2 \
    --token_threshold 3000 --keep_recent_pairs 1 \
    --baseline_context_chars 40000

# Default sample: 5 conversations × 20 questions = 100 questions
python run_longmemeval.py

# Full: 5 conversations × 60 questions = 300 questions
python run_longmemeval.py --limit 60
```

---

## `run_longmemeval.py` Parameter Details

### Evaluation Scope

| Parameter | Default | Meaning |
|---|---|---|
| `--data_file` | `data/longmemeval_s_star.jsonl` | Download script produced data |
| `--dialogue_limit` | All (5) | Only run first N conversations |
| `--dialogue_index` | None | Only run specific index conversation (0-4), overrides `--dialogue_limit` |
| `--limit` | **20** | Per-conversation only run first N questions (**default sample**; set 60 for full 300 questions) |

### Compressed Arm: ContextManager Configuration

| Parameter | Default | Meaning |
|---|---|---|
| `--token_threshold` | `12000` | Cumulative context exceeds this token count triggers compression, smaller = more aggressive |
| `--keep_recent_pairs` | `2` | How many pairs (user, assistant) to retain uncompressed at tail |
| `--keep_recent_steps` | `4` | ContextManager within-turn retain step count |
| `--max_observation_length` | `20000` | Single observation character limit |
| `--sessions_per_batch` | `4` | How many atomic sessions per ingest batch (larger = fewer compression rounds, larger per-round input) |
| `--max_ingest_sessions` | `0` (entire) | Compressed arm only takes first N sessions, **for smoke testing**—small value drastically speeds up |
| `--ingest_max_steps` | `2` | Ingest agent max steps (only triggers compression, 2 steps sufficient) |

### Scoring Arm

| Parameter | Default | Meaning |
|---|---|---|
| `--probe_max_steps` | `3` | Each probe agent max steps |

Scoring uses LLM-as-judge:

- Each question_type has one judge prompt (`eval_utils.py`)
- Judge model parsed by env priority: `JUDGE_*` → `LLM_*` → fallback substring match
- Judge actual behavior printed in `outputs/.../predictions.jsonl`'s `judge_label` field
  (`yes` / `no` / `unknown` / `error` / `fallback_*`)

### Baseline Arm

`longmemeval_s*` conversations ~1.6M chars (~355K tokens), **when window not large enough must truncate**.

| Parameter | Default | Meaning |
|---|---|---|
| `--baseline_context_chars` | `480000` | Baseline feed character limit (estimate by model window) |

### Debug / Skip

| Parameter | Default | Meaning |
|---|---|---|
| `--skip_baseline` | No | Skip baseline (save time when iterating compression params) |
| `--skip_compressed` | No | Skip compressed arm |
| `--debug` | No | Print agent debug output |

---

## Evaluation Dimensions and Output

Both arms answer **same questions**, retention ratio clean:

```
memory_retention = compressed_accuracy / baseline_accuracy
token_reduction  = 1 - last_compressed_tokens / last_uncompressed_tokens
```

`token_reduction` same method as `manual_cases` / `eventqa_eval`: Take compressed arm last
ingest turn's `ContextManager.get_token_counts()` single-point sampling.

**New dimension (vs `eventqa_eval`)**: Report retention bucketed by 6 question_types,
locate which memory categories compression hurts.

No Continuation evaluation—LongMemEval questions independent.

Output written to `outputs/`:

```
outputs/
├── <dialogue_id>/
│   ├── predictions.jsonl   # Per-question baseline vs compressed answers + judge labels
│   └── summary.json        # Single-conversation metrics + complete compression summary + per-category
└── summary.json            # Cross-conversation aggregate + per-category grouped metrics
```

---

## Differences from eventqa_eval (Key)

| | eventqa_eval | longmemeval_eval |
|--|--|--|
| History format | Novel continuous prose, char-chunked into `[Novel part X]` envelope | **Real multi-session conversation**, by session chunk, turns as-is as `(user, assistant)` pairs into history |
| Scoring | Six-choice MCQ → string match | **Free text → LLM-as-judge** (per-type different prompts) |
| Default schema | `default` / `narrative` / `both` | **Only SDK default schema** (first test production behavior, schema experiments pending) |
| Probe independence | ✓ | ✓ |
| Dimensions | Single accuracy + token_reduction | accuracy + token_reduction + **per-category retention** (6 types) |

---

## Notes

- **Self-judging bias**: Default fallback uses same `LLM_*` model as judge, numbers biased optimistic.
  For formal comparison recommend separate `JUDGE_*` config (external stronger model like GPT-4o).
- **Sample vs full**: Default `--limit 20` (5 × 20 = 100 questions) suitable for iteration; for formal numbers
  run `--limit 60` (5 × 60 = 300 questions).
- **Ingest is fixed cost**: Unrelated to `--limit`—entire conversation history must be compressed once.
- Data download if HF SSL jitter will auto fallback to local cache.