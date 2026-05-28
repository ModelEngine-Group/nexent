#!/usr/bin/env python3
"""Run the EventQA benchmark with the nexent agent.

EventQA (MemoryAgentBench) gives a full novel plus 100 six-choice
"what happens next" questions. This benchmark keeps the same evaluation method
and dimensions as the rest of ``sdk/benchmark`` — a baseline vs compressed
comparison — but adapted to a long-document memory task:

  * Baseline   — the novel is truncated to the model's context window and fed
                 whole, with NO compression. Questions about events past the
                 truncation point are expected to fail.
  * Compressed — the FULL novel is streamed in as a growing conversation
                 history; the real ContextManager incrementally compresses it.
                 The 100 questions are then run as memory probes against the
                 pre-compressed context.

Both arms answer the SAME 100 questions, so the retention ratio is clean:

    memory_retention = compressed_accuracy / baseline_accuracy
    token_reduction  = 1 - last_compressed_tokens / last_uncompressed_tokens

Continuation is not measured — EventQA questions are independent MCQs.

Usage:
    python download_data.py            # one-time: fetch the 5 novels
    python run_eventqa.py --limit 5 --book_limit 1 --max_ingest_chars 120000
    python run_eventqa.py              # full run: 5 books x 100 questions

Results are written to outputs/<book_id>/ and outputs/summary.json.
"""
import argparse
import asyncio
import copy
import json
import os
import sys

# ---- Path setup (mirrors acon_eval/run_acon_qa.py) ----
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

from dataset import load_books, EventQABook
from eval_utils import score_mcq


# ============ Agent duty prompts ============

INGEST_DUTY = (
    "You are reading a long novel one part at a time. Each message gives you "
    "the next part of the novel. Read it carefully and remember the events, "
    "the characters, and the order in which things happen. Do not analyze, "
    "review, or summarize the text. Simply acknowledge that you have read it "
    "by calling final_answer with the single word: OK"
)

PROBE_DUTY = (
    "You are answering a six-choice question about a novel. The novel — or a "
    "compressed summary of it — has been provided to you as earlier context. "
    "The question states the events that have already occurred and then lists "
    "six candidate events that might happen next. Exactly one of the six is "
    "the true continuation from the novel; the other five are "
    "plausible-sounding distractors.\n"
    "Rules:\n"
    "- You MUST choose exactly one of the six options. Choosing one is "
    "mandatory even when none seems certain — pick the most likely.\n"
    "- Never reply that none of the events occur, and never put your "
    "reasoning into the answer.\n"
    "- Answer in a SINGLE step. Your first and only code block must call "
    "final_answer directly. Do NOT first write a bare string, a print, or "
    "any inspection code — a bare string is NOT an answer and wastes a step.\n"
    "- Emit exactly one code block of this form, with the chosen option's "
    "text copied verbatim from the candidate list:\n"
    '<code>\nfinal_answer("<exact text of the option you choose>")\n</code>'
)


# ============ Summary schemas for the compressed arm ============
# The compressed arm can use either schema; `--summary_schema both` runs each.
#
#   default   — the production ContextManager schema (agent-task oriented:
#               active_task / completed_work / relevant_files ...). On a novel
#               most fields collapse to "None" and the plot is squeezed into a
#               single capped field.
#   narrative — the novel-oriented schema below. Still the real ContextManager
#               class and the same incremental-compression code path; only the
#               summary template (prompts + JSON schema) differs.

NARRATIVE_SUMMARY_SYSTEM_PROMPT = (
    "You are summarizing a novel that is being read in sequential parts. "
    "Treat the text below as the novel's own content — it is a story, NOT a "
    "task, a conversation, or a document the user is asking you to review. "
    "Produce only the structured JSON summary; no greeting, preamble, or prefix. "
    "Write the summary in the same language as the novel. "
    "Your goal is to preserve the STORY so that someone who reads only your "
    "summary could still answer 'what happens next' questions: keep the "
    "sequence of events, which character did what, and the order things happen. "
    "Be CONCRETE — name characters, places, and specific actions, and preserve "
    "chronological order. Avoid vague phrases like 'various events occur'. "
    "Output strict JSON format without markdown blocks."
)

