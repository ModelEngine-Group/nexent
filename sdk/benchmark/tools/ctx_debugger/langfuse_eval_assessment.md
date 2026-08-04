# Langfuse Evaluation Capability Adaptation Assessment

For the three benchmarks in this repo (`sdk/benchmark/`) — `manual_cases` / `acon_eval` / `eventqa_eval` — evaluate feasibility and gaps of using Langfuse's built-in **Evaluation / Scores / LLM-as-a-Judge / Human Annotation / Datasets** as the main evaluation framework.

> Scope: Only evaluate Langfuse evaluation features. We already use Langfuse's trace visualization and session grouping (`ctx_debugger/langfuse_export.py`), that part not discussed here.

---

## 1. Langfuse Evaluation Capabilities vs This Repo's Needs

| Langfuse Feature | Design Purpose | Where suitable in this repo |
|---|---|---|
| **Scores** | Attach numeric/category metrics to trace / observation / session | ✅ Attach each question's correct/incorrect / retention / token_reduction; dashboard cross-session comparison |
| **LLM-as-a-Judge** | Let a judge LLM score open-ended answers | ⚠️ Most evaluation here is deterministic (MCQ, EM/F1, keywords); judge反而introduces noise |
| **Human Annotation** | Queue traces for manual annotation | ⚠️ Only useful for open-ended output/quality subjective judgment |
| **Datasets** | Collection of input + expected output pairs, run experiment | ⚠️ Dataset and task model mismatch (see below) |

---

## 2. (a) Overall Benchmark Adaptation Assessment

Three benchmarks' evaluation methods:

| Benchmark | Evaluation Method | Langfuse Replacement Feasibility |
|---|---|---|
| `manual_cases` | `eval_text(text, check)` keyword `must_contain` / `must_contain_any` | Keyword check done externally cheaper, more accurate; **but summary inspection layer switching to LLM-as-a-Judge has value**—current `must_contain` only verifies "appeared or not", judge can ask "does this summary retain key states" |
| `acon_eval` | EM / F1 (deterministic string) | ❌ No need for judge / annotation |
| `eventqa_eval` | Six-choice string match | ❌ No need for judge / annotation |

**Structural gap**: Langfuse's Experiment framework follows **"one input → one LLM call → one output"** model. Our task is **entire agent run + multi-turn ingest + multiple probes**—doesn't match Langfuse Dataset/Experiment's "task per item". Forcing in等于把 `run_*.py`拆成一堆 Langfuse callbacks, complexity rises, benefit small.

**Real incremental value** in two areas:

1. **Scores push (high priority)**: Extend `langfuse_export.py`, attach each probe trace with `correctness: 0/1` score, attach entire session with aggregate `accuracy` / `retention` / `token_reduction`. Dashboard can visualize time-series comparison of different params/schema/models. **Highest ROI integration**.
2. **LLM-as-a-Judge only for `manual_cases` summary inspection layer**: Current `summary_checks` uses `must_contain` keyword check, misses synonymous rewrites. Switch judge evaluating "does summary retain X info" more robust. But don't touch acon/eventqa—MCQ上 judge反而introduces误判.

---

## 3. (b) EventQA Individual Assessment

| Dimension | Langfuse Replacement | Evaluation |
|---|---|---|
| Probe MCQ scoring | Langfuse Scores | ✅ **Feasible and recommended**—attach each probe trace with `correctness: 0/1`, `match_type: exact/containment/fuzzy/no_answer` |
| Token reduction | Langfuse built-in token tracking | ✅ Langfuse **自带 per-call token count** (input/output/cost), more precise than "take last turn get_token_counts"; can use ingest phase LLM calls total tokens as Score |
| Retention (compressed/baseline) | Langfuse cross-session aggregation | ⚠️ Langfuse **不自动算 retention**—only shows各自 acc, ratio needs external calculation then push as Score |
| LLM-as-a-Judge | — | ❌ **Not needed**—MCQ gold is one of six options, deterministic match sufficient; judge introduces unnecessary LLM calls |
| Human Annotation | — | ❌ **Not needed**—same as above |
| Datasets | Put 100 questions into Langfuse Dataset | ⚠️ **Duplicate data storage**—we already have `data/eventqa_full.jsonl`; unless running Langfuse Experiment flow, pure duplication |

### EventQA Specific Gaps

1. **Cannot "end-to-end run EventQA in Langfuse"**—its task model is "one input → one LLM call → one output". EventQA's "input" is entire novel (needs 24 turns of ingest to compress), "output" is 100 question answers. Entire ingest+probe flow forcing into Langfuse Experiment unnatural—still need external `run_eventqa.py` to run, import results in.

2. **Retention is cross-arm ratio**: Langfuse has no "cross session/trace automatic comparison" concept. To get compressed_acc / baseline_acc must calculate externally then push.

3. **Per-probe context cost**: Langfuse's token count is LLM actual input/output tokens, **more precise than `manual_cases`同款 "take last turn effective tokens"**. Can switch to Langfuse-reported real token cost替代 single-point estimate.

---

## 4. Implementation Priority

By descending benefit:

| Priority | Action | Benefit | Work量 |
|---|---|---|---|
| **High (已落地)** | Extend `langfuse_export.py`: Add `--benchmarkqa-outputs <dir>`; each probe trace attach `correctness` (NUMERIC 0/1) + `match_type` (CATEGORICAL), score metadata contains arm / schema / qid. Langfuse UI auto aggregates `correctness` by session, filter by `metadata.arm` can split compressed / baseline. `retention` / `token_reduction` **不push**—already in `outputs/<book>/summary.json`, pushing to Langfuse反而needs creating phantom "session-summary" trace polluting trace list. | Dashboard directly see time-series / cross-session comparison; foundation for other features | ~80 lines |
| **Medium** | Add LLM-as-a-Judge evaluator for `manual_cases`' summary_checks (doesn't miss synonymous rewrites) | Real complement to `must_contain` keyword method | ~100 lines + judge prompt design |
| **Low** | Move EventQA data into Langfuse Dataset | Not much new value—already have jsonl | ~30 lines |
| **Don't do** | Move EventQA evaluation main flow to Langfuse Experiments | Model mismatch—forcing等于把 `run_eventqa.py`拆成一堆 callbacks | × |
| **Don't do** | LLM-as-a-Judge / Human Annotation on MCQ | Introduces noise, no benefit | × |

---

## 5. Summary

- Langfuse's evaluation framework **cannot replace main flow** (agent multi-turn ingest + probe + cross-arm retention structure doesn't match its task model)
- **Only high ROI integration is Scores push**—push existing evaluation results into Langfuse for visualization, convenient cross-session comparison of params/model/schema tuning
- LLM-as-a-Judge / Human Annotation / Datasets only have marginal value for `manual_cases`' summary inspection一小段; for acon/eventqa deterministic evaluation introduces noise