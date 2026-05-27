#!/usr/bin/env python3
"""Run ACON multi-objective QA benchmark with nexent agent.

Loads ACON's nq_multi_8 data, builds a nexent CoreAgent with
wikipedia_search + final_answer tools, evaluates with EM/F1 scoring.

Supports three modes:
  baseline        — no context compression
  context_manager — nexent's built-in ContextManager

Use --num_objectives to control how many sub-questions per sample
(e.g. --num_objectives 2 to use only the first 2 sub-questions).

Usage:
    # Start ACON retriever server first:
    #   cd acon/experiments/smolagents/search && python retriever_server.py
    #   (or download the corpus and start it per ACON README)

    python run_acon_qa.py \
        --data_folder data/nq_multi_8 \
        --split test \
        --mode baseline \
        --num_objectives 4 \
        --limit 5

Results saved to outputs/<mode>/<split>/summary.json + predictions.jsonl
"""
import argparse
import asyncio
import json
import os
import sys
import threading
from datetime import datetime
from typing import Optional

# ---- Path setup ----
# Robust path resolution via paths.py (.git discovery) — works regardless of file location
# 1. Add benchmark/ to sys.path so paths.py can be found
# 2. import paths triggers setup_paths() which adds sdk/, backend/ to sys.path
# 3. Add this directory for local module imports (dataset, eval_utils, tools)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths  # noqa: F401 — side-effect: adds sdk/, backend/ to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ---- Register ACON tools into nexent namespace before any agent creation ----
from tools import register_acon_tools, get_acon_tool_configs
register_acon_tools()

from dataset import QALoader
from eval_utils import exact_match, f1_max

from agent_runner import (
    build_agent_run_info_with_custom_prompt,
    run_agent_with_tracking,
    AgentRunResult,
    ContextManagerConfig,
)

from nexent.core.agents.agent_model import AgentHistory
from nexent.core.agents.agent_context import ContextManager


# ---- QA-specific system prompt builder ----