NARRATIVE_INCREMENTAL_SUMMARY_SYSTEM_PROMPT = (
    "You are maintaining a running summary of a novel that is being read in "
    "sequential parts. The text below shows the existing summary as 'Previous "
    "Summary' and the next part of the novel as 'New Content'. Treat the new "
    "content as story text, NOT as a task or conversation. "
    "Update the summary by these rules:\n"
    "1. PRESERVE earlier events — do not drop plot points just because they "
    "are old. When space runs short, compress older events into briefer "
    "mentions rather than deleting them outright.\n"
    "2. ADD the new events to 'events_so_far', continuing the chronological order.\n"
    "3. UPDATE 'characters' with newly introduced characters and changes to known ones.\n"
    "4. UPDATE 'recent_events' to describe the latest part in finer detail.\n"
    "5. UPDATE 'unresolved_threads' and 'setting'.\n"
    "Write in the novel's language. Output strict JSON format without markdown blocks."
)

NARRATIVE_SUMMARY_SCHEMA = {
    "events_so_far": (
        "THE MOST IMPORTANT FIELD. A numbered, chronological list of the plot "
        "events from the start of the novel up to now. Each entry: which "
        "character did what, and where. Be concrete and specific — this field "
        "is what a reader uses to judge what happens next. (<=600 words)"
    ),
    "characters": (
        "Key characters and their roles, relationships, and current "
        "situation. (<=250 words)"
    ),
    "recent_events": (
        "The events of the most recent part, in finer detail than the older "
        "entries, for continuity with what comes next. (<=200 words)"
    ),
    "unresolved_threads": (
        "Open plot threads, conflicts, and questions not yet resolved. (<=150 words)"
    ),
    "setting": "Time period, places, and overall context of the story. (<=80 words)",
}


def build_compressed_config(schema_name: str, args) -> ContextManagerConfig:
    """Build the compressed-arm ContextManagerConfig for a given summary schema.

    For 'narrative', only the three summary-template fields are overridden; the
    rest of the ContextManager (incremental compression, caching, boundaries)
    is untouched — it is still the real production compression path.
    """
    config = ContextManagerConfig(
        enabled=True,
        token_threshold=args.token_threshold,
        keep_recent_pairs=args.keep_recent_pairs,
        keep_recent_steps=args.keep_recent_steps,
        max_observation_length=args.max_observation_length,
    )
    if schema_name == "narrative":
        config.summary_system_prompt = NARRATIVE_SUMMARY_SYSTEM_PROMPT
        config.incremental_summary_system_prompt = NARRATIVE_INCREMENTAL_SUMMARY_SYSTEM_PROMPT
        config.summary_json_schema = NARRATIVE_SUMMARY_SCHEMA
    return config


def resolve_schemas(arg: str) -> list[str]:
    """Map the --summary_schema argument to the list of schemas to run."""
    return ["default", "narrative"] if arg == "both" else [arg]


def _fmt(x) -> str:
    """Format a possibly-None metric for console output."""
    return "n/a" if x is None else f"{x:.3f}"


# ============ Pre-compressed history builder ============
# Copied from manual_cases/test_benchmark.py:build_precompressed_history so this
# directory stays self-contained (acon_eval follows the same self-contained
# pattern). It must mirror the message structure produced by
# ContextManager.compress_if_needed → SummaryTaskStep.to_messages().

