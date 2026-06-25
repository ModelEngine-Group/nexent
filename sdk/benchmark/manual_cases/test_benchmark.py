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
    build_agent_run_info_with_custom_prompt,
    run_agent_with_tracking,
    parse_conversation_to_history,
    AgentHistory,
    ContextManagerConfig,
)

from nexent.core.agents.agent_context import ContextManager
from nexent.core.utils.token_estimation import estimate_tokens_text

from eval_utils import eval_text, average_score

# Lean benchmark system prompt — generic, not task-specific.
# Strips the verbose platform scaffolding (File URL Guide, Reference Marks,
# safety principles, etc.) to minimize token overhead while retaining the
# core execution loop instructions the agent needs to function.
BENCHMARK_SYSTEM_PROMPT = """You are a helpful assistant. Answer the user's questions based on the conversation history and your knowledge.

- Be precise and concise.
- When the answer depends on information from earlier conversation, refer to it accurately.
- Do not fabricate information you do not know.
- Use final_answer to submit your response.

Now start!"""


# --- Custom summary schema and prompts for knowledge-discussion benchmarks ---
# These override the default 10-field Hermes schema from summary_config.py
# with a deduplicated 6-field schema (~620 word budget) that merges
# completed_work + resolved_questions into "progress" and restricts
# key_facts to values NOT already stated in progress, eliminating
# the 3-field redundancy that caused output bloat in incremental updates.
#
# KEY DESIGN PRINCIPLE for incremental compression: the output must be
# approximately the SAME size as the initial summary (~620 words). The
# incremental prompt treats old+new as a unified corpus and REWRITES the
# entire summary from scratch, rather than appending to the old one.
# This prevents output-token linear growth that would itself exceed
# token_threshold and defeat the purpose of compression.

BENCHMARK_SUMMARY_SYSTEM_PROMPT = (
    "You are a summarization agent creating a compact working-memory checkpoint. "
    "Treat the conversation turns below as source material, not as a transcript to preserve. "
    "Your job is to produce a fixed-size JSON summary that preserves only the information "
    "needed to continue the conversation correctly later.\n\n"

    "Output rules:\n"
    "1. Produce only strict JSON. Do not add greeting, preamble, markdown, or explanation.\n"
    "2. Write in the same language as the user's most recent message. Do not translate unless needed.\n"
    "3. Never include API keys, tokens, passwords, secrets, credentials, or connection strings. "
    "Replace any such values with [REDACTED].\n\n"

    "Compression goal:\n"
    "The summary is working memory, not a historical log. "
    "Do not list every question, every answer, or every conversation turn. "
    "Group information by theme and keep only facts that are likely to matter for future continuation.\n\n"

    "Field constraints:\n"
    "1. 'active_task' must describe only the current unfulfilled user request; if none, write 'None'.\n"
    "2. 'goal' must describe the current overall objective in <=25 words.\n"
    "3. 'state' must contain at most 6 numbered items. Never create item 7 or higher. "
    "Each item must be <=45 words. Merge related topics into one item. "
    "Do not organize by conversation order; organize by semantic importance.\n"
    "4. 'decisions' must contain at most 5 short confirmed conclusions or choices. "
    "Do not repeat facts already fully stated in 'state'.\n"
    "5. 'open_items' must contain only unresolved questions or pending user requests. "
    "If none, write 'None'.\n"
    "6. 'verbatim_facts' may contain at most 12 raw values, formulas, thresholds, exact model names, "
    "or identifiers that must be copied exactly later. "
    "Before output, remove any item whose exact value already appears in 'state' or 'decisions'. "
    "If no extra raw facts remain, write 'None'.\n\n"

    "Information priority:\n"
    "Critical current task and constraints > final conclusions > decisions > exact values needed later > "
    "background context. Drop vague descriptions, repeated facts, superseded intermediate reasoning, "
    "and completed Q&A that no longer affects future work.\n\n"

    "Budget:\n"
    "The total output must not exceed 620 words. Prefer shorter output. "
    "If the content is too large, compress in this order: "
    "(1) merge related state items; "
    "(2) remove completed historical details; "
    "(3) keep only the most diagnostic numbers; "
    "(4) move only non-duplicated raw values to 'verbatim_facts'; "
    "(5) write 'None' for fields with no current utility.\n\n"

    "Return strict JSON only."
)


