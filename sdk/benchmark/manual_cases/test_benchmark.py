import asyncio
import copy
import glob
import json
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths  # noqa: F401 — side-effect: adds sdk/, backend/ to sys.path

from agent_runner import (
    build_agent_run_info,
    run_agent_with_tracking,
    parse_conversation_to_history,
    AgentHistory,
    ContextManagerConfig,
)

from nexent.core.agents.agent_context import ContextManager
from nexent.core.utils.token_estimation import estimate_tokens_text

from eval_utils import eval_text, average_score


def history_to_text(history: list[AgentHistory]) -> str:
    return "\n".join([f"{h.role}: {h.content}" for h in history])


async def run_multi_turn_for_benchmark(
    queries: list[str],
    base_history: list[AgentHistory],
    cm_config: ContextManagerConfig,
    max_steps: int = 5,
):
    conversation_history = list(base_history)
    results = []

    shared_cm = None
    if cm_config and cm_config.enabled:
        shared_cm = ContextManager(config=cm_config, max_steps=max_steps)

    initial_tokens = estimate_tokens_text(history_to_text(conversation_history))

    # Track per-step actual input tokens for accurate token reduction
    step_input_tokens = []

    for query in queries:
        agent_run_info = build_agent_run_info(
            query,
            conversation_history,
            max_steps=max_steps,
            context_manager_config=cm_config,
        )

        if shared_cm is not None:
            agent_run_info.context_manager = shared_cm

        result = await run_agent_with_tracking(agent_run_info, debug=False)
        results.append(result)

        # Collect actual input token count from the last step metrics
        if shared_cm is not None:
            tc = shared_cm.get_token_counts()
            step_input_tokens.append(tc)

        conversation_history.append(AgentHistory(role="user", content=query))
        conversation_history.append(
            AgentHistory(role="assistant", content=result.final_answer)
        )

    final_tokens = estimate_tokens_text(history_to_text(conversation_history))

    cm_stats = None
    cm_token_counts = None
    cm_summary = None
    if shared_cm is not None:
        cm_stats = shared_cm.get_all_compression_stats()
        cm_token_counts = shared_cm.get_token_counts()
        cm_summary = shared_cm.export_summary()

    return {
        "results": results,
        "conversation_history": conversation_history,
        "shared_cm": shared_cm,
        "initial_tokens": initial_tokens,
        "final_tokens": final_tokens,
        "cm_stats": cm_stats,
        "cm_token_counts": cm_token_counts,
        "cm_summary": cm_summary,
        "step_input_tokens": step_input_tokens,
    }


def build_precompressed_history(
    frozen_history: list[AgentHistory],
    cm_summary: dict,
) -> list[AgentHistory]:
    """Build a pre-compressed history from the compression snapshot.

    Replaces the compressed prefix pairs with a single user message containing
    the summary text, then appends the retained tail pairs verbatim. This
    mirrors the actual message structure produced by compress_if_needed:

        SummaryTaskStep.to_messages() → [ChatMessage(role=USER, summary)]
        followed by retained tail steps → [TaskStep, ActionStep, ...]

    There is NO assistant message after the summary — the model sees the
    summary as a user message, followed directly by the next retained step.

    Args:
        frozen_history: The original uncompressed conversation history.
        cm_summary: The export_summary() dict from the compressed run's
                    ContextManager, containing summary text and boundary info.

    Returns:
        A new AgentHistory list that mirrors the compressed context structure.
    """
    boundary = cm_summary.get("compression_boundary", {})
    compressed_pairs = boundary.get("previous_compressed_pairs", 0)

    # Each pair = 2 AgentHistory entries (user + assistant)
    compressed_entries = compressed_pairs * 2

    summary_text = cm_summary.get("previous_summary") or ""

    # If no compression happened, return original history unchanged
    if not summary_text or compressed_entries == 0:
        return list(frozen_history)

    # Build pre-compressed history:
    # 1. Summary as a single USER message (matching SummaryTaskStep.to_messages)
    #    No paired assistant message — the model sees summary then next retained step
    precompressed = [
        AgentHistory(
            role="user",
            content=f"Summary of earlier steps in this task:\n{summary_text}",
        ),
    ]

    # 2. Retained tail pairs (everything after the compressed prefix)
    if compressed_entries < len(frozen_history):
        precompressed.extend(frozen_history[compressed_entries:])

    return precompressed