def build_precompressed_history(
    frozen_history: list[AgentHistory],
    cm_summary: dict,
) -> list[AgentHistory]:
    """Build a pre-compressed history from a compression snapshot.

    Replaces the compressed prefix pairs with a single user message holding the
    summary text, then appends the retained tail pairs verbatim. If no
    compression happened, the original history is returned unchanged.
    """
    boundary = cm_summary.get("compression_boundary", {})
    compressed_pairs = boundary.get("previous_compressed_pairs", 0)
    compressed_entries = compressed_pairs * 2  # each pair = user + assistant

    summary_text = cm_summary.get("previous_summary") or ""
    if not summary_text or compressed_entries == 0:
        return list(frozen_history)

    precompressed = [
        AgentHistory(
            role="user",
            content=f"Summary of earlier steps in this task:\n{summary_text}",
        ),
    ]
    if compressed_entries < len(frozen_history):
        precompressed.extend(frozen_history[compressed_entries:])
    return precompressed


# ============ Novel chunking ============

def chunk_text(text: str, chunk_chars: int) -> list[str]:
    """Split text into chunks of about ``chunk_chars`` characters.

    Chunk boundaries are nudged forward to the next newline (within a small
    slack) so chunks do not cut sentences in half.
    """
    chunks: list[str] = []
    i, n = 0, len(text)
    while i < n:
        end = min(i + chunk_chars, n)
        if end < n:
            nl = text.find("\n", end)
            if nl != -1 and nl - end < 500:
                end = nl + 1
        chunks.append(text[i:end])
        i = end
    return chunks


# ============ Compressed arm: ingest + compress ============

async def ingest_and_compress(book: EventQABook, cm_config: ContextManagerConfig, args) -> dict:
    """Stream the novel into a growing history and let ContextManager compress.

    Returns a dict with the compression summary export, the accumulated
    conversation history, the last token counts, and compression stats.
    """
    context = book.context
    if args.max_ingest_chars > 0:
        context = context[:args.max_ingest_chars]

    chunks = chunk_text(context, args.chunk_chars)
    shared_cm = ContextManager(config=cm_config, max_steps=args.ingest_max_steps)

    conversation_history: list[AgentHistory] = []
    token_counts = None
    ingest_main_input_tokens = 0
    ingest_main_output_tokens = 0

    for idx, chunk in enumerate(chunks):
        chunk_msg = f"[Novel part {idx + 1} of {len(chunks)}]\n\n{chunk}"
        # The agent only exists to drive a real ContextManager compression pass
        # over the accumulated history. Showing the exact acknowledgement code
        # keeps a code-agent from misfiring on a bare "OK".
        query = (
            f"{chunk_msg}\n\n"
            f"You have now read this part of the novel. Acknowledge it by "
            f"emitting exactly this code and nothing else:\n"
            f'<code>\nfinal_answer("OK")\n</code>'
        )
        run_info = build_agent_run_info(
            query,
            conversation_history,
            duty_prompt=INGEST_DUTY,
            max_steps=args.ingest_max_steps,
            context_manager_config=cm_config,
            language="en",
            agent_name="eventqa_reader",
            agent_description="EventQA novel-reading agent",
        )
        run_info.context_manager = shared_cm

        chunk_result = await run_agent_with_tracking(run_info, debug=args.debug)
        ingest_main_input_tokens += chunk_result.total_input_tokens
        ingest_main_output_tokens += chunk_result.total_output_tokens
        token_counts = shared_cm.get_token_counts()

        # Store a clean (chunk, ack) pair. The agent's own reply carries no
        # information and may be malformed, so a fixed "OK" is used instead.
        conversation_history.append(AgentHistory(role="user", content=chunk_msg))
        conversation_history.append(AgentHistory(role="assistant", content="OK"))

    return {
        "cm_summary": shared_cm.export_summary(),
        "conversation_history": conversation_history,
        "token_counts": token_counts,
        "cm_stats": shared_cm.get_all_compression_stats(),
        "num_chunks": len(chunks),
        "ingest_chars": len(context),
        "ingest_main_input_tokens": ingest_main_input_tokens,
        "ingest_main_output_tokens": ingest_main_output_tokens,
    }


# ============ Probe runner (shared by both arms) ============

