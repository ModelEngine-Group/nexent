# Benchmark Testing Mechanism Analysis
> Benchmarks like LongBench, LooGLE, Needle evaluate the base LLM's long-context understanding capability (one-time input of long text, testing understanding/reasoning/retrieval), not Agent's context compression capability (after multi-turn interaction history is compressed, testing whether it can continue working).

## 1. Core Objectives

Evaluate the practical effectiveness of **Agent Context Compression**, answering:

> **After compression, can the Agent still work and remember key states?**

Does not evaluate text similarity between summary and original, but evaluates **functional retention**.

Three key dimensions:
- **Continuation**: Can the task continue after compression
- **Memory Retention**: Can key states be remembered after compression
- **Token Reduction**: Does token count effectively decrease

---

## 2. Test Structure: Two Experiments Per Case

Each `cases/<case_id>/` directory contains:
- `history.json`: Initial multi-turn conversation history (user/assistant pairs)
- `case.json`: Test configuration and inspection criteria

Each case runs two comparison experiments:

| Group | Compression Status | Purpose |
|---|---|---|
| **Baseline** | `enabled=False` | No compression, measure capability ceiling |
| **Compressed** | `enabled=True` + custom params | Enable compression, measure actual performance |

---

## 3. Case Configuration Key Fields

```json
{
  "queries": [],        // Multi-turn continuation questions
  "probes": [],         // Memory probe questions (test early history)
  "task_checks": [],    // Task output checks
  "summary_checks": [], // Static summary checks
  "compressed_config": {} // Compression parameter overrides
}
```

---

## 4. Three Evaluation Dimensions

### 4.1 Continuation Evaluation (Task Continuation Capability)

Simulate real multi-turn Agent interaction:
- Execute `queries` in sequence, append `(query, answer)` to history each turn
- Compressed group **shares the same ContextManager**, compression **continuously triggers** during execution
- Score `final_answer` at specified turns with `task_checks`

**Metric**: `task_success_retention = compressed_task_score / baseline_task_score`

---

### 4.2 Probe Evaluation (Memory Retention Capability)

Test whether the compressed Agent can **utilize** residual information in the summary to answer questions about early history.

**Key Design** (avoid redundant LLM calls):
1. Get summary and compression boundary from compressed run's `export_summary()`
2. `build_precompressed_history()` constructs precompressed history:
   - Compressed prefix pairs → replaced with a single user summary message
   - Retained tail pairs → preserved verbatim
3. All probes **reuse the same** precompressed history
4. Each probe `deep copy` then **runs independently**, compression disabled

Baseline Probe also runs on the full history after compressed run ends, establishing the ceiling.

**Metric**: `probe_retention = compressed_probe_score / baseline_probe_score`

**Probe Construction Principle**: Only ask about information in the compressed region (early history). If asking about tail retained region, cannot measure memory retention.

---

### 4.3 Static Summary Inspection (Compressor Static Quality)

Run without Agent, directly check whether summary text contains key information.

- Apply `summary_checks` to `previous_summary + current_summary`
- Distinguish failure root causes from Probe Eval:

| | Probe Eval | Static Inspection |
|---|---|---|
| Input | Complete compressed context (summary + retained tail steps) | Summary text only |
| Execution | Run Agent (LLM) | Direct text inspection |
| What it tests | Agent **can utilize** residual information | Compressor **did retain** key information |
| Failure meaning | Summary has it but Agent didn't use it | Summary doesn't have it at all |

---

## 5. Token Reduction Calculation

Two-level fallback:
1. **Prefer ContextManager actual token statistics**: Take `last_uncompressed` vs `last_compressed` from the last turn of compressed run
2. **Fallback text estimation**: `1 - compressed.final_tokens / baseline.final_tokens`

---

## 6. Final Report Structure

```json
{
  "case_id": "...",
  "baseline": { "task_score", "probe_score", "final_tokens" },
  "compressed": { "task_score", "probe_score", "final_tokens", "cm_stats", "cm_summary" },
  "metrics": {
    "task_success_retention": ...,   // Task continuation retention rate
    "probe_retention": ...,          // Memory probe retention rate
    "token_reduction": ...,          // Token reduction rate
    "summary_score": ...             // Static summary score
  },
  "task_eval": [...],
  "probe_eval": { "baseline": [...], "compressed": [...] },
  "summary_inspection": [...]
}
```

All cases aggregated to `reports/summary.json`.

---

## 7. Key Design Principles Summary

1. **Stateful Continuation**: Compressed group shares `ContextManager`, simulates real execution
2. **Probe Isolation**: Each probe `deep copy` + independent run, no cross-contamination
3. **Probe Reuses Compression Result**: Precompressed history built once, avoid redundant LLM calls
4. **Inspection vs Probe Separation**: Distinguish "compressor missed it" vs "Agent didn't use it" failures
5. **Functional Testing Only**: No text similarity measurement, test Agent's actual working capability in compressed context