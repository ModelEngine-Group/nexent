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
        --data_folder D:/path/to/acon/experiments/smolagents/data/nq_multi_8 \
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
    """Build a lean, QA-optimized system prompt.

    This bypasses the generic platform template to avoid irrelevant sections
    (File URL Guide, Reference Marks, Markdown formatting, safety principles)
    that waste tokens and can conflict with concise QA answering.
    """
    answer_slots = "; ".join(f"answer{i}" for i in range(1, num_objectives + 1))

    return f"""You are a QA agent that answers multiple sub-questions using search.

## Task Rules
- You must answer ALL sub-questions. The questions are separated by semicolons (;).
- Answer sub-questions sequentially, one at a time.
- Use the wikipedia_search tool to find information before answering each sub-question.
- When you have answers to all sub-questions, use the final_answer tool to submit them.
- **CRITICAL**: Copy the answer phrase EXACTLY as it appears in the search result text. Do NOT rephrase, shorten, or drop adjectives. If the text says "edible tuber", write "edible tuber" — NOT "tubers" or "a tuber".
- Keep answers concise but preserve key adjectives and specific terms from the source.
- Separate your answers with semicolons in the same order as the sub-questions.
- Do NOT add explanations, context, or extra words in the final answer.

## Format
final_answer(answer="{answer_slots}")

## Execution Loop
To solve tasks, follow a loop of Think and Code steps:

1. Think: Decide which tool to use and what to search for.
2. Code: Write Python code to call the tool. Use <code>code</code> tags for executable code.
   - After execution, the system returns results with "Observation:" marker.
   - Continue based on real observation results only — do NOT fabricate results.

3. When you have all answers, call final_answer directly.

## Available Tools
- wikipedia_search(query: str, n_results: int = 3) — Search 2018 Wikipedia for relevant passages.
- final_answer(answer: any) — Submit your final answer.

## Code Rules
1. Only use <code>code</code> for executable code.
2. Use keyword arguments for tool calls: tool_name(param1="value1", param2="value2")
3. Use print() to pass information between steps; printed content persists.
4. Do NOT repeat the same search with identical parameters.
5. Do NOT give up. Keep searching until you find the answer.

## Example
Task: "Where is the food stored in a yam plant?; Who plays Lefou in Beauty and the Beast 1991?"
Think: I need to find where food is stored in a yam plant first.
<code>result = wikipedia_search(query="yam plant food storage organ", n_results=3)
print(result)</code>
Observation: Yams are tuber crops... The edible tuber is the main storage organ...
Think: The answer is "edible tuber" — I must keep the adjective. Now search for Lefou's voice actor.
<code>result = wikipedia_search(query="Lefou voice actor Beauty and the Beast 1991", n_results=3)
print(result)</code>
Observation: Lefou was voiced by Jesse Corti in the 1991 animated film...
Think: The answer is "Jesse Corti".
<code>final_answer(answer="edible tuber; Jesse Corti")</code>

Now start! Answer all sub-questions with short, precise phrases from the search results."""


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
        "cm_stats": shared_cm.get_all_compression_stats() if shared_cm else None,
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
    enable_reload: bool,
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
        cm_config = ContextManagerConfig(
            enabled=True,
            token_threshold=token_threshold,
            keep_recent_pairs=keep_recent_pairs,
            keep_recent_steps=keep_recent_steps,
            max_observation_length=max_observation_length,
            enable_reload=enable_reload,
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
              f"keep_recent_steps={keep_recent_steps}, max_obs_len={max_observation_length}, "
              f"enable_reload={enable_reload}")
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
                "cm_stats": None,
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
        })

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
    parser.add_argument("--token_threshold", type=int, default=12000, help="ContextManager token threshold (for context_manager mode)")
    parser.add_argument("--keep_recent_pairs", type=int, default=1, help="ContextManager keep_recent_pairs (for context_manager mode)")
    parser.add_argument("--keep_recent_steps", type=int, default=4, help="ContextManager keep_recent_steps (for context_manager mode)")
    parser.add_argument("--max_observation_length", type=int, default=20000, help="Max observation length in chars (for context_manager mode)")
    parser.add_argument("--enable_reload", action="store_true", default=True, help="Enable reload tool for offloaded context (for context_manager mode)")
    parser.add_argument("--no_reload", dest="enable_reload", action="store_false", help="Disable reload tool")
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
        enable_reload=args.enable_reload,
        debug=args.debug,
        output_dir=args.output_dir,
        id_list_file=args.id_list_file,
        num_objectives=args.num_objectives,
    ))
