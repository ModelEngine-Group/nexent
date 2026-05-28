#!/usr/bin/env python3
"""Run the LongMemEval (S*) benchmark with the nexent agent.

LongMemEval (S*) from MemoryAgentBench gives 5 long multi-session dialogues
(~355K tokens each) with 60 free-text questions per dialogue (300 total),
labelled with six ability categories:

  * single-session-user / -assistant / -preference  (information extraction)
  * multi-session                                   (multi-session reasoning)
  * knowledge-update                                (keep the latest value)
  * temporal-reasoning                              (dates / durations)

IMPORTANT: LongMemEval contains MANY INDEPENDENT TOPICS (job search, work hours,
bereavement support, travel, shopping, etc.), not a single continuous task.
The default "active_task" schema fails here — it discards older topics.
Use --summary_schema multi_topic to preserve all topics.

This script keeps the same evaluation method as the rest of ``sdk/benchmark``
(baseline vs compressed, retention as the ratio of the two) but adapted to a
multi-session conversational memory task:

  * Baseline   — the dialogue's flattened text is truncated to the model's
                 context window and fed whole, with NO compression. Questions
                 whose evidence lies past the truncation point are expected
                 to fail.
  * Compressed — the FULL multi-session chat history is streamed in as real
                 (user, assistant) turn pairs; the real ContextManager
                 incrementally compresses it. The 60 questions are then run
                 as memory probes against the pre-compressed context.

Both arms answer the SAME questions, so the retention ratio is clean:

    memory_retention = compressed_accuracy / baseline_accuracy
    token_reduction  = 1 - last_compressed_tokens / last_uncompressed_tokens

Continuation is not measured — LongMemEval questions are independent.

Default scope is the full benchmark: 5 dialogues x 60 questions = 300 Q.
Pass --limit 20 (or any smaller value) to sample for quick iteration.

Usage:
    python download_data.py            # one-time: fetch the dataset
    python run_longmemeval.py --dialogue_index 0 --limit 1   # smoke
    python run_longmemeval.py --limit 20                     # 100-Q sample
    python run_longmemeval.py                                # full 300 Q

Results are written to outputs/<dialogue_id>/ and outputs/summary.json.
"""
import argparse
import asyncio
import copy
import json
import os
import sys
from collections import defaultdict

# ---- Path setup (mirrors eventqa_eval/run_eventqa.py) ----
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths  # noqa: F401 - side effect: adds sdk/, backend/ to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent_runner import (
    build_agent_run_info,
    run_agent_with_tracking,
    ContextManagerConfig,
)
from nexent.core.agents.agent_model import AgentHistory
from nexent.core.agents.agent_context import ContextManager

from dataset import load_dialogues, LongMemEvalDialogue, LongMemEvalSession
from eval_utils import judge_answer, judge_configured
from summary_schemas import build_multi_topic_config


# ============ Agent duty prompts ============

INGEST_DUTY = (
    "You are reading a long multi-session chat conversation between a user and "
    "an assistant. Earlier sessions are already in your conversation history "
    "in their original chronological order. The next message will simply ask "
    "you to acknowledge the latest batch of sessions you have just seen. "
    "Do not analyze or summarize anything. Acknowledge by calling final_answer "
    'with the single word: OK'
)

PROBE_DUTY = (
    "You are answering a question about a long multi-session chat conversation "
    "between a user and an assistant. The entire conversation history (or a "
    "compressed summary of it) is in your context. The user is asking you to "
    "recall some fact from that history.\n"
    "Rules:\n"
    "- Answer the question DIRECTLY in a single short sentence — give the "
    "fact, not your reasoning.\n"
    "- If the user has updated some information over time, answer with the "
    "MOST RECENT value, not an older superseded one.\n"
    "- Answer in a SINGLE step. Your first and only code block must call "
    "final_answer directly.\n"
    '<code>\nfinal_answer("<your concise answer here>")\n</code>'
)


# ============ Pre-compressed history builder ============
# Same shape as eventqa_eval/run_eventqa.py:build_precompressed_history.
# Kept self-contained so this directory does not depend on eventqa_eval.