async def run_probes(items, history: list[AgentHistory], args) -> tuple[list[dict], dict]:
    """Run each EventQA question against a frozen history snapshot.

    Compression is disabled — the history is already in its final form
    (pre-compressed summary, or truncated novel). Each probe gets its own
    deep copy and runs fully independently, so we can fan them out under
    a bounded semaphore (--probe_concurrency). Result order is preserved
    via asyncio.gather and matches the items order.

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
                agent_name="eventqa_answerer",
                agent_description="EventQA multiple-choice answering agent",
                max_tokens=args.probe_max_tokens,
            )
            result = await run_agent_with_tracking(run_info, debug=args.debug)
            mcq = score_mcq(result.final_answer, it.options, it.gold)
            return {
                "qid": it.qid,
                "answer": result.final_answer,
                "selected_index": mcq.selected_index,
                "selected": mcq.selected,
                "gold": it.gold,
                "gold_index": mcq.gold_index,
                "correct": mcq.correct,
                "score": mcq.score,
                "match_type": mcq.match_type,
                "_main_input_tokens": result.total_input_tokens,
                "_main_output_tokens": result.total_output_tokens,
            }

    rows = await asyncio.gather(*(_one(it) for it in items))
    totals = {
        "main_input_tokens": sum(r.pop("_main_input_tokens", 0) for r in rows),
        "main_output_tokens": sum(r.pop("_main_output_tokens", 0) for r in rows),
    }
    return rows, totals


# ============ Per-book run ============

async def run_book(book: EventQABook, args) -> dict:
    """Run the baseline arm plus one compressed arm per summary schema."""
    # --question_start lets a salvaged / resumed run skip already-done qids.
    start = max(0, args.question_start)
    end = start + args.limit if args.limit else None
    items = book.items[start:end] if end is not None else book.items[start:]
    schemas = resolve_schemas(args.summary_schema)
    print(f"\n===== BOOK: {book.book_title} ({book.book_id}) =====")
    if start > 0:
        print(f"  novel chars={len(book.context)}  questions={len(items)} (qids {start}..{start+len(items)-1})")
    else:
        print(f"  novel chars={len(book.context)}  questions={len(items)}")

    # ---- Compressed arm(s): one ingest + probe pass per summary schema ----
    compressed: dict[str, dict] = {}
    if not args.skip_compressed:
        for schema_name in schemas:
            cm_config = build_compressed_config(schema_name, args)
            print(f"  [compressed:{schema_name}] ingesting novel "
                  f"(chunk_chars={args.chunk_chars}, threshold={args.token_threshold}) ...")
            compression = await ingest_and_compress(book, cm_config, args)
            boundary = compression["cm_summary"].get("compression_boundary", {})
            print(f"  [compressed:{schema_name}] {compression['num_chunks']} chunks "
                  f"ingested, compressed_pairs="
                  f"{boundary.get('previous_compressed_pairs', 0)}")

            precompressed_history = build_precompressed_history(
                compression["conversation_history"], compression["cm_summary"]
            )
            print(f"  [compressed:{schema_name}] running {len(items)} probes ...")
            results, probe_tokens = await run_probes(items, precompressed_history, args)
            compressed[schema_name] = {
                "results": results,
                "compression": compression,
                "probe_tokens": probe_tokens,
            }

    # ---- Baseline arm (schema-independent, runs once) ----
    baseline_results: list[dict] = []
    baseline_probe_tokens = {"main_input_tokens": 0, "main_output_tokens": 0}
    if not args.skip_baseline:
        truncated = book.context[:args.baseline_context_chars]
        baseline_history = [
            AgentHistory(
                role="user",
                content=f"Here is the novel (it may be truncated):\n\n{truncated}",
            ),
            AgentHistory(role="assistant", content="OK, I have read the novel."),
        ]
        print(f"  [baseline] novel truncated to {len(truncated)} chars, "
              f"running {len(items)} probes ...")
        baseline_results, baseline_probe_tokens = await run_probes(
            items, baseline_history, args
        )

    # ---- Metrics ----
    def accuracy(rows: list[dict]) -> float:
        return sum(r["score"] for r in rows) / len(rows) if rows else 0.0

    baseline_acc = accuracy(baseline_results)

    compressed_report: dict[str, dict] = {}
    for schema_name, data in compressed.items():
        c_acc = accuracy(data["results"])

        memory_retention = None
        if baseline_results and data["results"]:
            memory_retention = c_acc / baseline_acc if baseline_acc > 0 else 0.0

        token_reduction = None
        tc = data["compression"]["token_counts"]
        if tc:
            unc = tc.get("last_uncompressed") or 0
            comp = tc.get("last_compressed") or 0
            if unc > 0:
                token_reduction = 1 - comp / unc

        cm_summary = data["compression"]["cm_summary"]
        compressed_report[schema_name] = {
            "accuracy": c_acc,
            "n": len(data["results"]),
            "memory_retention": memory_retention,
            "token_reduction": token_reduction,
            "compression": {
                "token_counts": data["compression"]["token_counts"],
                "num_chunks": data["compression"]["num_chunks"],
                "ingest_chars": data["compression"]["ingest_chars"],
                "compression_boundary": cm_summary.get("compression_boundary"),
                "previous_summary": cm_summary.get("previous_summary"),
            },
        }

    cost = _build_cost(baseline_probe_tokens, compressed)
    report = {
        "book_id": book.book_id,
        "book_title": book.book_title,
        "novel_chars": len(book.context),
        "num_questions": len(items),
        "config": _build_run_config(args),
        "baseline": {"accuracy": baseline_acc, "n": len(baseline_results)},
        "compressed": compressed_report,
        "cost": cost,
        "predictions": _merge_predictions(baseline_results, compressed),
    }

    line = f"  RESULT: baseline_acc={_fmt(baseline_acc)}"
    for schema_name, c in compressed_report.items():
        line += (f"  |  {schema_name}: acc={_fmt(c['accuracy'])} "
                 f"retention={_fmt(c['memory_retention'])} "
                 f"token_reduction={_fmt(c['token_reduction'])}")
    print(line)
    base_total = cost["baseline"]["total_tokens"]
    if base_total and cost.get("compressed"):
        for schema_name, c in cost["compressed"].items():
            r = (cost.get("ratio") or {}).get(schema_name, {}).get("total")
            print(f"  COST[{schema_name}]: baseline_total={base_total:,}  "
                  f"compressed_total={c['total_tokens']:,} "
                  f"(main={c['main_input_tokens'] + c['main_output_tokens']:,} "
                  f"+ compression={c['compression_input_tokens'] + c['compression_output_tokens']:,})  "
                  f"ratio={_fmt(r)}")
    return report


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
        "summary_schemas": resolve_schemas(args.summary_schema),
        "chunk_chars": args.chunk_chars,
        "max_ingest_chars": args.max_ingest_chars,
        "ingest_max_steps": args.ingest_max_steps,
        "probe_max_steps": args.probe_max_steps,
        "probe_concurrency": args.probe_concurrency,
        "probe_max_tokens": args.probe_max_tokens,
        "baseline_context_chars": args.baseline_context_chars,
        "limit": args.limit,
        "question_start": args.question_start,
    }


def _build_cost(baseline_probe_tokens: dict, compressed: dict[str, dict]) -> dict:
    """Aggregate end-to-end token cost (main LLM + compression LLM) per arm.

    EventQA supports multiple schemas per book, so the compressed side is a
    dict keyed by ``schema_name``. Baseline arm has zero compression cost
    since compression is disabled in its probe-only runs.
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

    if not compressed:
        return {"baseline": baseline, "compressed": None, "ratio": None}

    def _ratio(c: int, b: int):
        return (c / b) if b > 0 else None

    compressed_costs: dict[str, dict] = {}
    ratios: dict[str, dict] = {}
    for schema_name, data in compressed.items():
        comp = data["compression"]
        cm_stats = comp.get("cm_stats") or {}
        probe = data.get("probe_tokens") or {}

        comp_main_in = comp.get("ingest_main_input_tokens", 0) + probe.get("main_input_tokens", 0)
        comp_main_out = comp.get("ingest_main_output_tokens", 0) + probe.get("main_output_tokens", 0)
        comp_cmp_in = cm_stats.get("total_input_tokens", 0) or 0
        comp_cmp_out = cm_stats.get("total_output_tokens", 0) or 0
        compressed_costs[schema_name] = {
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
        ratios[schema_name] = {
            "input": _ratio(compressed_costs[schema_name]["total_input_tokens"], baseline["total_input_tokens"]),
            "output": _ratio(compressed_costs[schema_name]["total_output_tokens"], baseline["total_output_tokens"]),
            "total": _ratio(compressed_costs[schema_name]["total_tokens"], baseline["total_tokens"]),
        }
    return {"baseline": baseline, "compressed": compressed_costs, "ratio": ratios}


def _aggregate_costs(costs: list[dict | None]) -> dict:
    """Sum per-arm token totals across books for the top-level summary.

    Compressed side is keyed by schema, so the aggregate is also keyed by
    schema; ratios are recomputed at the aggregate level from summed totals
    rather than averaged from per-book ratios.
    """
    base_keys = ["main_input_tokens", "main_output_tokens",
                 "compression_input_tokens", "compression_output_tokens",
                 "total_input_tokens", "total_output_tokens", "total_tokens"]
    comp_keys = base_keys + ["ingest_main_input_tokens", "ingest_main_output_tokens",
                             "probe_main_input_tokens", "probe_main_output_tokens",
                             "compression_calls"]
    baseline_agg = {k: 0 for k in base_keys}
    compressed_agg: dict[str, dict] = {}
    for c in costs:
        if not c:
            continue
        for k in base_keys:
            baseline_agg[k] += c.get("baseline", {}).get(k, 0) or 0
        for schema_name, sub in (c.get("compressed") or {}).items():
            slot = compressed_agg.setdefault(schema_name, {k: 0 for k in comp_keys})
            for k in comp_keys:
                slot[k] += sub.get(k, 0) or 0

    def _ratio(c: int, b: int):
        return (c / b) if b > 0 else None

    ratios: dict[str, dict] = {}
    for schema_name, sub in compressed_agg.items():
        ratios[schema_name] = {
            "input": _ratio(sub["total_input_tokens"], baseline_agg["total_input_tokens"]),
            "output": _ratio(sub["total_output_tokens"], baseline_agg["total_output_tokens"]),
            "total": _ratio(sub["total_tokens"], baseline_agg["total_tokens"]),
        }
    return {
        "baseline": baseline_agg,
        "compressed": compressed_agg or None,
        "ratio": ratios or None,
    }


def _merge_predictions(
    baseline_results: list[dict],
    compressed: dict[str, dict],
) -> list[dict]:
    """Join the baseline and per-schema compressed results by qid."""
    by_qid: dict[str, dict] = {}

    def _row(r: dict) -> dict:
        return {
            "answer": r["answer"], "selected": r["selected"],
            "correct": r["correct"], "match_type": r["match_type"],
        }

    for r in baseline_results:
        entry = by_qid.setdefault(r["qid"], {"qid": r["qid"], "gold": r["gold"]})
        entry["baseline"] = _row(r)
    for schema_name, data in compressed.items():
        for r in data["results"]:
            entry = by_qid.setdefault(r["qid"], {"qid": r["qid"], "gold": r["gold"]})
            entry.setdefault("compressed", {})[schema_name] = _row(r)
    return list(by_qid.values())


# ============ Main ============

async def main(args):
    data_path = args.data_file
    if not os.path.isabs(data_path):
        data_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), data_path)

    if not os.path.exists(data_path):
        print(f"ERROR: data file not found: {data_path}")
        print("  Run 'python download_data.py' first to fetch the EventQA novels.")
        return

    books = load_books(data_path)
    if args.book_index is not None:
        books = [books[args.book_index]]
    elif args.book_limit:
        books = books[:args.book_limit]

    outputs_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
    os.makedirs(outputs_root, exist_ok=True)

    schemas = resolve_schemas(args.summary_schema)

    print(f"{'=' * 60}")
    print(f"EventQA Benchmark (nexent agent)")
    print(f"{'=' * 60}")
    print(f"  Books:                 {len(books)}")
    print(f"  Questions per book:    {args.limit or 'all (100)'}")
    print(f"  Compressed schema(s):  {', '.join(schemas)}")
    print(f"  Token threshold:       {args.token_threshold}")
    print(f"  Chunk chars:           {args.chunk_chars}")
    print(f"  Baseline ctx chars:    {args.baseline_context_chars}")
    print(f"  Max ingest chars:      {args.max_ingest_chars or 'full novel'}")
    print(f"{'=' * 60}")

    reports = []
    for book in books:
        report = await run_book(book, args)
        reports.append(report)

        book_dir = os.path.join(outputs_root, book.book_id)
        os.makedirs(book_dir, exist_ok=True)
        with open(os.path.join(book_dir, "predictions.jsonl"), "w", encoding="utf-8") as f:
            for pred in report["predictions"]:
                f.write(json.dumps(pred, ensure_ascii=False) + "\n")
        book_summary = {k: v for k, v in report.items() if k != "predictions"}
        with open(os.path.join(book_dir, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(book_summary, f, ensure_ascii=False, indent=2, default=str)

    # ---- Cross-book aggregate ----
    def _avg(values):
        vals = [v for v in values if v is not None]
        return sum(vals) / len(vals) if vals else None

    per_schema = {}
    for schema_name in schemas:
        books_with = [r for r in reports if schema_name in r["compressed"]]
        if not books_with:
            continue
        per_schema[schema_name] = {
            "avg_compressed_accuracy": _avg(
                [r["compressed"][schema_name]["accuracy"] for r in books_with]),
            "avg_memory_retention": _avg(
                [r["compressed"][schema_name]["memory_retention"] for r in books_with]),
            "avg_token_reduction": _avg(
                [r["compressed"][schema_name]["token_reduction"] for r in books_with]),
        }

    # Cross-book cost aggregate: sum absolute tokens across books so the
    # top-level number reflects the full benchmark wallet, not an average.
    cost_agg = _aggregate_costs([r.get("cost") for r in reports])

    summary = {
        "total_books": len(reports),
        "questions_per_book": args.limit or 100,
        "summary_schemas": schemas,
        "config": _build_run_config(args),
        "avg_baseline_accuracy": _avg([r["baseline"]["accuracy"] for r in reports]),
        "per_schema": per_schema,
        "cost": cost_agg,
        "per_book": {
            r["book_id"]: {
                "book_title": r["book_title"],
                "baseline_accuracy": r["baseline"]["accuracy"],
                "compressed": {
                    s: {
                        "accuracy": c["accuracy"],
                        "memory_retention": c["memory_retention"],
                        "token_reduction": c["token_reduction"],
                    }
                    for s, c in r["compressed"].items()
                },
                "cost": r.get("cost"),
            }
            for r in reports
        },
    }
    summary_name = (
        f"summary_{args.book_index}.json"
        if args.book_index is not None
        else "summary.json"
    )
    summary_path = os.path.join(outputs_root, summary_name)
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n{'=' * 60}")
    print(f"EventQA finished. {len(reports)} book(s).")
    print(f"  avg baseline accuracy:   {_fmt(summary['avg_baseline_accuracy'])}")
    for schema_name, m in per_schema.items():
        print(f"  [compressed:{schema_name}] acc={_fmt(m['avg_compressed_accuracy'])}  "
              f"retention={_fmt(m['avg_memory_retention'])}  "
              f"token_reduction={_fmt(m['avg_token_reduction'])}")
    if cost_agg.get("compressed") and cost_agg["baseline"]["total_tokens"]:
        b = cost_agg["baseline"]
        print(f"  cost (sum across books):")
        print(f"    baseline    main={b['main_input_tokens']:>12,} in / {b['main_output_tokens']:>10,} out  total={b['total_tokens']:,}")
        for schema_name, c in cost_agg["compressed"].items():
            r = cost_agg["ratio"][schema_name]
            print(f"    compressed[{schema_name}]  main={c['main_input_tokens']:>12,} in / {c['main_output_tokens']:>10,} out  "
                  f"compression={c['compression_input_tokens']:,} in / {c['compression_output_tokens']:,} out  total={c['total_tokens']:,}")
            print(f"      ratio  input={_fmt(r['input'])}  output={_fmt(r['output'])}  total={_fmt(r['total'])}")
    print(f"  Summary saved to {summary_path}")
    print(f"{'=' * 60}")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the EventQA benchmark with the nexent agent")
    parser.add_argument("--data_file", type=str, default="data/eventqa_full.jsonl",
                        help="EventQA jsonl produced by download_data.py")
    parser.add_argument("--book_limit", type=int, default=None,
                        help="Limit number of books (default: all 5)")
    parser.add_argument("--book_index", type=int, default=None,
                        help="Evaluate only the book at this index (0-4); overrides --book_limit")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit questions per book (default: all 100)")
    parser.add_argument("--question_start", type=int, default=0,
                        help="Skip the first N questions (for resuming an interrupted run)")
    parser.add_argument("--token_threshold", type=int, default=12000,
                        help="ContextManager token threshold for the compressed arm")
    parser.add_argument("--keep_recent_pairs", type=int, default=2,
                        help="ContextManager keep_recent_pairs")
    parser.add_argument("--keep_recent_steps", type=int, default=4,
                        help="ContextManager keep_recent_steps")
    parser.add_argument("--max_observation_length", type=int, default=20000,
                        help="ContextManager max_observation_length")
    parser.add_argument("--summary_schema", type=str, default="default",
                        choices=["default", "narrative", "both"],
                        help="Summary template the compressed arm uses: 'default' "
                             "(production agent-task schema), 'narrative' "
                             "(novel-oriented schema), or 'both' (run each and compare)")
    parser.add_argument("--chunk_chars", type=int, default=20000,
                        help="Characters per novel chunk fed during ingest")
    parser.add_argument("--baseline_context_chars", type=int, default=480000,
                        help="Characters of the novel fed to the baseline arm "
                             "(truncate to the model's context window)")
    parser.add_argument("--max_ingest_chars", type=int, default=0,
                        help="Cap the novel length ingested in the compressed arm "
                             "(0 = full novel; use a small value for smoke tests)")
    parser.add_argument("--ingest_max_steps", type=int, default=2,
                        help="Max agent steps per ingest (acknowledge) run")
    parser.add_argument("--probe_max_steps", type=int, default=3,
                        help="Max agent steps for each question-answering probe")
    parser.add_argument("--probe_concurrency", type=int, default=5,
                        help="Bounded asyncio concurrency for probe LLM calls "
                             "(default 5; set 1 for serial). Only affects probes — "
                             "ingest stays serial since compressions are ordered.")
    parser.add_argument("--probe_max_tokens", type=int, default=4096,
                        help="Per-call completion output cap for probe LLM calls "
                             "(default 4096 — matches SDK production default). "
                             "Lower to 1024-2048 for tighter loop containment.")
    parser.add_argument("--skip_baseline", action="store_true",
                        help="Skip the baseline arm (compressed-only iteration)")
    parser.add_argument("--skip_compressed", action="store_true",
                        help="Skip the compressed arm (baseline-only iteration)")
    parser.add_argument("--debug", action="store_true", help="Enable agent debug output")
    return parser


if __name__ == "__main__":
    asyncio.run(main(_build_arg_parser().parse_args()))