async def run_probe_questions(
    probes: list[dict],
    precompressed_history: list[AgentHistory],
    max_steps: int = 5,
):
    """Run probe questions against a pre-compressed history snapshot.

    Each probe runs independently with compression DISABLED, because the
    history has already been pre-compressed (compressed prefix replaced with
    summary text, retained tail kept verbatim). This avoids redundant LLM
    compression calls — the compression was done once in the compressed run,
    and all probes reuse that result.

    Per CLAUDE.md rules:
    - Each probe uses a deep-copied frozen snapshot
    - Probes see compressed context (summary + retained tail)
    - No compression triggered during probe phase
    - Probes are fully independent, no shared state
    """
    probe_results = []
    no_compression_config = ContextManagerConfig(enabled=False, token_threshold=10**9)

    for probe in probes:
        question = probe["question"]

        # Each probe gets its own deep copy — fully independent
        probe_history = copy.deepcopy(precompressed_history)

        agent_run_info = build_agent_run_info(
            question,
            probe_history,
            max_steps=max_steps,
            context_manager_config=no_compression_config,
        )

        result = await run_agent_with_tracking(agent_run_info, debug=False)
        eval_result = eval_text(result.final_answer, probe)

        probe_results.append(
            {
                "question": question,
                "answer": result.final_answer,
                "passed": eval_result.passed,
                "score": eval_result.score,
                "details": eval_result.details,
            }
        )

    return probe_results


async def run_baseline_probes(
    probes: list[dict],
    frozen_history: list[AgentHistory],
    max_steps: int = 5,
):
    """Run probe questions against full uncompressed history (baseline).

    This measures the ceiling: what can the agent answer when it sees
    the complete history. probe_retention = compressed_score / baseline_score.
    """
    probe_results = []
    baseline_config = ContextManagerConfig(enabled=False, token_threshold=10**9)

    for probe in probes:
        question = probe["question"]
        probe_history = copy.deepcopy(frozen_history)

        agent_run_info = build_agent_run_info(
            question,
            probe_history,
            max_steps=max_steps,
            context_manager_config=baseline_config,
        )

        result = await run_agent_with_tracking(agent_run_info, debug=False)
        eval_result = eval_text(result.final_answer, probe)

        probe_results.append(
            {
                "question": question,
                "answer": result.final_answer,
                "passed": eval_result.passed,
                "score": eval_result.score,
                "details": eval_result.details,
            }
        )

    return probe_results


def eval_summary_inspection(summary: dict, checks: list[dict]) -> list[dict]:
    """Static Compression Inspection — check if the compressed summary
    retains key information (user preferences, file names, plans, tool results).

    Uses dedicated summary_checks when available, NOT probe must_contain
    (which has different semantics — probe keywords are for agent answers,
    summary keywords are for what the compressor chose to preserve).
    """
    results = []

    prev_summary = summary.get("previous_summary") or ""
    curr_summary = summary.get("current_summary") or ""
    combined = prev_summary + "\n" + curr_summary

    for check in checks:
        eval_result = eval_text(combined, check)
        results.append(
            {
                "check": check,
                "passed": eval_result.passed,
                "score": eval_result.score,
                "details": eval_result.details,
            }
        )

    return results


def eval_task_outputs(case: dict, run_outputs: list):
    eval_results = []

    for check in case.get("task_checks", []):
        turn_idx = check["turn"] - 1
        if turn_idx >= len(run_outputs):
            continue

        answer = run_outputs[turn_idx].final_answer
        r = eval_text(answer, check)

        eval_results.append(
            {
                "turn": check["turn"],
                "answer": answer,
                "passed": r.passed,
                "score": r.score,
                "details": r.details,
            }
        )

    return eval_results