def build_precompressed_history(
    frozen_history: list[AgentHistory],
    cm_summary: dict,
) -> list[AgentHistory]:
    """Replace the compressed prefix pairs with a single summary message,
    then append the retained tail pairs verbatim.
    """
    boundary = cm_summary.get("compression_boundary", {})
    compressed_pairs = boundary.get("previous_compressed_pairs", 0)
    compressed_entries = compressed_pairs * 2

    summary_text = cm_summary.get("previous_summary") or ""
    if not summary_text or compressed_entries == 0:
        return list(frozen_history)

    precompressed = [
        AgentHistory(
            role="user",
            content=f"Summary of earlier sessions in this conversation:\n{summary_text}",
        ),
    ]
    if compressed_entries < len(frozen_history):
        precompressed.extend(frozen_history[compressed_entries:])
    return precompressed


# ============ Session batching ============
# The haystack is already 100-120 atomic (user,assistant,...) sessions per
# dialogue. We group N sessions per "ingest batch" — the agent runs once per
# batch to trigger compression, and the real turns are appended directly to
# the conversation history so the chat structure is preserved (unlike the
# novel-prose envelope used by eventqa_eval).

def turns_to_pairs(session: LongMemEvalSession) -> list[tuple[str, str]]:
    """Squash a session's turns into well-formed (user, assistant) pairs.

    Real sessions occasionally have consecutive turns of the same role
    (rare but observed). We coalesce runs of same-role turns into one, then
    pair user with the following assistant. A trailing unpaired user turn is
    paired with an empty assistant ack; a trailing assistant turn without a
    preceding user is dropped (no information attribution).
    """
    coalesced: list[tuple[str, str]] = []  # (role, content)
    for t in session.turns:
        if coalesced and coalesced[-1][0] == t.role:
            coalesced[-1] = (t.role, coalesced[-1][1] + "\n" + t.content)
        else:
            coalesced.append((t.role, t.content))

    pairs: list[tuple[str, str]] = []
    i = 0
    while i < len(coalesced):
        role, content = coalesced[i]
        if role == "user":
            if i + 1 < len(coalesced) and coalesced[i + 1][0] == "assistant":
                pairs.append((content, coalesced[i + 1][1]))
                i += 2
            else:
                pairs.append((content, ""))
                i += 1
        else:
            # leading assistant turn with no user — skip
            i += 1
    return pairs


def session_chunk_text(session_pairs: list[tuple[str, str]]) -> str:
    """Render one batch of session pairs as a plain text block (for the
    chunk_chars / token-budget estimate displayed in logs)."""
    parts: list[str] = []
    for u, a in session_pairs:
        parts.append(f"USER: {u}\nASSISTANT: {a}")
    return "\n\n".join(parts)


# ============ Compressed arm: ingest + compress ============

async def ingest_and_compress(dialogue: LongMemEvalDialogue,
                              cm_config: ContextManagerConfig, args) -> dict:
    """Stream the real chat history into the conversation_history list and
    let ContextManager compress it incrementally.

    Unlike EventQA (which wraps novel prose as [Novel part X] envelopes),
    LongMemEval turns are real user/assistant pairs and go into history as
    such. A tiny no-op agent run per batch is the compression trigger.
    """
    sessions = dialogue.sessions
    if args.max_ingest_sessions > 0:
        sessions = sessions[:args.max_ingest_sessions]

    shared_cm = ContextManager(config=cm_config, max_steps=args.ingest_max_steps)
    conversation_history: list[AgentHistory] = []
    token_counts = None
    ingest_main_input_tokens = 0
    ingest_main_output_tokens = 0

    batch_size = max(args.sessions_per_batch, 1)
    batches: list[list[LongMemEvalSession]] = [
        sessions[i:i + batch_size]
        for i in range(0, len(sessions), batch_size)
    ]

    for batch_idx, batch in enumerate(batches):
        # 1. Append the real turns of this batch to conversation_history.
        new_pairs_count = 0
        for sess in batch:
            for user_text, assistant_text in turns_to_pairs(sess):
                conversation_history.append(AgentHistory(role="user", content=user_text))
                conversation_history.append(
                    AgentHistory(role="assistant", content=assistant_text or "OK")
                )
                new_pairs_count += 1

        # 2. Trigger compression with a no-op acknowledgement query.
        ack_query = (
            f"You have just been shown sessions {batch_idx * batch_size + 1}"
            f"-{batch_idx * batch_size + len(batch)} of {len(sessions)} in "
            f"the conversation history. Acknowledge by emitting exactly:\n"
            f'<code>\nfinal_answer("OK")\n</code>'
        )
        run_info = build_agent_run_info(
            ack_query,
            conversation_history,
            duty_prompt=INGEST_DUTY,
            max_steps=args.ingest_max_steps,
            context_manager_config=cm_config,
            language="en",
            agent_name="longmemeval_reader",
            agent_description="LongMemEval ingest agent",
        )
        run_info.context_manager = shared_cm
        batch_result = await run_agent_with_tracking(run_info, debug=args.debug)
        ingest_main_input_tokens += batch_result.total_input_tokens
        ingest_main_output_tokens += batch_result.total_output_tokens
        token_counts = shared_cm.get_token_counts()

    return {
        "cm_summary": shared_cm.export_summary(),
        "conversation_history": conversation_history,
        "token_counts": token_counts,
        "cm_stats": shared_cm.get_all_compression_stats(),
        "num_batches": len(batches),
        "num_sessions": len(sessions),
        "num_pairs": len(conversation_history) // 2,
        "ingest_main_input_tokens": ingest_main_input_tokens,
        "ingest_main_output_tokens": ingest_main_output_tokens,
    }


