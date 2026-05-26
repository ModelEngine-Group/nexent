# Agent Context Compression Benchmark

## Objectives

Evaluate whether the compressed Agent can still function properly:

- **Continuation**: Can the agent continue the task after compression?
- **Memory Retention**: Can the agent remember key states after compression?
- **Token Reduction**: Does the token count effectively decrease?


---

## Two Evaluation Paths

```
benchmark/
├── manual_cases/          # Handcrafted cases, complete evaluation pipeline
├── acon_eval/             # QA evaluation based on ACON dataset
├── eventqa_eval/          # Long-text memory evaluation based on EventQA dataset
└── paths.py               # Shared path resolution
```

### 1. manual_cases — Handcrafted Case Evaluation

Handcrafted test cases running the complete evaluation pipeline (continuation, probe, static inspection).

```
manual_cases/
├── cases/                         # test_benchmark.py input
│   └── <case_id>/
│       ├── case.json              # queries, probes, checks, config
│       └── history.json           # conversation history
├── inspections/                   # summary_inspector.py input (standalone run)
│   └── <name>/
│       ├── history.json
│       ├── checks.json            # [{"description": "...", "must_contain": [...]}]
│       ├── _result.json           # output: inspection results
│       └── _summary.txt           # output: raw summary text (--save-summary)
├── reports/                       # test_benchmark.py output
│   ├── <case_id>.json            # single-case complete report
│   └── summary.json              # cross-case aggregate metrics
├── agent_runner.py                # agent run + tracing utilities
├── eval_utils.py                  # keyword evaluation
├── summary_inspector.py           # standalone summary inspection (low cost, no agent run)
└── test_benchmark.py              # complete benchmark runner
```

`case.json` format:

```json
{
  "id": "example_infra",
  "history_file": "history.json",
  "queries": [],
  "probes": [],
  "summary_checks": [],
  "task_checks": [],
  "compressed_config": {}
}
```

- `id`: unique case identifier, also used as report filename
- `history_file`: conversation history file, relative to case directory (default `history.json`)
- `queries`: continuation queries
- `probes`: memory probe questions
- `summary_checks`: static summary inspections
- `task_checks`: task result inspections
- `compressed_config`: compression config overrides

`history.json` format:

```json
[
  {"role": "user", "content": "..."},
  {"role": "assistant", "content": "..."}
]
```


#### Evaluation Metrics

Each case runs two groups:

1. **baseline** (no compression)
2. **compressed** (compression enabled)

Core metrics:

```python
task_success_retention = compressed_task_score / baseline_task_score

probe_retention = compressed_probe_score / baseline_probe_score

token_reduction = 1 - compressed_tokens / baseline_tokens
```

---

**Continuation Evaluation**
Continuation queries simulate real multi-turn Agent interactions.

Allowed:

- history growth
- continuous compression occurrence
- ContextManager reuse across turns

This is a **stateful** evaluation.


**Probe Evaluation**
Probes check whether the compressed agent can **utilize** residual information to answer questions.

Important rules:

- freeze the compressed history snapshot (deep copy per probe)
- each probe runs independently
- probes cannot modify the original history (isolated via deep copy)
- probes cannot share context with each other

Compression happens once, all probes reuse the result:

1. Get summary + compression_boundary from the compressed run's `export_summary()`
2. Build precompressed history with `build_precompressed_history()`:
   - compressed pairs replaced with a single (user=summary, assistant=ack)
   - retained tail pairs preserved verbatim
3. Each probe runs with precompressed history + compression disabled
4. Avoid redundant compression LLM calls per probe (same input → same compression result, no need to call LLM repeatedly)


### 2. acon_eval — Dataset-driven QA Evaluation

Uses ACON's `nq_multi_8` dataset (multi-objective questions + Wikipedia search) to evaluate compression's impact on QA accuracy.

Unlike manual_cases, this **does not use** handcrafted probes or continuation queries, but directly compares baseline vs compressed **task accuracy** (EM/F1) on a standardized dataset.

```
acon_eval/
├── data/nq_multi_8/              # ACON dataset (JSONL)
│   ├── train.jsonl
│   ├── test.jsonl
│   └── folds/                    # few-shot fold data
├── outputs/                      # results per mode
│   ├── baseline/test/
│   │   ├── predictions.jsonl
│   │   └── summary.json
│   └── context_manager/test/
│       ├── predictions.jsonl
│       └── summary.json
├── agent_runner.py                # agent run + tracing
├── dataset.py                     # ACON dataset loader
├── eval_utils.py                  # EM/F1 scoring
├── run_acon_qa.py                 # main entry point
└── tools.py                       # wikipedia_search + final_answer tools
```

Usage:

```bash
# First start ACON retriever service (see ACON README) https://github.com/microsoft/acon/blob/main/experiments/smolagents/README.md
#  python retriever_server.py  --index_path database/wikipedia/bm25/   --corpus_path database/wikipedia/wiki-18.jsonl
# The retriever_server.py above has been modified (see this directory's version). Also need to manually download bm25 index files and wiki-18 dataset
# bm25: https://huggingface.co/datasets/PeterJinGo/wiki-18-bm25-index/tree/main/bm25
# wiki-18: https://huggingface.co/datasets/PeterJinGo/wiki-18-corpus/tree/main
python run_acon_qa.py \
    --data_folder ./data/nq_multi_8 \
    --split test \
    --mode baseline \
    --num_objectives 4 \
    --limit 1

python run_acon_qa.py \
    --data_folder ./data/nq_multi_8 \
    --split test \
    --mode context_manager \
    --num_objectives 4 \
    --token_threshold 6000 \
    --keep_recent_steps 4 \
    --enable_reload \
    --limit 1

```