def _resolve_compressed_config(case: dict) -> ContextManagerConfig:
    """Build compressed config from case definition, with sensible defaults."""
    case_cfg = case.get("compressed_config", {})
    return ContextManagerConfig(
        enabled=True,
        token_threshold=case_cfg.get("token_threshold", 3600),
        keep_recent_pairs=case_cfg.get("keep_recent_pairs", 1),
        keep_recent_steps=case_cfg.get("keep_recent_steps", 4),
        max_observation_length=case_cfg.get("max_observation_length", 20000),
    )


async def run_one_case(case_dir: str):
    """Load and run a single benchmark case from its directory.

    Each case directory contains:
      - case.json: queries, probes, summary_checks, task_checks, compressed_config
      - history.json: conversation history

    Args:
        case_dir: Absolute or relative path to the case directory.

    Returns:
        Report dict for this case.
    """
    case_path = os.path.join(case_dir, "case.json")
    with open(case_path, "r", encoding="utf-8") as f:
        case = json.load(f)

    # Resolve history_file relative to the case directory;
    # defaults to "history.json" in the same directory if not specified.
    history_relpath = case.get("history_file", "history.json")
    history_abspath = os.path.join(case_dir, history_relpath)

    base_history = parse_conversation_to_history(history_abspath)

    baseline_config = ContextManagerConfig(
        enabled=False,
        token_threshold=10**9,
        keep_recent_pairs=1,
    )

    # P5: Allow per-case config override
    compressed_config = _resolve_compressed_config(case)

    print(f"\n===== CASE: {case['id']} =====")

    baseline = await run_multi_turn_for_benchmark(
        queries=case["queries"],
        base_history=base_history,
        cm_config=baseline_config,
    )

    compressed = await run_multi_turn_for_benchmark(
        queries=case["queries"],
        base_history=base_history,
        cm_config=compressed_config,
    )

    baseline_task_eval = eval_task_outputs(case, baseline["results"])
    compressed_task_eval = eval_task_outputs(case, compressed["results"])

    # P1: Baseline probe — agent sees full uncompressed history
    # Same frozen_history, but with compression disabled, so the agent sees
    # the complete unmodified context. This establishes the ceiling for
    # probe_retention = compressed_probe_score / baseline_probe_score.
    baseline_probe_eval = await run_baseline_probes(
        probes=case["probes"],
        frozen_history=compressed["conversation_history"],
        max_steps=5,
    )

    # P0: Compressed probe — agent sees pre-compressed context
    # Build the pre-compressed history ONCE using the summary from the
    # compressed run's ContextManager, then run each probe independently
    # against it with compression disabled. This avoids redundant LLM calls
    # (compression was already done in the compressed multi-turn run).
    precompressed_history = build_precompressed_history(
        frozen_history=compressed["conversation_history"],
        cm_summary=compressed["cm_summary"] or {},
    )
    compressed_probe_eval = await run_probe_questions(
        probes=case["probes"],
        precompressed_history=precompressed_history,
    )

    # P3: Summary inspection uses dedicated summary_checks, not probe must_contain
    summary_inspection = []
    if compressed.get("cm_summary"):
        summary_checks = case.get("summary_checks", [])
        if summary_checks:
            summary_inspection = eval_summary_inspection(
                compressed["cm_summary"], summary_checks
            )

    baseline_task_score = sum(x["score"] for x in baseline_task_eval) / max(
        len(baseline_task_eval), 1
    )

    compressed_task_score = sum(x["score"] for x in compressed_task_eval) / max(
        len(compressed_task_eval), 1
    )

    baseline_probe_score = sum(x["score"] for x in baseline_probe_eval) / max(
        len(baseline_probe_eval), 1
    )

    compressed_probe_score = sum(x["score"] for x in compressed_probe_eval) / max(
        len(compressed_probe_eval), 1
    )

    summary_score = (
        sum(x["score"] for x in summary_inspection) / max(len(summary_inspection), 1)
        if summary_inspection
        else None
    )

    task_success_retention = (
        compressed_task_score / baseline_task_score
        if baseline_task_score > 0
        else 0.0
    )

    probe_retention = (
        compressed_probe_score / baseline_probe_score
        if baseline_probe_score > 0
        else 0.0
    )

    # P2: Token reduction from actual input token counts
    # Use the last step's token counts (final compressed vs uncompressed state)
    token_reduction = 0.0
    if compressed.get("step_input_tokens") and compressed["step_input_tokens"]:
        last_tc = compressed["step_input_tokens"][-1]
        if last_tc and last_tc.get("last_uncompressed") is not None:
            unc = last_tc["last_uncompressed"] or 1
            comp = last_tc["last_compressed"] or 0
            if unc > 0:
                token_reduction = 1 - comp / unc
    # Fallback to text-based estimation
    if token_reduction == 0.0:
        token_reduction = 1 - (
            compressed["final_tokens"] / max(baseline["final_tokens"], 1)
        )
    baseline_failed = baseline_task_score == 0 

    report = {
        "case_id": case["id"],
        "baseline_failed": baseline_failed,
        "baseline": {
            "task_score": baseline_task_score,
            "probe_score": baseline_probe_score,
            "final_tokens": baseline["final_tokens"],
        },
        "compressed": {
            "task_score": compressed_task_score,
            "probe_score": compressed_probe_score,
            "final_tokens": compressed["final_tokens"],
            "cm_stats": compressed["cm_stats"],
            "cm_token_counts": compressed["cm_token_counts"],
            "cm_summary": compressed["cm_summary"],
        },
        "metrics": {
            "task_success_retention": task_success_retention,
            "probe_retention": probe_retention,
            "token_reduction": token_reduction,
            "summary_score": summary_score,
        },
        "task_eval": compressed_task_eval,
        "probe_eval": {
            "baseline": baseline_probe_eval,
            "compressed": compressed_probe_eval,
        },
        "summary_inspection": summary_inspection,
    }

    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return report