# ============ Probe runner ============

async def run_probes(items, history: list[AgentHistory], args) -> tuple[list[dict], dict]:
    """Run each LongMemEval question against a frozen history snapshot.

    Compression is disabled — the history is already in its final form
    (pre-compressed summary, or truncated context). Each probe gets its own
    deep copy and runs fully independently, so we fan them out under a
    bounded semaphore (--probe_concurrency). Result order is preserved via
    asyncio.gather and matches the items order.

    Returns ``(rows, token_totals)`` where ``token_totals`` aggregates the
    main-LLM input/output tokens across all probes (compression is disabled
    in this arm so no compression cost is incurred here).
    """
    disabled_cm = ContextManagerConfig(enabled=False, token_threshold=10 ** 9)
    concurrency = max(1, args.probe_concurrency)
    sem = asyncio.Semaphore(concurrency)

    async def _one(it):
        async with sem:
            probe_history = copy.deepcopy(history)
            run_info = build_agent_run_info(
                it.question,
                probe_history,
                duty_prompt=PROBE_DUTY,
                max_steps=args.probe_max_steps,
                context_manager_config=disabled_cm,
                language="en",
                agent_name="longmemeval_answerer",
                agent_description="LongMemEval question-answering agent",
                max_tokens=args.probe_max_tokens,
            )
            result = await run_agent_with_tracking(run_info, debug=args.debug)
            verdict = judge_answer(
                question=it.question,
                gold=it.answer,
                hypothesis=result.final_answer,
                question_type=it.question_type,
            )
            return {
                "qid": it.qid,
                "question_type": it.question_type,
                "answer": result.final_answer,
                "gold": it.answer,
                "correct": verdict.correct,
                "score": verdict.score,
                "judge_label": verdict.judge_label,
                "judge_raw": verdict.judge_raw,
                "_main_input_tokens": result.total_input_tokens,
                "_main_output_tokens": result.total_output_tokens,
            }

    rows = await asyncio.gather(*(_one(it) for it in items))
    totals = {
        "main_input_tokens": sum(r.pop("_main_input_tokens", 0) for r in rows),
        "main_output_tokens": sum(r.pop("_main_output_tokens", 0) for r in rows),
    }
    return rows, totals


# ============ Per-dialogue run ============

def _fmt(x) -> str:
    return "n/a" if x is None else f"{x:.3f}"


def _aggregate_costs(costs: list[dict | None]) -> dict:
    """Sum per-arm token totals across dialogues for the top-level summary."""
    base_keys = ["main_input_tokens", "main_output_tokens",
                 "compression_input_tokens", "compression_output_tokens",
                 "total_input_tokens", "total_output_tokens", "total_tokens"]
    comp_keys = base_keys + ["ingest_main_input_tokens", "ingest_main_output_tokens",
                             "probe_main_input_tokens", "probe_main_output_tokens",
                             "compression_calls"]
    baseline_agg = {k: 0 for k in base_keys}
    compressed_agg = {k: 0 for k in comp_keys}
    have_compressed = False
    for c in costs:
        if not c:
            continue
        for k in base_keys:
            baseline_agg[k] += c.get("baseline", {}).get(k, 0) or 0
        if c.get("compressed"):
            have_compressed = True
            for k in comp_keys:
                compressed_agg[k] += c.get("compressed", {}).get(k, 0) or 0

    def _ratio(c: int, b: int):
        return (c / b) if b > 0 else None

    ratio = None
    if have_compressed:
        ratio = {
            "input": _ratio(compressed_agg["total_input_tokens"], baseline_agg["total_input_tokens"]),
            "output": _ratio(compressed_agg["total_output_tokens"], baseline_agg["total_output_tokens"]),
            "total": _ratio(compressed_agg["total_tokens"], baseline_agg["total_tokens"]),
        }
    return {
        "baseline": baseline_agg,
        "compressed": compressed_agg if have_compressed else None,
        "ratio": ratio,
    }