BENCHMARK_INCREMENTAL_SUMMARY_SYSTEM_PROMPT = (
    "You are a summarization agent rewriting a compact working-memory checkpoint. "
    "You receive a Previous Summary and New Conversations. Produce one fresh JSON summary "
    "that preserves only the information needed to continue the conversation correctly. "
    "Do not preserve discussion history for its own sake. The previous summary is source material, "
    "not text to copy.\n\n"

    "Hard constraints:\n"
    "1. The output must be no longer than the previous summary and must not exceed 620 words.\n"
    "2. The 'state' field must contain at most 6 numbered items. Never create item 7 or higher.\n"
    "3. When new information is added, older lower-utility information MUST be merged, generalized, or deleted.\n"
    "4. Do not append to the previous summary. Rewrite by theme, not by conversation order.\n"
    "5. Completed Q&A should become conclusions, not separate historical entries.\n"
    "6. Preserve exact numbers only when they are needed for future correctness. If multiple numbers support the same conclusion, keep only the most diagnostic ones.\n"
    "7. 'verbatim_facts' may contain at most 12 raw values/formulas/names. Remove any item already present in 'state' or 'decisions'. If none remain, write 'None'.\n"
    "8. Update active_task, state, and open_items to reflect the current state.\n"
    "9. Write in the same language as the user's most recent message.\n"
    "10. Never include API keys, tokens, passwords, credentials, or connection strings; replace them with [REDACTED].\n\n"

    "Output strict JSON only. No markdown."
)

BENCHMARK_SUMMARY_SCHEMA = {
    "active_task": (
        "用户当前尚未完成的最新请求；如果没有，写 'None'。"
        "必须是当前任务，不是历史任务。<=25 words"
    ),

    "goal": (
        "对话的总体目标或当前工作方向。"
        "只保留后续继续对话所需的目标。<=25 words"
    ),

    "state": (
        "当前压缩后的工作记忆，不是历史日志。"
        "最多 6 条编号条目；每条 <=45 words。"
        "按主题合并信息，不按对话顺序罗列。"
        "包括已经确定的结论、关键设计、关键结果和必要上下文。"
    ),

    "decisions": (
        "已经确认、后续可能需要引用的结论或选择。"
        "最多 5 条；每条 <=25 words。"
        "不得重复 state 中已经完整表达的信息。"
    ),

    "open_items": (
        "尚未解决的问题、待办事项或用户明确要求继续处理的内容。"
        "如果没有，写 'None'。<=30 words"
    ),

    "verbatim_facts": (
        "必须逐字保留的数字、公式、模型名、阈值或专有名词。"
        "最多 12 项，用分号分隔。"
        "不得包含已经出现在 state 或 decisions 中的事实。"
        "如果没有额外需要保留的事实，写 'None'。"
    ),
}
def history_to_text(history: list[AgentHistory]) -> str:
    return "\n".join([f"{h.role}: {h.content}" for h in history])