async def main(case_names: list[str] = None):
    # Discover cases: use specified names if provided, otherwise find all cases under ./cases/*/case.json
    if case_names:
        case_dirs = [os.path.join("./cases", name) for name in case_names]
    else:
        case_dirs = sorted(glob.glob("./cases/*/case.json"))
        case_dirs = [os.path.dirname(p) for p in case_dirs]

    if not case_dirs:
        print("No benchmark cases found under ./cases/*/case.json")
        return

    print(f"Found {len(case_dirs)} case(s): {[os.path.basename(d) for d in case_dirs]}")

    # Output directory for reports
    os.makedirs("./reports", exist_ok=True)

    reports = []
    for case_dir in case_dirs:
        report = await run_one_case(case_dir)
        reports.append(report)

        # Write per-case report
        case_id = report["case_id"]
        per_case_path = os.path.join("./reports", f"{case_id}.json")
        with open(per_case_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        print(f"  Report saved to {per_case_path}")
    
    # Exclude cases where baseline itself failed
    valid_reports = [r for r in reports if not r.get["baseline_failed"]]
    excluded_ids = [r["case_id"] for r in reports if r.get("baseline_failed")]
    if excluded_ids:
        print(f"\n  Excluded from average (baseline failed): {excluded_ids}")
    # Write summary across all cases
    summary = {
        "total_cases": len(reports),
        "excluded_cases": len(reports) - len(valid_reports),
        "metrics": {
            "avg_task_success_retention": sum(
                r["metrics"]["task_success_retention"] for r in valid_reports
            ) / max(len(valid_reports), 1),
            "avg_probe_retention": sum(
                r["metrics"]["probe_retention"] for r in valid_reports
            ) / max(len(valid_reports), 1),
            "avg_token_reduction": sum(
                r["metrics"]["token_reduction"] for r in valid_reports
            ) / max(len(valid_reports), 1),
            "per_case": {
                r["case_id"]: r["metrics"] for r in reports
            },
        },
    }
    summary_path = "./reports/summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

    print(f"\nBenchmark finished. Summary saved to {summary_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Agent Context Compression Benchmark")
    parser.add_argument(
        "--cases",nargs="+",default=None,
        help="Specific case names to run (e.g. --cases example_infra algotithm_data)."
             "if omitted, run all cases under .cases/."
    )
    args = parser.parse_args()
    asyncio.run(main(case_names = args.cases))