def _build_run_config(args) -> dict:
    """Snapshot the run's compression/ingest/probe/baseline params.

    Stored verbatim in summary.json so each output stands alone for
    later analysis without grepping shell history for the command line.
    """
    return {
        "token_threshold": args.token_threshold,
        "keep_recent_pairs": args.keep_recent_pairs,
        "keep_recent_steps": args.keep_recent_steps,
        "max_observation_length": args.max_observation_length,
        "summary_schema": args.summary_schema,
        "sessions_per_batch": args.sessions_per_batch,
        "max_ingest_sessions": args.max_ingest_sessions,
        "ingest_max_steps": args.ingest_max_steps,
        "probe_max_steps": args.probe_max_steps,
        "probe_concurrency": args.probe_concurrency,
        "probe_max_tokens": args.probe_max_tokens,
        "baseline_context_chars": args.baseline_context_chars,
        "limit": args.limit,
    }


def _build_cost(baseline_probe_tokens: dict, compressed_data: dict | None) -> dict:
    """Aggregate end-to-end token cost (main LLM + compression LLM) per arm.

    Baseline arm has zero compression cost since compression is disabled in its
    probe-only runs. The compressed arm sums ingest main-LLM tokens, probe
    main-LLM tokens, and the compression LLM tokens reported by the shared
    ContextManager.
    """
    base_main_in = baseline_probe_tokens.get("main_input_tokens", 0)
    base_main_out = baseline_probe_tokens.get("main_output_tokens", 0)
    baseline = {
        "main_input_tokens": base_main_in,
        "main_output_tokens": base_main_out,
        "compression_input_tokens": 0,
        "compression_output_tokens": 0,
        "total_input_tokens": base_main_in,
        "total_output_tokens": base_main_out,
        "total_tokens": base_main_in + base_main_out,
    }

    if compressed_data is None:
        return {"baseline": baseline, "compressed": None, "ratio": None}

    comp = compressed_data["compression"]
    cm_stats = comp.get("cm_stats") or {}
    probe = compressed_data.get("probe_tokens") or {}

    comp_main_in = comp.get("ingest_main_input_tokens", 0) + probe.get("main_input_tokens", 0)
    comp_main_out = comp.get("ingest_main_output_tokens", 0) + probe.get("main_output_tokens", 0)
    comp_cmp_in = cm_stats.get("total_input_tokens", 0) or 0
    comp_cmp_out = cm_stats.get("total_output_tokens", 0) or 0
    compressed = {
        "main_input_tokens": comp_main_in,
        "main_output_tokens": comp_main_out,
        "compression_input_tokens": comp_cmp_in,
        "compression_output_tokens": comp_cmp_out,
        "ingest_main_input_tokens": comp.get("ingest_main_input_tokens", 0),
        "ingest_main_output_tokens": comp.get("ingest_main_output_tokens", 0),
        "probe_main_input_tokens": probe.get("main_input_tokens", 0),
        "probe_main_output_tokens": probe.get("main_output_tokens", 0),
        "compression_calls": cm_stats.get("total_calls", 0),
        "total_input_tokens": comp_main_in + comp_cmp_in,
        "total_output_tokens": comp_main_out + comp_cmp_out,
        "total_tokens": comp_main_in + comp_main_out + comp_cmp_in + comp_cmp_out,
    }

    def _ratio(c: int, b: int):
        return (c / b) if b > 0 else None

    ratio = {
        "input": _ratio(compressed["total_input_tokens"], baseline["total_input_tokens"]),
        "output": _ratio(compressed["total_output_tokens"], baseline["total_output_tokens"]),
        "total": _ratio(compressed["total_tokens"], baseline["total_tokens"]),
    }
    return {"baseline": baseline, "compressed": compressed, "ratio": ratio}


