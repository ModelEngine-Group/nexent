# eventqa_eval — EventQA Long-text Memory Evaluation

Based on **EventQA** dataset from MemoryAgentBench, evaluate the impact of **context compression** on ultra-long document memory: an entire novel as history to be compressed, can it still correctly answer "what happens next" questions?

> Evaluation methods and dimensions follow the rest of `sdk/benchmark`: **baseline (no compression) vs compressed (compression)** comparison. This file covers **how to run** and **what each parameter means**.

---

## Dataset

EventQA comes from ∞-Bench's 5 novels (Gone with the Wind, Les Misérables, The Count of Monte Cristo, David Copperfield, Anna Karenina), each 390K–530K tokens. Each book has 100 six-choice MCQs: given prior events that have occurred, select the true continuation from 6 candidates (1 true + 5 GPT-4o distractors).

Data is in HuggingFace `ai-hyz/MemoryAgentBench`'s `Accurate_Retrieval` split, rows with `metadata.source == "eventqa_full"` are the full novel versions.

---

## Prerequisites

- Use backend's venv: `nexent/backend/.venv/bin/python` (requires `huggingface_hub`, `pyarrow`)
- LLM credentials in repo root `nexent/.env`: `LLM_API_KEY` / `LLM_MODEL_NAME` / `LLM_API_URL`
- Commands below assume you're in this directory (`sdk/benchmark/eventqa_eval/`)

---

## Two Steps

### Step 1: Download Data

```bash
python download_data.py
```

Download `Accurate_Retrieval` split from HuggingFace, extract 5 `eventqa_full` rows, write to `data/eventqa_full.jsonl` (~13MB, already `.gitignore`, not committed).

| Parameter | Default | Meaning |
|---|---|---|
| `--source` | `eventqa_full` | Which variant: `eventqa_full` (entire), `eventqa_65536` (truncated to 64K tokens), `eventqa_131072` (truncated to 128K tokens). Note truncated variants have **different questions** than full |
| `--output_dir` | `./data` | Output directory |

### Step 2: Run Evaluation

```bash
# Smoke test: 1 book, 1 question, novel truncated to 48K chars
python run_eventqa.py --book_limit 1 --limit 1 \
    --max_ingest_chars 48000 --chunk_chars 12000 \
    --token_threshold 3000 --keep_recent_pairs 1

# Full run: 5 books × 100 questions
python run_eventqa.py
```

---

## `run_eventqa.py` Parameter Details

### Evaluation Scope

| Parameter | Default | Meaning |
|---|---|---|
| `--data_file` | `data/eventqa_full.jsonl` | Data file produced by `download_data.py` |
| `--book_limit` | All (5) | Only evaluate first N books. For smoke test set `1` |
| `--limit` | All (100) | Only run first N questions per book. For smoke test set `1` |

### Compressed Arm: ContextManager Configuration

The entire novel will be chunked and fed in multiple turns, triggering real ContextManager incremental compression.

| Parameter | Default | Meaning |
|---|---|---|
| `--token_threshold` | `12000` | ContextManager compression trigger threshold. When cumulative context exceeds this token count, compression triggers. **Lower = earlier, more aggressive compression** |
| `--keep_recent_pairs` | `2` | How many chunks to retain uncompressed at tail (rest enters summary). **Total chunks must > this value for compression to actually occur** |
| `--keep_recent_steps` | `4` | ContextManager retains how many steps in current turn uncompressed |
| `--max_observation_length` | `20000` | ContextManager single observation max character count |
| `--chunk_chars` | `20000` | Character count per novel chunk. Total chars / this value = chunk turns. **Recommended ≲ token_threshold equivalent chars**, so each turn's incremental compression input stays within budget, uses fast incremental path; too large degrades to full re-compression |
| `--max_ingest_chars` | `0` (entire) | Compressed arm only takes first N chars of novel. **For smoke testing**—set small value (e.g., `48000`) to drastically shorten one book's ingest time. `0` means use entire novel |
| `--ingest_max_steps` | `2` | Max steps per ingest (acknowledge) agent run. Ingest agent only triggers compression, small step count sufficient |
| `--summary_schema` | `default` | Which summary template compressed arm uses: `default` / `narrative` / `both`, see below |

### Two Summary Schemas (`--summary_schema`)

ContextManager's default summary schema targets agent tasks (`active_task` / `completed_work` / `relevant_files` …). When compressing narrative novels, ~9 of 10 fields become "None", entire plot squeezed into single `critical_context` field (also capped ≤300 words)—will lose much plot detail, artificially lowering compressed scores.

Therefore evaluation provides two schemas:

| Schema | Fields | What it tests |
|---|---|---|
| `default` | active_task / completed_work / relevant_files … (10, agent-task oriented) | "Production ContextManager as-is" performance on narrative documents |
| `narrative` | events_so_far / characters / recent_events / unresolved_threads / setting (5, narrative oriented) | Whether compression **mechanism** with adapted template can retain narrative memory |

`narrative` still uses **real ContextManager class + same incremental compression code path**, only replacing summary template (prompts + JSON schema, both are `ContextManagerConfig` fields).

`--summary_schema both` lets compressed arm run both schemas. Difference between them can isolate loss sources:

- `default` vs `narrative` gap → how much loss from **schema mismatch**
- `narrative` vs baseline gap → how much loss from **compression ratio itself**

Note: `both` makes compressed arm (ingest + probes) run twice, ~doubling time.

### Baseline Arm

`eventqa_full` novels are 1.7M–3.2M chars, **no model can ingest entire book without compression**, so baseline uses "truncate to model window" as no-compression control.

| Parameter | Default | Meaning |
|---|---|---|
| `--baseline_context_chars` | `480000` | Novel character count fed to baseline arm (truncate from start). Set to your model's context window capacity. Questions about events beyond window, baseline will fail—this is exactly what we're testing |

### Probe (Probe) Execution

| Parameter | Default | Meaning |
|---|---|---|
| `--probe_max_steps` | `3` | Max steps per MCQ probe agent run |

### Skip One Arm / Debugging

| Parameter | Default | Meaning |
|---|---|---|
| `--skip_baseline` | No | Skip baseline arm (use when iterating compressed arm only) |
| `--skip_compressed` | No | Skip compressed arm (use when iterating baseline only) |
| `--debug` | No | Print agent debug output |

---

## Smoke Command Item-by-item Explanation

```bash
python run_eventqa.py --book_limit 1 --limit 1 \
    --max_ingest_chars 48000 --chunk_chars 12000 \
    --token_threshold 3000 --keep_recent_pairs 1
```

- `--book_limit 1`: Only evaluate 1 book (not all 5)
- `--limit 1`: This book only runs 1 question (not all 100)
- `--max_ingest_chars 48000`: Compressed arm only takes first 48K chars, not entire book—speeds up smoke test
- `--chunk_chars 12000`: Each chunk 12K chars → `48000 / 12000 = 4` chunks
- `--token_threshold 3000`: Cumulative context exceeds 3000 tokens triggers compression (small value, ensures compression triggers during smoke)
- `--keep_recent_pairs 1`: Tail only retains 1 chunk uncompressed → 4 chunks, first 3 enter compression region

Overall effect: With minimal novel and question count, ensure **compression actually triggers**, end-to-end flow completes.

---

## Evaluation Dimensions and Output

Both arms answer **the same questions**, so retention ratio is clean:

```
memory_retention = compressed_accuracy / baseline_accuracy
token_reduction  = 1 - last_compressed_tokens / last_uncompressed_tokens
```

**`token_reduction` same method as `manual_cases`**: Take compressed arm's **last ingest turn**'s `ContextManager.get_token_counts()`, calculate `1 - last_compressed / last_uncompressed` (corresponds to `manual_cases/test_benchmark.py` main algorithm). `acon_eval` doesn't measure token_reduction. Note this is "last turn" single-point sampling—if two schemas' last turns happen to have same token count, `token_reduction` will be same, this is inherent behavior of this method, not anomaly.

No Continuation evaluation—EventQA MCQs are independent.

Output written to `outputs/` (compressed metrics grouped by schema, `--summary_schema both` includes both):

```
outputs/
├── <book_id>/
│   ├── predictions.jsonl   # Per-question: baseline vs each schema's compressed comparison
│   └── summary.json        # Single-book metrics + each schema's compression info/summary
└── summary.json            # Cross-book aggregate, includes per_schema grouped metrics
```

---

## Full Run Time Estimation

Based on DeepSeek-v4-flash smoke test (Les Misérables entire book, single-step latency):

| Stage | Unit Time (measured, approximate) | Notes |
|---|---|---|
| Ingest turn | ~20 s/turn | Chunk feed-in + one incremental compression LLM call |
| Compressed probe | ~60 s/question | Compressed context small, but model reasoning output long |
| Baseline probe | ~110 s/question | Entire novel fed in (400K–740K tokens), agent ~2 steps |

- **Ingest turns = novel chars ÷ chunk_chars**. Default `chunk_chars=20000` means 5 books total ~590 turns. Ingest is **fixed cost, unrelated to `--limit`** (entire book must be compressed).
- Baseline probes are the time bottleneck: each question feeds entire book, agent often runs ~2 steps, each step re-sends entire book.

**Full run (5 books × 100 questions, default params) rough estimate:**

| Stage | Count | Estimated Time |
|---|---|---|
| Ingest | ~590 turns × 20s | ~3.3 h |
| Compressed probes | 500 questions × 60s | ~8.3 h |
| Baseline probes | 500 questions × 110s | ~15 h |
| **Total** | | **~25–30 hours** |

**Sampled run (`--limit 20`, 5 books × 20 questions) rough estimate:** Ingest fixed ~3.3 h + probes ~5 h ≈ **8–9 hours**.

Recommendations:

- First use `--limit` sampling (e.g., `--limit 20`) to confirm results reasonable before expanding.
- To speed up ingest, increase `--chunk_chars` (turns halved, time ~halved), trade-off is larger per-turn compression input.
- When iterating one arm only, use `--skip_baseline` / `--skip_compressed`—baseline is time bottleneck.

> Note: Smoke test confirmed **DeepSeek V4 (1M window) can ingest entire Les Misérables** (3,171,853 chars ≈ 743,179 tokens, single call without truncation, no error), all 5 books can be fully ingested for baseline arm.