def build_qa_system_prompt(num_objectives: int) -> str:
    answer_slots = "; ".join(f"answer{i}" for i in range(1, num_objectives + 1))

    return f"""You are a multi-hop QA agent. The input contains multiple sub-questions separated by "; ".
Answer them sequentially by actually calling `wikipedia_search`, then call `final_answer`.

# Tools
- `wikipedia_search(query: str, n_results: int = 3)` — searches the local 2018 Wikipedia retriever.
- `final_answer(answer: str)` — submits the final answer.

# Mandatory Tool-Use Protocol
For every search, you must use a real code block:

<code>
result = wikipedia_search(query="...", n_results=3)
print(result)
</code>

Only an actual Observation produced after a `<code>` block counts as evidence.
Do not write fake Search/Result text.

# Core Rules
For each sub-question, in order:
1. Run one `wikipedia_search` call.
2. Read the actual Observation.
3. If the Observation clearly answers the sub-question, register the canonical answer and move to the next sub-question.
4. Do not run confirmation searches after finding a clear answer.
5. Use at most 3 searches per sub-question.
6. If the first 2 searches fail, the 3rd query must be broader and centered on the main entity/topic.
7. If 3 searches are exhausted, commit to the best candidate from observed results and move on.

# Anti-Loop & Exhaustion Rules (CRITICAL — overriding priority)
- Track the exact count of wikipedia_search calls for the current sub-question.
- When count reaches 3, STOP searching immediately. Output ANSWER_Q<number>: <your best inference from observed results> and move to the next question. No exceptions, no additional searches.
- If the last 2 searches returned completely irrelevant results (no mention of the target entity), the query angle is wrong. Do NOT search a third time with minor wording tweaks of the same query. Instead, search the main entity broadly (e.g. "Formula One history" instead of "chain F1"), or if already at 3, infer the best answer from any indirect clues in the observations and output ANSWER_Q<number>.
- Self-check: if you catch yourself writing "I'm not finding it", "Perhaps", "Let me search for" or similar frustration phrases, you have already done enough searching. Output ANSWER_Q<number> with your best inference immediately.
- After 3 searches, you already have your answer. Do NOT write "However", "But", "I'm not sure", "I'm not entirely sure", "Let me try one more", "Let me check directly", or any similar hesitation phrase. These words mean you have a candidate answer but are delaying. Output that candidate as ANSWER_Q<number> right now and move on. Uncertainty is expected and acceptable — your best guess IS the answer.
- If the conversation contains a user message starting with "Summary of earlier steps in this task:", that message is an authoritative checkpoint of your progress. Before each search, check its JSON fields: "status", "search_counts", "pending_q", "next_action". If pending_q is empty and next_action says to call final_answer, call final_answer immediately — do not search again. If a question is marked "exhausted" in the summary, do not search it further.

# Query Rules
- Prefer entity-focused queries, e.g. "Asha Bhosle Guinness", not "most prolific singer ever".
- Each query must be meaningfully different.
- Use `n_results=3` by default.

# Answer Rules
- Use concise canonical answers: Wikipedia-title-like names or one-line factual answers.
- Keep modifiers only when needed for correctness.
- Do not include explanations, citations, dates, chapter/verse references, or extra context.
- Final answers must be separated by "; " in the original sub-question order.

# Answer Registration — mandatory
Before moving from one question to the next, output exactly one plain-text marker:

ANSWER_Q<number>: <canonical answer>


JUST Examples:
ANSWER_Q1: Eva Lund
ANSWER_Q2: September 1980

Rules:
- The marker is plain text, not a code block.
- If an Observation clearly answers Q<number>, output `ANSWER_Q<number>: <canonical answer>`.
- After 3 searches, if there is any usable candidate in the Observations, output `ANSWER_Q<number>: <best canonical candidate>`.
- Never move to the next question without an ANSWER_Q marker for the current question.
- Use the registered ANSWER_Q markers to construct the final answer.

# Final Answer
Before calling `final_answer`, count your answers.
The final answer must contain exactly one answer per sub-question.
Never submit a partial answer.

Use a real code block:

<code>
final_answer(answer="{answer_slots}")
</code>

Start answering the real questions, starting with obtaining ANSWER_Q1.
"""

def _sanitize_for_path(name: str) -> str:
    return ''.join(ch if ch.isalnum() or ch in ('-', '_', '.') else '-' for ch in name)


async def run_sample(
    ex,
    max_steps: int,
    retriever_port: str,
    mode: str,
    cm_config: Optional[ContextManagerConfig],
    debug: bool,
    system_prompt: str,
) -> dict:
    """Run a single QA example through the nexent agent."""
    tools = get_acon_tool_configs(port=retriever_port)

    agent_run_info = build_agent_run_info_with_custom_prompt(
        query=ex.question,
        system_prompt=system_prompt,
        history=[],
        tools=tools,
        max_steps=max_steps,
        agent_name="acon_qa_agent",
        agent_description="ACON multi-objective QA agent",
        language="en",
        context_manager_config=cm_config,
        temperature=0
    )

    # Attach shared ContextManager if mode is context_manager
    shared_cm = None
    if mode == "context_manager" and cm_config and cm_config.enabled:
        shared_cm = ContextManager(config=cm_config, max_steps=max_steps)
        agent_run_info.context_manager = shared_cm

    result = await run_agent_with_tracking(agent_run_info, debug=debug)
    pred_raw = result.final_answer or ""

    # Score: split prediction by semicolons, compare to gold answer list
    pred_list = [p.strip() for p in pred_raw.split(";")]

    # Pad or truncate predictions to match number of gold sub-answers
    n_sub = len(ex.answer)
    while len(pred_list) < n_sub:
        pred_list.append("")
    pred_list = pred_list[:n_sub]

    em_list = [exact_match(p, a) for p, a in zip(pred_list, ex.answer)]
    f1_list = [f1_max(p, a) for p, a in zip(pred_list, ex.answer)]

    em_score = sum(em_list) / n_sub if n_sub else 0.0
    f1_score = sum(f1_list) / n_sub if n_sub else 0.0

    return {
        "pred_raw": pred_raw,
        "pred_list": pred_list,
        "em_score": em_score,
        "f1_score": f1_score,
        "em_list": em_list,
        "f1_list": f1_list,
        "step_count": result.step_count,
        "errors": result.errors,
        "total_input_tokens": result.total_input_tokens,
        "total_output_tokens": result.total_output_tokens,
        "cm_stats": shared_cm.get_all_compression_stats() if shared_cm else None,
        "cm_token_counts": shared_cm.get_token_counts() if shared_cm else None,
    }