def _category_accuracy(rows: list[dict]) -> dict[str, dict]:
    """Bucket scores by question_type and return per-category {n, accuracy}."""
    bucket: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        bucket[r["question_type"]].append(r["score"])
    out: dict[str, dict] = {}
    for qt, scores in bucket.items():
        out[qt] = {
            "n": len(scores),
            "accuracy": sum(scores) / len(scores) if scores else 0.0,
        }
    return out


async def run_dialogue(dialogue: LongMemEvalDialogue, args) -> dict:
    """Run baseline + compressed arms for one LongMemEval dialogue."""
    items = dialogue.items[:args.limit] if args.limit else dialogue.items
    print(f"\n===== DIALOGUE: {dialogue.dialogue_id} =====")
    print(f"  ctx_chars={len(dialogue.context)}  sessions={len(dialogue.sessions)}  "
          f"questions={len(items)}")

    # ---- Compressed arm ----
    compressed_data = None
    if not args.skip_compressed:
        cm_config = ContextManagerConfig(
            enabled=True,
            token_threshold=args.token_threshold,
            keep_recent_pairs=args.keep_recent_pairs,
            keep_recent_steps=args.keep_recent_steps,
            max_observation_length=args.max_observation_length,
        )
        # Override with multi-topic schema if requested
        if args.summary_schema == "multi_topic":
            build_multi_topic_config(cm_config)
            schema_label = "multi_topic"
        else:
            schema_label = "default"
        print(f"  [compressed:{schema_label}] ingesting "
              f"(sessions_per_batch={args.sessions_per_batch}, "
              f"threshold={args.token_threshold}) ...")
        compression = await ingest_and_compress(dialogue, cm_config, args)
        boundary = compression["cm_summary"].get("compression_boundary", {})
        print(f"  [compressed:{schema_label}] {compression['num_batches']} batches, "
              f"{compression['num_pairs']} pairs ingested, "
              f"compressed_pairs={boundary.get('previous_compressed_pairs', 0)}")

        precompressed_history = build_precompressed_history(
            compression["conversation_history"], compression["cm_summary"]
        )
        print(f"  [compressed:{schema_label}] running {len(items)} probes ...")
        compressed_results, compressed_probe_tokens = await run_probes(
            items, precompressed_history, args
        )
        compressed_data = {
            "results": compressed_results,
            "compression": compression,
            "schema": schema_label,
            "probe_tokens": compressed_probe_tokens,
        }

    # ---- Baseline arm ----
    baseline_results: list[dict] = []
    baseline_probe_tokens = {"main_input_tokens": 0, "main_output_tokens": 0}
    if not args.skip_baseline:
        truncated = dialogue.context[:args.baseline_context_chars]
        baseline_history = [
            AgentHistory(
                role="user",
                content=(
                    "Here is the full multi-session chat history between you and "
                    "the user (it may be truncated):\n\n" + truncated
                ),
            ),
            AgentHistory(role="assistant", content="OK, I have read it."),
        ]
        print(f"  [baseline] context truncated to {len(truncated)} chars, "
              f"running {len(items)} probes ...")
        baseline_results, baseline_probe_tokens = await run_probes(
            items, baseline_history, args
        )

    # ---- Metrics ----
    def accuracy(rows: list[dict]) -> float:
        return sum(r["score"] for r in rows) / len(rows) if rows else 0.0

    baseline_acc = accuracy(baseline_results)
    compressed_acc = accuracy(compressed_data["results"]) if compressed_data else 0.0
    memory_retention = None
    if baseline_results and compressed_data:
        memory_retention = (compressed_acc / baseline_acc) if baseline_acc > 0 else 0.0

    token_reduction = None
    if compressed_data and compressed_data["compression"]["token_counts"]:
        tc = compressed_data["compression"]["token_counts"]
        unc = tc.get("last_uncompressed") or 0
        comp = tc.get("last_compressed") or 0
        if unc > 0:
            token_reduction = 1 - comp / unc

    per_cat_baseline = _category_accuracy(baseline_results)
    per_cat_compressed = (
        _category_accuracy(compressed_data["results"]) if compressed_data else {}
    )

    # Per-category retention: compressed_acc / baseline_acc within each type.
    per_cat_retention: dict[str, dict] = {}
    all_types = set(per_cat_baseline) | set(per_cat_compressed)
    for qt in sorted(all_types):
        b = per_cat_baseline.get(qt, {}).get("accuracy")
        c = per_cat_compressed.get(qt, {}).get("accuracy")
        per_cat_retention[qt] = {
            "n": per_cat_baseline.get(qt, {}).get("n") or per_cat_compressed.get(qt, {}).get("n", 0),
            "baseline_accuracy": b,
            "compressed_accuracy": c,
            "memory_retention": (c / b) if (b is not None and c is not None and b > 0) else None,
        }

    cm_summary = compressed_data["compression"]["cm_summary"] if compressed_data else {}
    cost = _build_cost(baseline_probe_tokens, compressed_data)
    report = {
        "dialogue_id": dialogue.dialogue_id,
        "ctx_chars": len(dialogue.context),
        "num_sessions": len(dialogue.sessions),
        "num_questions": len(items),
        "summary_schema": compressed_data.get("schema", "none") if compressed_data else "none",
        "config": _build_run_config(args),
        "baseline": {"accuracy": baseline_acc, "n": len(baseline_results)},
        "compressed": (
            None if compressed_data is None else {
                "accuracy": compressed_acc,
                "n": len(compressed_data["results"]),
                "memory_retention": memory_retention,
                "token_reduction": token_reduction,
                "token_counts": compressed_data["compression"]["token_counts"],
                "num_batches": compressed_data["compression"]["num_batches"],
                "num_sessions_ingested": compressed_data["compression"]["num_sessions"],
                "compression_boundary": cm_summary.get("compression_boundary"),
                "previous_summary": cm_summary.get("previous_summary"),
            }
        ),
        "cost": cost,
        "per_category": per_cat_retention,
        "predictions": _merge_predictions(baseline_results, compressed_data),
    }

    line = (f"  RESULT: baseline_acc={_fmt(baseline_acc)}  "
            f"compressed_acc={_fmt(compressed_acc)}  "
            f"retention={_fmt(memory_retention)}  "
            f"token_reduction={_fmt(token_reduction)}  "
            f"schema={compressed_data.get('schema', 'none') if compressed_data else 'none'}")
    print(line)
    if cost.get("compressed") and cost.get("baseline"):
        b = cost["baseline"]["total_tokens"]
        c = cost["compressed"]["total_tokens"]
        r = cost["ratio"]["total"]
        print(f"  COST: baseline_total={b:,}  compressed_total={c:,} "
              f"(main={cost['compressed']['main_input_tokens'] + cost['compressed']['main_output_tokens']:,} "
              f"+ compression={cost['compressed']['compression_input_tokens'] + cost['compressed']['compression_output_tokens']:,})  "
              f"ratio={_fmt(r)}")
    return report