**Modes**: `baseline` (no compression) vs `context_manager` (nexent built-in compression).
**Note**: The conversation history structure here differs from manual_cases. This test scenario has no previous history, only multi-step within the current session.

---

### 3. eventqa_eval — EventQA Long-text Memory Evaluation

Uses MemoryAgentBench's EventQA dataset (5 novels, each 390K–530K tokens, 100 "what happens next" six-choice MCQs per book) to evaluate compression's impact on **ultra-long document memory**.

Like acon_eval, this is dataset-driven but with a different scenario: the entire novel as history to be compressed, MCQs directly serve as memory probes—questions come with prior events, naturally asking "given the compressed summary, what happens next", no need for additional probe construction.

```
eventqa_eval/
├── data/                      # novels downloaded by download_data.py
│   └── eventqa_full.jsonl
├── outputs/                   # results per book
│   └── <book_id>/
│   │   ├── predictions.jsonl  # per-question baseline vs compressed comparison
│   │   └── summary.json       # single-book metrics
│   └── summary.json           # cross-book aggregate
├── download_data.py           # download EventQA data from HuggingFace
├── dataset.py                 # EventQA loader + six-choice MCQ parser
├── eval_utils.py              # six-choice accuracy scoring
└── run_eventqa.py             # main entry point
```

**Two evaluation arms** (same model, clean retention ratio):

| Arm | Compression | Novel Context |
|---|---|---|
| Baseline | Disabled | Entire novel truncated to model window then fed whole (questions beyond window will fail) |
| Compressed | Enabled | Novel chunked and fed in multiple turns, real ContextManager incremental compression; MCQs as probes |

Both arms answer **the same 100 questions**, so the retention ratio is clean:

```python
memory_retention = compressed_accuracy / baseline_accuracy

token_reduction  = 1 - last_compressed_tokens / last_uncompressed_tokens
```

No Continuation evaluation—EventQA MCQs are independent, no multi-turn task continuation.

Usage:

```bash
# One-time: download 5 novels (~13MB, written to data/)
python download_data.py

# Smoke test: 1 book, 1 question, novel truncated to 48K chars (trigger compression)
python run_eventqa.py --book_limit 1 --limit 1 \
    --max_ingest_chars 48000 --chunk_chars 12000 \
    --token_threshold 3000 --keep_recent_pairs 1

# Full run: 5 books × 100 questions
python run_eventqa.py
```

**Note**: `eventqa_full` novels are 1.7M–3.2M characters, no model can ingest the entire book without compression, so baseline uses "truncate to window" as the no-compression control (`--baseline_context_chars` controls truncation length). The dataset also has `eventqa_65536` / `eventqa_131072` pre-truncated variants, but their questions differ from `eventqa_full`, cannot directly compare with full.

---

## Supplementary Notes

### Probe Construction Principle: Only Target Compressed Content

The core purpose of probes is to detect memory retention, i.e., "whether the agent can answer information that was compressed away".
Therefore **probes should only ask about content in the compressed region**, not information retained in the tail steps.

Compression boundary is temporal: `keep_recent_pairs=N` means the last N pairs are preserved verbatim, everything before enters the summary. Therefore:

- **Probes should only ask about details in the early pairs (history first half)**
- If a probe asks about information in recent pairs, the agent can answer without the summary, the probe fails—cannot measure memory retention

When constructing probes, no need to know exactly what the compressor retained, just ensure probe-dependent information comes from early history (region that will definitely be compressed).

**Verify probe design**: Use `export_summary()`'s `compression_boundary` field to confirm which pairs were compressed vs retained. If the probe's answer isn't in the summary at all, that's a compressor problem (belongs to Static Inspection layer), not an agent problem.

---

### Static Summary Inspection vs Probe Eval

Both test different failure modes:

| | Probe Eval | Static Summary Inspection |
|--|-----------|--------------------------|
| Input | Complete compressed context (summary + retained tail steps + system prompt) | Summary text only |
| Execution | Let agent answer questions (run LLM) | Directly inspect summary text for key information |
| What it tests | Whether agent **can utilize** residual information | Whether compressor **chose to retain** key information |
| Failure meaning | Summary has it but agent didn't use it → retrieval/utilization capability issue | Summary doesn't have it → compressor lost it |

**Two different failure modes**:
1. Compressor retained, but agent didn't utilize → **Probe Eval** catches this, Inspection won't
2. Compressor didn't retain at all → Both catch this, but should attribute to Inspection layer

---

### Static Summary Inspection

Directly inspect whether the compressed summary still contains key information.

#### Online Approach

After agent run, export compression state:

```python
compressed_state = shared_cm.export_summary()
# compressed_state contains:
#   previous_summary / current_summary: compressed summary text
#   compression_boundary: which pairs/steps were compressed vs retained
#   previous_cache_info / current_cache_info: cache metadata

for check in summary_checks:
    eval_text(compressed_state["previous_summary"], check)
```

#### Offline Approach

Run compression on pure text pairs without agent, using the same prompt and schema:

```python
from nexent.core.agents.agent_context import compress_history_offline

result = compress_history_offline(
    pairs=[("What user said", "What assistant did"), ...],
    model=llm_model,
    config=ContextManagerConfig(),
)
# result["summary"]: compressed summary
# result["is_incremental"]: whether incremental compression was used
# result["is_fallback"]: whether LLM failed and used fallback
# result["input_text"]: raw text fed to LLM (for debugging)

eval_text(result["summary"], {"must_contain": ["key_filename"]})
```

Offline approach advantages:
- No need to run agent, just one LLM call for compression
- No dependency on AgentMemory, ActionStep and other runtime objects
- Suitable for batch evaluation of different prompt/schema impacts on compression quality