async def main(
    data_folder: str,
    split: str,
    mode: str,
    max_steps: int,
    limit: Optional[int],
    retriever_port: str,
    token_threshold: int,
    keep_recent_pairs: int,
    keep_recent_steps: int,
    max_observation_length: int,
    debug: bool,
    output_dir: Optional[str],
    id_list_file: Optional[str],
    num_objectives: int,
):
    # Resolve data path
    split_key = (split or "test").lower()
    if split_key in {"dev", "validation", "val"}:
        split_key = "test"
    fname = "train.jsonl" if split_key == "train" else "test.jsonl"
    data_path = os.path.join(data_folder, fname)

    if not os.path.exists(data_path):
        print(f"ERROR: Data file not found: {data_path}")
        print(f"  Make sure to point --data_folder to ACON's nq_multi_8 directory,")
        print(f"  e.g., D:/path/to/acon/experiments/smolagents/data/nq_multi_8")
        return

    loader = QALoader(data_path)

    # Optional ID filtering
    filter_ids = None
    if id_list_file and os.path.exists(id_list_file):
        with open(id_list_file, "r", encoding="utf-8") as f:
            filter_ids = {line.strip() for line in f if line.strip() and not line.strip().startswith("#")}

    # Build iterator
    if filter_ids is not None:
        materialized = [ex for ex in loader.iter(limit=None) if ex.id in filter_ids]
        if limit is not None:
            materialized = materialized[:limit]
        iterator = materialized
        total_count = len(materialized)
    else:
        iterator = list(loader.iter(limit=limit))
        total_count = len(iterator)

    # Truncate sub-questions if num_objectives < 8
    if num_objectives < 8:
        for ex in iterator:
            q_parts = [q.strip() for q in ex.question.split(";")]
            ex.question = "; ".join(q_parts[:num_objectives])
            ex.answer = ex.answer[:num_objectives]

    # Build QA-specific system prompt with dynamic answer slots
    qa_system_prompt = build_qa_system_prompt(num_objectives)

    # ContextManager config based on mode
    cm_config = None
    if mode == "context_manager":
        # Custom summary JSON schema that emphasizes task progress tracking
        custom_summary_schema = {
            "n_questions": "Total number of sub-questions.",
            "answers": (
                "Ordered list of final-answer candidates. Length must equal n_questions. "
                "Each item is either an exact canonical answer string or 'Unknown'. "
            ),
            "status": (
                "Array of length n_questions. Each item must be one of: "
                "'unstarted', 'searching', 'answered', 'exhausted'. "
                "answered requires a non-null answer other than 'Unknown'. or null"
                "exhausted requires answer that need to be inferred."
            ),
            "search_counts": (
                "Array of integers of length n_questions. "
                "Count only actual wikipedia_search calls."
            ),
            "current_q": (
                "The 1-based index of the next question to solve. "
                "Usually the first index whose status is not 'answered' or 'exhausted'."
            ),
            "pending_q": (
                "List of question numbers whose status is 'unstarted' or 'searching'. "
                "Do not include answered or exhausted questions."
            ),
            "next_action": (
                "One direct mechanical next step. Example: "
                "'Run wikipedia_search for Q5: Ash Wednesday ashes palm leaves'."
            ),
        }
        # Custom summary system prompt that emphasizes multi-question task tracking
        custom_incremental_summary_system_prompt = (
            "Update the compact QA checkpoint based on the latest agent action. "
            "Output only strict JSON matching the schema. No markdown.\n\n"
            "Treat ANSWER_Q<number>: ... marker as authoritative; never replace with null or Unknown."
            "INCREMENTAL UPDATE RULES:\n"
            "- Preserve all answered values; never downgrade them to null or 'Unknown'.\n"
            "- If the latest action executed wikipedia_search, increment only that question's search_counts entry.\n"
            "- If the latest observation clearly answers the current question, write the canonical answer into answers and set status to 'answered'.\n"
            "- ENFORCEMENT: If any search_counts reaches >=3, its status MUST be 'exhausted' (NEVER 'searching'). "
            "Set its answer to the best observed candidate, or 'Unknown' if nothing was useful. "
            "An exhausted question must be REMOVED from pending_q.\n"
            "- current_q must advance past any exhausted question to the next unstarted/searching question.\n"
            "- If ALL questions are answered or exhausted, set next_action to 'Call final_answer with the collected answers'.\n"
            "- NEVER set next_action to search a question whose search_counts is already >=3.\n"
            "- Otherwise, leave answer as null and status as 'searching'.\n"
            "- pending_q must contain exactly the question numbers with status 'unstarted' or 'searching'.\n"
            "- Overwrite the old state completely. Do not append logs, snippets, or history."
        )

        custom_summary_system_prompt = (
            "You are creating a compact execution checkpoint for a sequential multi-question QA agent. "
            "Output only strict JSON matching the schema. No markdown, greetings, or backticks.\n\n"
            "Treat ANSWER_Q<number>: ... marker as authoritative; never replace an ANSWER_Q value with null or Unknown.\n"
            "STATE RULES:\n"
            "- Preserve exact canonical answer strings when explicitly available.\n"
            "- answers, status, and search_counts must all have length n_questions.\n"
            "- status must be consistent with answers and search_counts:\n"
            "  * unstarted => answer is null, search_counts is 0\n"
            "  * searching => answer is null, search_counts is 1 or 2\n"
            "  * answered => answer is non-null canonical string, search_counts is 1-3\n"
            "  * exhausted => search_counts is >=3, answer is best inference or 'Unknown'\n"
            "- A question with search_counts >=3 must have status 'exhausted', never 'searching'.\n"
            "- pending_q must contain exactly the question numbers with status 'unstarted' or 'searching'.\n"
            "- current_q should be the first question in pending_q.\n"
            "- If all questions are answered or exhausted, set next_action to 'Call final_answer'.\n\n"

            "COMPACTION RULES:\n"
            "- Strip raw search logs, snippets, long reasons, file status, and failed query history.\n"
            "- Count every wikipedia_search call visible in the trajectory for each question.\n"
            "- Keep the checkpoint short and stable. Do not append history."
        )
        cm_config = ContextManagerConfig(
            enabled=True,
            token_threshold=token_threshold,
            keep_recent_pairs=keep_recent_pairs,
            keep_recent_steps=keep_recent_steps,
            max_observation_length=max_observation_length,
            summary_json_schema=custom_summary_schema,
            summary_system_prompt=custom_summary_system_prompt,
            incremental_summary_system_prompt=custom_incremental_summary_system_prompt,
        )
    else:
        # baseline: no compression
        cm_config = ContextManagerConfig(enabled=False, token_threshold=10**9)

    # Output directory
    if output_dir is None:
        acon_eval_dir = os.path.dirname(os.path.abspath(__file__))
        outputs_root = os.path.join(acon_eval_dir, "outputs")
    else:
        outputs_root = output_dir

    mode_part = _sanitize_for_path(mode)
    split_part = _sanitize_for_path(split_key)
    out_dir = os.path.join(outputs_root, f"{mode_part}", split_part)
    os.makedirs(out_dir, exist_ok=True)

    print(f"\n{'='*60}")
    obj_label = f"{num_objectives}-Objective" if num_objectives != 8 else "8-Objective"
    print(f"ACON {obj_label} QA Evaluation (nexent agent)")
    print(f"{'='*60}")
    print(f"  Data:            {data_path}")
    print(f"  Split:           {split_key}")
    print(f"  Mode:            {mode}")
    print(f"  Num objectives:  {num_objectives}")
    print(f"  Max steps:       {max_steps}")
    print(f"  Limit:           {limit or 'all'}")
    print(f"  Total:           {total_count}")
    print(f"  Retriever:       127.0.0.1:{retriever_port}")
    if mode == "context_manager":
        print(f"  CM config:  threshold={token_threshold}, keep_recent_pairs={keep_recent_pairs}, "
              f"keep_recent_steps={keep_recent_steps}, max_obs_len={max_observation_length}")
    print(f"  Output:     {out_dir}")
    print(f"{'='*60}\n")

    n = 0
    em_sum = 0.0
    f1_sum = 0.0
    all_rows = []

    for ex in iterator:
        print(f"[{n+1}/{total_count}] {ex.id[:40]}...", end=" ", flush=True)

        try:
            sample_result = await run_sample(
                ex=ex,
                max_steps=max_steps,
                retriever_port=retriever_port,
                mode=mode,
                cm_config=cm_config,
                debug=debug,
                system_prompt=qa_system_prompt,
            )
            em_score = sample_result["em_score"]
            f1_score = sample_result["f1_score"]
            print(f"EM={em_score:.2f} F1={f1_score:.2f} steps={sample_result['step_count']}")
        except Exception as e:
            print(f"ERROR: {e}")
            em_score = 0.0
            f1_score = 0.0
            sample_result = {
                "pred_raw": "",
                "pred_list": [],
                "em_score": 0.0,
                "f1_score": 0.0,
                "em_list": [],
                "f1_list": [],
                "step_count": 0,
                "errors": [str(e)],
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "cm_stats": None,
                "cm_token_counts": None,
            }

        em_sum += em_score
        f1_sum += f1_score
        n += 1

        all_rows.append({
            "id": ex.id,
            "question": ex.question,
            "answer": ex.answer,
            "prediction": sample_result["pred_list"],
            "pred_raw": sample_result["pred_raw"],
            "em": em_score,
            "f1": f1_score,
            "em_list": sample_result["em_list"],
            "f1_list": sample_result["f1_list"],
            "step_count": sample_result["step_count"],
            "errors": sample_result["errors"],
            "total_input_tokens": sample_result["total_input_tokens"],
            "total_output_tokens": sample_result["total_output_tokens"],
            "cm_stats": sample_result.get("cm_stats"),
            "cm_token_counts": sample_result.get("cm_token_counts"),
        })

    # Token aggregates
    total_input_tokens = sum(row["total_input_tokens"] for row in all_rows)
    total_output_tokens = sum(row["total_output_tokens"] for row in all_rows)
    avg_input_tokens = (total_input_tokens / n) if n else 0.0
    avg_output_tokens = (total_output_tokens / n) if n else 0.0

    # Compression cost aggregate (context_manager mode only)
    total_compression_input_tokens = 0
    total_compression_output_tokens = 0
    for row in all_rows:
        cm_stats = row.get("cm_stats")
        if cm_stats:
            total_compression_input_tokens += cm_stats.get("total_input_tokens", 0)
            total_compression_output_tokens += cm_stats.get("total_output_tokens", 0)
    avg_compression_input_tokens = (total_compression_input_tokens / n) if n else 0.0
    avg_compression_output_tokens = (total_compression_output_tokens / n) if n else 0.0

    # Summary
    summary = {
        "total": n,
        "avg_em": (em_sum / n) if n else 0.0,
        "avg_f1": (f1_sum / n) if n else 0.0,
        "mode": mode,
        "split": split_key,
        "num_objectives": num_objectives,
        "data_path": data_path,
        "max_steps": max_steps,
        "token_threshold": token_threshold if mode == "context_manager" else None,
        "keep_recent_pairs": keep_recent_pairs if mode == "context_manager" else None,
        "keep_recent_steps": keep_recent_steps if mode == "context_manager" else None,
        "avg_input_tokens": avg_input_tokens,
        "avg_output_tokens": avg_output_tokens,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "total_compression_input_tokens": total_compression_input_tokens if mode == "context_manager" else None,
        "total_compression_output_tokens": total_compression_output_tokens if mode == "context_manager" else None,
        "avg_compression_input_tokens": avg_compression_input_tokens if mode == "context_manager" else None,
        "avg_compression_output_tokens": avg_compression_output_tokens if mode == "context_manager" else None,
        "timestamp": datetime.now().isoformat(),
    }

    # Save results
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    with open(os.path.join(out_dir, "predictions.jsonl"), "w", encoding="utf-8") as f:
        for row in all_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"\n{'='*60}")
    print(f"Results Summary")
    print(f"{'='*60}")
    print(f"  Mode:       {mode}")
    print(f"  Total:      {n}")
    print(f"  Avg EM:     {em_sum/n*100:.1f}% ({em_sum:.2f}/{n})" if n else "  Avg EM: N/A")
    print(f"  Avg F1:     {f1_sum/n:.3f}" if n else "  Avg F1: N/A")
    print(f"  Avg Input Tokens:  {avg_input_tokens:,.0f}")
    print(f"  Avg Output Tokens: {avg_output_tokens:,.0f}")
    if mode == "context_manager":
        print(f"  Avg Compression Input Tokens:  {avg_compression_input_tokens:,.0f}")
        print(f"  Avg Compression Output Tokens: {avg_compression_output_tokens:,.0f}")
    print(f"  Output:     {out_dir}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run ACON multi-objective QA benchmark with nexent agent")
    parser.add_argument(
        "--data_folder",
        type=str,
        default="data/nq_multi_8",
        help="Path to ACON nq_multi_8 data folder (containing train.jsonl and test.jsonl)",
    )
    parser.add_argument("--split", type=str, default="test", help="Dataset split: train or test")
    parser.add_argument(
        "--mode",
        type=str,
        default="baseline",
        choices=["baseline", "context_manager"],
        help="Evaluation mode: baseline (no compression) or context_manager (nexent CM)",
    )
    parser.add_argument("--max_steps", type=int, default=30, help="Max agent steps per question")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of examples")
    parser.add_argument("--retriever_port", type=str, default="8005", help="ACON retriever server port")
    parser.add_argument("--token_threshold", type=int, default=7200, help="ContextManager token threshold (for context_manager mode)")
    parser.add_argument("--keep_recent_pairs", type=int, default=1, help="ContextManager keep_recent_pairs (for context_manager mode)")
    parser.add_argument("--keep_recent_steps", type=int, default=4, help="ContextManager keep_recent_steps (for context_manager mode)")
    parser.add_argument("--max_observation_length", type=int, default=20000, help="Max observation length in chars (for context_manager mode)")
    parser.add_argument("--debug", action="store_true", help="Enable debug output")
    parser.add_argument("--output_dir", type=str, default=None, help="Override output directory")
    parser.add_argument("--id_list_file", type=str, default=None, help="File with example IDs to filter (one per line)")
    parser.add_argument(
        "--num_objectives",
        type=int,
        default=8,
        help="Number of sub-questions to use per sample (1-8, default: 8)",
    )

    args = parser.parse_args()

    asyncio.run(main(
        data_folder=args.data_folder,
        split=args.split,
        mode=args.mode,
        max_steps=args.max_steps,
        limit=args.limit,
        retriever_port=args.retriever_port,
        token_threshold=args.token_threshold,
        keep_recent_pairs=args.keep_recent_pairs,
        keep_recent_steps=args.keep_recent_steps,
        max_observation_length=args.max_observation_length,
        debug=args.debug,
        output_dir=args.output_dir,
        id_list_file=args.id_list_file,
        num_objectives=args.num_objectives,
    ))