def _merge_predictions(baseline_results: list[dict],
                       compressed_data: dict) -> list[dict]:
    """Join baseline and compressed predictions by qid."""
    by_qid: dict[str, dict] = {}

    def _row(r: dict) -> dict:
        return {
            "answer": r["answer"],
            "correct": r["correct"],
            "judge_label": r["judge_label"],
        }

    for r in baseline_results:
        entry = by_qid.setdefault(r["qid"], {
            "qid": r["qid"], "question_type": r["question_type"], "gold": r["gold"],
        })
        entry["baseline"] = _row(r)
    if compressed_data:
        for r in compressed_data["results"]:
            entry = by_qid.setdefault(r["qid"], {
                "qid": r["qid"], "question_type": r["question_type"], "gold": r["gold"],
            })
            entry["compressed"] = _row(r)
    return list(by_qid.values())


# ============ Main ============

async def main(args):
    data_path = args.data_file
    if not os.path.isabs(data_path):
        data_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), data_path)
    if not os.path.exists(data_path):
        print(f"ERROR: data file not found: {data_path}")
        print("  Run 'python download_data.py' first.")
        return

    dialogues = load_dialogues(data_path)
    if args.dialogue_index is not None:
        dialogues = [dialogues[args.dialogue_index]]
    elif args.dialogue_limit:
        dialogues = dialogues[:args.dialogue_limit]

    outputs_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
    os.makedirs(outputs_root, exist_ok=True)

    print(f"{'=' * 60}")
    print(f"LongMemEval (S*) Benchmark (nexent agent)")
    print(f"{'=' * 60}")
    print(f"  Dialogues:               {len(dialogues)}")
    print(f"  Questions per dialogue:  {args.limit if args.limit else 'all (60)'}")
    print(f"  Token threshold:         {args.token_threshold}")
    print(f"  Sessions per batch:      {args.sessions_per_batch}")
    print(f"  Keep recent pairs:       {args.keep_recent_pairs}")
    print(f"  Summary schema:          {args.summary_schema}")
    print(f"  Baseline ctx chars:      {args.baseline_context_chars}")
    print(f"  Max ingest sessions:     {args.max_ingest_sessions or 'full'}")
    print(f"  Judge:                   {'dedicated JUDGE_*' if judge_configured() else 'main LLM_*'}")
    print(f"{'=' * 60}")

    reports = []
    for dialogue in dialogues:
        report = await run_dialogue(dialogue, args)
        reports.append(report)

        d_dir = os.path.join(outputs_root, dialogue.dialogue_id)
        os.makedirs(d_dir, exist_ok=True)
        with open(os.path.join(d_dir, "predictions.jsonl"), "w", encoding="utf-8") as f:
            for pred in report["predictions"]:
                f.write(json.dumps(pred, ensure_ascii=False) + "\n")
        d_summary = {k: v for k, v in report.items() if k != "predictions"}
        with open(os.path.join(d_dir, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(d_summary, f, ensure_ascii=False, indent=2, default=str)

    # ---- Cross-dialogue aggregate ----
    def _avg(values):
        vals = [v for v in values if v is not None]
        return sum(vals) / len(vals) if vals else None

    overall_baseline = _avg([r["baseline"]["accuracy"] for r in reports])
    overall_compressed = _avg([
        r["compressed"]["accuracy"] for r in reports if r["compressed"]
    ])
    overall_retention = _avg([
        r["compressed"]["memory_retention"] for r in reports if r["compressed"]
    ])
    overall_token_red = _avg([
        r["compressed"]["token_reduction"] for r in reports if r["compressed"]
    ])

    # Cross-dialogue per-category aggregate.
    per_cat_agg: dict[str, dict] = {}
    all_types: set[str] = set()
    for r in reports:
        all_types.update(r["per_category"].keys())
    for qt in sorted(all_types):
        baseline_vals = [r["per_category"][qt]["baseline_accuracy"]
                         for r in reports if qt in r["per_category"]
                         and r["per_category"][qt]["baseline_accuracy"] is not None]
        compressed_vals = [r["per_category"][qt]["compressed_accuracy"]
                           for r in reports if qt in r["per_category"]
                           and r["per_category"][qt]["compressed_accuracy"] is not None]
        retention_vals = [r["per_category"][qt]["memory_retention"]
                          for r in reports if qt in r["per_category"]
                          and r["per_category"][qt]["memory_retention"] is not None]
        per_cat_agg[qt] = {
            "avg_baseline_accuracy": _avg(baseline_vals),
            "avg_compressed_accuracy": _avg(compressed_vals),
            "avg_memory_retention": _avg(retention_vals),
        }

    # Cross-dialogue cost aggregate: sum absolute tokens across dialogues so
    # the top-level number reflects the full benchmark wallet, not an average.
    cost_agg = _aggregate_costs([r.get("cost") for r in reports])

    summary = {
        "total_dialogues": len(reports),
        "questions_per_dialogue": args.limit if args.limit else 60,
        "summary_schema": args.summary_schema,
        "config": _build_run_config(args),
        "judge": "JUDGE_*" if judge_configured() else "LLM_*",
        "avg_baseline_accuracy": overall_baseline,
        "avg_compressed_accuracy": overall_compressed,
        "avg_memory_retention": overall_retention,
        "avg_token_reduction": overall_token_red,
        "cost": cost_agg,
        "per_category": per_cat_agg,
        "per_dialogue": {
            r["dialogue_id"]: {
                "baseline_accuracy": r["baseline"]["accuracy"],
                "compressed": (
                    None if r["compressed"] is None else {
                        "accuracy": r["compressed"]["accuracy"],
                        "memory_retention": r["compressed"]["memory_retention"],
                        "token_reduction": r["compressed"]["token_reduction"],
                    }
                ),
                "cost": r.get("cost"),
            }
            for r in reports
        },
    }
    summary_name = (
        f"summary_{args.dialogue_index}.json"
        if args.dialogue_index is not None
        else "summary.json"
    )
    summary_path = os.path.join(outputs_root, summary_name)
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n{'=' * 60}")
    print(f"LongMemEval finished. {len(reports)} dialogue(s).")
    print(f"  avg baseline accuracy:   {_fmt(overall_baseline)}")
    print(f"  avg compressed accuracy: {_fmt(overall_compressed)}")
    print(f"  avg memory_retention:    {_fmt(overall_retention)}")
    print(f"  avg token_reduction:     {_fmt(overall_token_red)}")
    print(f"  per-category:")
    for qt, m in per_cat_agg.items():
        print(f"    {qt:<28} baseline={_fmt(m['avg_baseline_accuracy'])}  "
              f"compressed={_fmt(m['avg_compressed_accuracy'])}  "
              f"retention={_fmt(m['avg_memory_retention'])}")
    if cost_agg.get("compressed") and cost_agg["baseline"]["total_tokens"]:
        b = cost_agg["baseline"]
        c = cost_agg["compressed"]
        print(f"  cost (sum across dialogues):")
        print(f"    baseline    main={b['main_input_tokens']:>12,} in / {b['main_output_tokens']:>10,} out  total={b['total_tokens']:,}")
        print(f"    compressed  main={c['main_input_tokens']:>12,} in / {c['main_output_tokens']:>10,} out  "
              f"compression={c['compression_input_tokens']:,} in / {c['compression_output_tokens']:,} out  total={c['total_tokens']:,}")
        print(f"    ratio       input={_fmt(cost_agg['ratio']['input'])}  "
              f"output={_fmt(cost_agg['ratio']['output'])}  total={_fmt(cost_agg['ratio']['total'])}")
    print(f"  Summary saved to {summary_path}")
    print(f"{'=' * 60}")


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run the LongMemEval (S*) benchmark")
    p.add_argument("--data_file", type=str, default="data/longmemeval_s_star.jsonl")
    p.add_argument("--dialogue_limit", type=int, default=None,
                   help="Run only first N dialogues (default: all 5)")
    p.add_argument("--dialogue_index", type=int, default=None,
                   help="Run only the dialogue at this index (0-4); overrides --dialogue_limit")
    p.add_argument("--limit", type=int, default=60,
                   help="Questions per dialogue (default 60 — full; set lower for sampling)")
    p.add_argument("--summary_schema", type=str, default="default",
                   choices=["default", "multi_topic"],
                   help="Summary schema: 'default' (active_task) or 'multi_topic' (preserve all topics)")
    # ContextManager
    p.add_argument("--token_threshold", type=int, default=12000)
    p.add_argument("--keep_recent_pairs", type=int, default=2,
                   help="Recent (user, assistant) pairs preserved uncompressed "
                        "(default 2 — matches SDK ContextManagerConfig). "
                        "Larger values keep more raw turns out of compression — "
                        "e.g. 4 is a safer choice when probes ask about the "
                        "MOST RECENT session, but inflates last_compressed tokens.")
    p.add_argument("--keep_recent_steps", type=int, default=4)
    p.add_argument("--max_observation_length", type=int, default=20000)
    # Ingest shaping
    p.add_argument("--sessions_per_batch", type=int, default=4,
                   help="How many haystack sessions to ingest per agent run "
                        "(higher = fewer compression rounds, larger inputs)")
    p.add_argument("--max_ingest_sessions", type=int, default=0,
                   help="Cap ingested sessions (0 = full ~111 sessions; "
                        "small value for smoke tests)")
    p.add_argument("--ingest_max_steps", type=int, default=2)
    p.add_argument("--probe_max_steps", type=int, default=3)
    p.add_argument("--probe_concurrency", type=int, default=5,
                   help="Bounded asyncio concurrency for probe LLM calls "
                        "(default 5; set 1 for serial). Only affects probes — "
                        "ingest stays serial since compressions are ordered.")
    p.add_argument("--probe_max_tokens", type=int, default=4096,
                   help="Per-call completion output cap for probe LLM calls "
                        "(default 4096 — matches SDK production default). "
                        "Lower to 1024-2048 for tighter loop containment.")
    # Baseline
    p.add_argument("--baseline_context_chars", type=int, default=480000,
                   help="Characters of the dialogue fed to the baseline arm")
    # Arm selection
    p.add_argument("--skip_baseline", action="store_true")
    p.add_argument("--skip_compressed", action="store_true")
    p.add_argument("--debug", action="store_true")
    return p


if __name__ == "__main__":
    asyncio.run(main(_build_arg_parser().parse_args()))
