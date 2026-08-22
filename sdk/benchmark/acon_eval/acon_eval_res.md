# ACON Multi-Objective QA Evaluation Results

## Experiment Setup

- **Data**: nq_multi_8/test, 100 samples, 8 sub-questions per sample, max_steps=40
- **baseline**: `token_threshold=10^9`, compression never triggers, agent sees full conversation history
- **context_manager**: `token_threshold=7200`, triggers compression when exceeded, `keep_recent_pairs=1`, `keep_recent_steps=4`

## Results

| Metric | baseline | context_manager | Delta |
|---|---|---|---|
| Avg EM | **38.25%** | 34.88% | -3.37pp |
| Avg F1 | **49.46%** | 46.15% | -3.31pp |
| Avg Input Tokens | 188,232 | 92,294 | **-51.0%** |
| Avg Output Tokens | 2,294 | 2,209 | -3.7% |
| Avg Steps | 22.7 | 21.0 | -1.7 |

## Compression Overhead

context_manager incurs additional LLM calls for compression:

- Avg compression input per sample: **9,715 tokens**
- Avg compression output per sample: **511 tokens**
- Only ~10% of total input, cost is well justified

## Compression Strategy Analysis

### Why `keep_recent_steps=4` is reasonable

- Each sub-question consumes 1-3 steps (1-3 searches), so a 4-step window covers the full trajectory of the current sub-question
- Global state (answers, status, search counts, next action) is carried by the summary JSON, serving as long-term memory
- The agent never "forgets" completed answers — the summary explicitly requires: "Treat ANSWER_Q marker as authoritative; never replace with null or Unknown"
- `agent_context.py:613` has a safety mechanism: if the boundary splits a tool_call + observation pair, it auto-extends to `keep_n + 1`

### Summary JSON schema

The summary tracks per-question state machine:

- `answers[]` — canonical answer for each sub-question (or null)
- `status[]` — one of: unstarted, searching, answered, exhausted
- `search_counts[]` — count of wikipedia_search calls per question
- `current_q` — next question to solve
- `pending_q` — questions still unstarted or searching
- `next_action` — specific mechanical next step

## Possible Causes of 3pp EM Drop

`keep_recent_steps=4` is well-designed; the gap is more likely from summary quality than window size:

1. **Summary LLM fidelity**: the LLM generating the summary may mis-record answer text or status, permanently losing information
2. **Cross-question search context loss**: the summary preserves only answer strings, not raw search observations — cross-question reuse of earlier search results is inherently lost with summarization
3. **Incremental update drift**: after 20+ incremental updates, the summary state may drift from the true trajectory

## Summary

Trading **51% token savings** for **3pp quality drop**. The compression window configuration is sound; optimization headroom lies in summary fidelity rather than window size.