async def run_multi_turn_for_benchmark(
    queries: list[str],
    base_history: list[AgentHistory],
    cm_config: ContextManagerConfig,
    max_steps: int = 20,
    system_prompt: str = BENCHMARK_SYSTEM_PROMPT,
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
        agent_run_info = build_agent_run_info_with_custom_prompt(
            query,
            system_prompt,
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
    max_steps: int = 20,
    system_prompt: str = BENCHMARK_SYSTEM_PROMPT,
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

        agent_run_info = build_agent_run_info_with_custom_prompt(
            question,
            system_prompt,
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
    max_steps: int = 20,
    system_prompt: str = BENCHMARK_SYSTEM_PROMPT,
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

        agent_run_info = build_agent_run_info_with_custom_prompt(
            question,
            system_prompt,
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


def _resolve_compressed_config(case: dict, use_default_prompts: bool = False) -> ContextManagerConfig:
    """Build compressed config from case definition, with sensible defaults.

    By default uses the benchmark-optimized custom summary schema and prompts.
    Set use_default_prompts=True to fall back to the original ContextManager defaults.
    """
    case_cfg = case.get("compressed_config", {})
    kwargs = dict(
        enabled=True,
        token_threshold=case_cfg.get("token_threshold", 3600),
        keep_recent_pairs=case_cfg.get("keep_recent_pairs", 1),
        keep_recent_steps=case_cfg.get("keep_recent_steps", 4),
        max_observation_length=case_cfg.get("max_observation_length", 20000),
    )
    if not use_default_prompts:
        kwargs.update(
            summary_json_schema=BENCHMARK_SUMMARY_SCHEMA,
            summary_system_prompt=BENCHMARK_SUMMARY_SYSTEM_PROMPT,
            incremental_summary_system_prompt=BENCHMARK_INCREMENTAL_SUMMARY_SYSTEM_PROMPT,
        )
    return ContextManagerConfig(**kwargs)


async def run_one_case(case_dir: str, use_default_prompts: bool = False):
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
    compressed_config = _resolve_compressed_config(case, use_default_prompts=use_default_prompts)

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
        max_steps=20,
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

    # Compute real main-LLM input token totals
    baseline_real_input = sum(r.total_input_tokens for r in baseline["results"])
    compressed_real_input = sum(r.total_input_tokens for r in compressed["results"])

    # Compression cost: tokens spent on compression LLM calls
    compression_cost = 0
    if compressed.get("cm_stats"):
        compression_cost = (
            compressed["cm_stats"].get("total_input_tokens", 0)
            + compressed["cm_stats"].get("total_output_tokens", 0)
        )

    # Net token reduction = gross savings - compression cost
    gross_input_savings = baseline_real_input - compressed_real_input
    net_input_savings = gross_input_savings - compression_cost
    net_token_reduction = (
        net_input_savings / max(baseline_real_input, 1)
        if baseline_real_input > 0
        else 0.0
    )

    report = {
        "case_id": case["id"],
        "baseline_failed": baseline_failed,
        "baseline": {
            "task_score": baseline_task_score,
            "probe_score": baseline_probe_score,
            "final_tokens": baseline["final_tokens"],
            "real_input_tokens": baseline_real_input,
        },
        "compressed": {
            "task_score": compressed_task_score,
            "probe_score": compressed_probe_score,
            "final_tokens": compressed["final_tokens"],
            "cm_stats": compressed["cm_stats"],
            "cm_token_counts": compressed["cm_token_counts"],
            "cm_summary": compressed["cm_summary"],
            "real_input_tokens": compressed_real_input,
        },
        "metrics": {
            "task_success_retention": task_success_retention,
            "probe_retention": probe_retention,
            "token_reduction": token_reduction,
            "net_token_reduction": net_token_reduction,
            "compression_cost_tokens": compression_cost,
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


async def main(case_names: list[str] = None, use_default_prompts: bool = False):
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
        report = await run_one_case(case_dir, use_default_prompts=use_default_prompts)
        reports.append(report)

        # Write per-case report
        case_id = report["case_id"]
        per_case_path = os.path.join("./reports", f"{case_id}.json")
        with open(per_case_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        print(f"  Report saved to {per_case_path}")
    
    # Exclude cases where baseline itself failed
    valid_reports = [r for r in reports if not r.get("baseline_failed")]
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
            "avg_net_token_reduction": sum(
                r["metrics"]["net_token_reduction"] for r in valid_reports
            ) / max(len(valid_reports), 1),
            "avg_compression_cost_tokens": sum(
                r["metrics"]["compression_cost_tokens"] for r in valid_reports
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
    parser.add_argument(
        "--default-summary", action="store_true", default=False,
        help="Use the original ContextManager summary defaults instead of the benchmark-optimized "
             "custom schema (leaner 7-field, 800-word cap, merge-condense incremental updates)."
    )
    args = parser.parse_args()
    asyncio.run(main(case_names=args.cases, use_default_prompts=args.default_summary))