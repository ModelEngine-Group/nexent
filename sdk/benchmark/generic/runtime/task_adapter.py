# -*- coding: utf-8 -*-
"""Task adapter: bridges Langfuse DatasetItem to NexentAgent execution.

Provides a factory function that creates a Langfuse-compatible task function
bound to a specific agent configuration. The task function:
1. Extracts the question/query from the DatasetItem input
2. Builds an AgentRunInfo via agent_runner.py
3. Runs the agent and returns structured results
"""
import asyncio
import os
import sys
from pathlib import Path
from typing import Any


# Path setup must happen before importing agent_runner.
GENERIC_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GENERIC_DIR.parent))
import paths  # noqa: E402, F401
from agent_runner import (  # noqa: E402
    AgentRunResult,
    build_agent_run_info,
    build_agent_run_info_with_custom_prompt,
    run_agent_with_tracking,
)


def render_precompact_system_prompt(context_items: list) -> str:
    """Render the static system context with the production ContextItem renderer."""
    from nexent.core.agents.context.models import normalize_context_inputs
    from nexent.core.agents.context.rendering import ContextItemRenderer

    normalized = normalize_context_inputs(context_items)
    messages = ContextItemRenderer().render(normalized)
    text_parts = []
    for message in messages:
        if message.get("role") not in {"system", "developer"}:
            continue
        content = message.get("content", [])
        if isinstance(content, str):
            text_parts.append(content)
            continue
        text_parts.extend(
            str(block.get("text", ""))
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "text"
            and block.get("text")
        )
    return "\n\n".join(text_parts)


def _get_budget_threshold(agent_run_info: Any, budget_type: str) -> int:
    """Extract soft or hard budget threshold from agent config."""
    cm_config = getattr(agent_run_info.agent_config, "context_manager_config", None)
    if cm_config is None:
        return 0
    if budget_type == "soft":
        return getattr(cm_config, "soft_input_budget_tokens", 0) or getattr(cm_config, "token_threshold", 0) or 0
    return getattr(cm_config, "hard_input_budget_tokens", 0) or int(getattr(cm_config, "token_threshold", 0) * 1.1) or 0


def make_nexent_task(
    system_prompt: str = "",
    duty_prompt: str = "",
    constraint_prompt: str = "",
    few_shots_prompt: str = "",
    max_steps: int = 10,
    temperature: float = 0.1,
    language: str = "en",
    tools: list = None,
    managed_agents: list = None,
    input_key: str = "question",
    max_tokens: int = None,
    context_manager_config = None,
    experiment_time: str = None,
    model_factory: str = None,
    user_id: str = "user_id",
    prompt_template_version: str = "",
    prompt_template_source: str = "",
    resource_support: dict = None,
    intentional_empty_resources: dict = None,
    prompt_components: dict = None,
):
    """Factory: create a Langfuse task function bound to agent config.

    Args:
        system_prompt: Custom system prompt (bypasses template engine if set).
        duty_prompt: Duty prompt for template-based system prompt.
        constraint_prompt: Constraint prompt for template-based system prompt.
        few_shots_prompt: Few-shot examples prompt.
        max_steps: Max agent execution steps.
        temperature: LLM temperature.
        language: Language for prompts (en/zh).
        tools: Tool list (ToolConfig objects).
        managed_agents: Managed sub-agents.
        input_key: Key in DatasetItem.input that contains the question.
        max_tokens: Per-call output token cap.
        user_id: Stable benchmark user identifier used by prompt/context assembly.

    Returns:
        A function compatible with Langfuse's TaskFunction protocol.
    """
    tools = tools or []
    managed_agents = managed_agents or []
    minio_bucket = os.getenv("MINIO_DEFAULT_BUCKET", "nexent")
    file_prefix = os.getenv("GAIA_FILE_PREFIX", "gaia")

    def task(*, item, **kwargs):
        """Execute NexentAgent on a single DatasetItem.

        Args:
            item: Langfuse DatasetItem (has .input, .expected_output, .metadata)
                  or a plain dict with "input" / "expected_output" keys.

        Returns:
            dict with final_answer, step_count, token counts, and errors.
        """
        # Extract input from either a DatasetItem or a plain dictionary.
        if isinstance(item, dict):
            inp = item.get("input", {})
        else:
            inp = item.input if hasattr(item, "input") else {}

        question = inp.get(input_key, "") if isinstance(inp, dict) else str(inp)

        # Inject file attachment S3 URL when DatasetItem has file_name,
        # matching production behavior in create_agent_info.py
        file_name = inp.get("file_name") if isinstance(inp, dict) else None
        if file_name and question:
            s3_url = f"s3:/{minio_bucket}/{file_prefix}/{file_name}"
            question = (
                f"User uploaded files. The file information is as follows:\n\n"
                f"File name: {file_name}, S3 URL: {s3_url}  [permanent]\n\n"
                f"User wants to answer questions based on the information in the above files: {question}"
            )

        if not question:
            return {
                "final_answer": "",
                "step_count": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "errors": ["No question found in input"],
            }

        # Build agent run info
        if system_prompt:
            agent_run_info = build_agent_run_info_with_custom_prompt(
                query=question,
                system_prompt=system_prompt,
                history=[],
                tools=tools,
                managed_agents=managed_agents,
                max_steps=max_steps,
                temperature=temperature,
                language=language,
                context_manager_config=context_manager_config,
                model_factory=model_factory,
            )
        else:
            agent_run_info = build_agent_run_info(
                query=question,
                history=[],
                duty_prompt=duty_prompt,
                constraint_prompt=constraint_prompt,
                few_shots_prompt=few_shots_prompt,
                tools=tools,
                managed_agents=managed_agents,
                max_steps=max_steps,
                temperature=temperature,
                language=language,
                max_tokens=max_tokens,
                context_manager_config=context_manager_config,
                current_time=experiment_time,
                model_factory=model_factory,
                user_id=user_id,
                prompt_components=prompt_components,
            )

        # Run agent (sync wrapper for Langfuse's sync task protocol)
        loop = asyncio.new_event_loop()
        try:
            result: AgentRunResult = loop.run_until_complete(
                run_agent_with_tracking(agent_run_info)
            )
        finally:
            loop.close()

        context_items = agent_run_info.agent_config.context_items or []
        system_prompt_text = render_precompact_system_prompt(context_items)
        model_config = agent_run_info.model_config_list[0] if agent_run_info.model_config_list else None
        try:
            from provenance.parity_snapshot import build_agent_run_info_parity_snapshot
        except ImportError:
            from ..provenance.parity_snapshot import build_agent_run_info_parity_snapshot
        parity_snapshot = build_agent_run_info_parity_snapshot(
            agent_run_info,
            language=language,
            template_version=prompt_template_version,
            template_source=prompt_template_source,
            resource_support=resource_support,
            intentional_empty_resources=intentional_empty_resources,
        )
        try:
            from tools.web_evidence import build_web_evidence
        except ImportError:
            from ..tools.web_evidence import build_web_evidence
        web_evidence = build_web_evidence(
            result.steps,
            task_query=question,
            answer_candidate=result.final_answer,
        )

        return {
            "final_answer": result.final_answer,
            "step_count": result.step_count,
            "total_input_tokens": result.total_input_tokens,
            "total_api_input_tokens": result.total_api_input_tokens,
            "total_output_tokens": result.total_output_tokens,
            "errors": result.errors,
            "message_type_count": result.message_type_count,
            "steps": result.steps,
            "web_evidence": web_evidence,
            "system_prompt": system_prompt_text,
            "parity_snapshot": parity_snapshot,
            "model_config": {
                "model_name": model_config.model_name if model_config else "",
                "url": model_config.url if model_config else "",
                "temperature": model_config.temperature if model_config else None,
                "max_tokens": model_config.max_tokens if model_config else None,
                "model_factory": model_config.model_factory if model_config else None,
            } if model_config else {},
            "agent_config": {
                "name": agent_run_info.agent_config.name,
                "max_steps": agent_run_info.agent_config.max_steps,
                "tools": [
                    tool.class_name if hasattr(tool, "class_name") else str(tool)
                    for tool in (agent_run_info.agent_config.tools or [])
                ],
                "managed_agents": [
                    agent.name
                    for agent in (agent_run_info.agent_config.managed_agents or [])
                ],
                "context_processing_mode": (
                    agent_run_info.agent_config.context_manager_config.policy_layers.platform[
                        "processing_mode"
                    ]
                    if isinstance(
                        agent_run_info.agent_config.context_manager_config.policy_layers.platform,
                        dict,
                    )
                    else getattr(
                        agent_run_info.agent_config.context_manager_config.policy_layers.platform,
                        "processing_mode",
                        "passthrough",
                    )
                ),
                "user_id": user_id,
                "context_item_types": [
                    str(getattr(item, "type", "unknown"))
                    for item in context_items
                ],
                "context_items": [
                    {
                        "id": item.id,
                        "type": str(getattr(item.type, "value", item.type)),
                        "content": item.content,
                        "priority": item.priority,
                        "source": list(item.source),
                        "metadata": item.metadata,
                    }
                    for item in context_items
                ],
            },
            "compression": {
                "calls": result.compression_calls,
                "deterministic_compaction_calls": (
                    result.deterministic_compaction_calls
                ),
                "input_tokens": result.compression_input_tokens,
                "output_tokens": result.compression_output_tokens,
                "summary_cache_hits": result.summary_cache_hits,
                "summary_cache_types": result.summary_cache_types,
                "total_uncompressed_est_tokens": result.total_uncompressed_est_tokens,
            },
            "provider_cache": _provider_cache_result(result),
            "latency": {
                "wall_clock_seconds": result.wall_clock_seconds,
                "step_durations": result.step_durations,
                "total_step_duration_seconds": round(sum(result.step_durations), 3),
            },
            "peak_context": {
                "peak_context_tokens": result.peak_context_tokens,
                "peak_context_step": result.peak_context_step,
            },
            "token_saving": {
                "total_uncompressed_est_tokens": result.total_uncompressed_est_tokens,
                "total_input_tokens": result.total_input_tokens,
                "compression_overhead_tokens": (
                    result.compression_input_tokens + result.compression_output_tokens
                ),
                "net_token_saving": getattr(result, "net_token_saving", 0),
            },
            "budget_evidence": {
                "over_soft_budget": result.over_soft_budget,
                "over_hard_budget": result.over_hard_budget,
                "compression_triggered": (
                    result.compression_calls > 0
                    or result.deterministic_compaction_calls > 0
                ),
                "peak_context_tokens": result.peak_context_tokens,
                "peak_context_step": result.peak_context_step,
                "max_raw_context_tokens": result.max_raw_context_tokens,
                "processing_mode": result.processing_mode,
                "soft_budget_tokens": (
                    result.soft_budget_tokens
                    or _get_budget_threshold(agent_run_info, "soft")
                ),
                "hard_budget_tokens": (
                    result.hard_budget_tokens
                    or _get_budget_threshold(agent_run_info, "hard")
                ),
                "total_input_tokens": result.total_input_tokens,
                "total_uncompressed_est_tokens": result.total_uncompressed_est_tokens,
            },
        }

    return task


def _provider_cache_result(result: AgentRunResult) -> dict:
    """Build provider-reported prefix-cache metrics without inferred hits."""
    available_calls = result.provider_cache_available_calls
    cached_tokens = result.provider_cached_input_tokens
    uncached_tokens = result.provider_uncached_input_tokens
    provider_input_tokens = cached_tokens + uncached_tokens
    statuses = sorted(result.provider_cache_statuses)
    if available_calls:
        status = "available"
    elif "unavailable" in statuses:
        status = "unavailable"
    else:
        status = "unsupported"
    return {
        "status": status,
        "available_calls": available_calls,
        "hit_calls": result.provider_cache_hit_calls,
        "provider_prefix_hit_rate": (
            round(result.provider_cache_hit_calls / available_calls, 4)
            if available_calls
            else None
        ),
        "provider_cached_tokens": cached_tokens,
        "provider_input_tokens": provider_input_tokens,
        "provider_cached_input_ratio": (
            round(cached_tokens / provider_input_tokens, 4)
            if provider_input_tokens
            else None
        ),
        "metrics_sources": sorted(result.provider_cache_metrics_sources),
    }


def make_run_evaluators(metric_names: list[str] = None):
    """Factory: create run-level aggregate evaluators.

    Args:
        metric_names: List of per-item metric names to aggregate.
                      Defaults to common metrics.

    Returns:
        A list of run evaluator functions.
    """
    if metric_names is None:
        metric_names = ["exact_match", "em", "f1", "numeric_answer", "keyword_match"]

    def aggregate(*, item_results, **kwargs):
        """Compute aggregate metrics across all items."""
        from langfuse.experiment import Evaluation

        if not item_results:
            return []

        results = []

        # Aggregate each known metric
        for metric in metric_names:
            values = []
            for r in item_results:
                for ev in r.evaluations:
                    if ev.name == metric and isinstance(ev.value, (int, float)):
                        values.append(ev.value)
            if values:
                avg = sum(values) / len(values)
                results.append(Evaluation(
                    name=f"avg_{metric}",
                    value=round(avg, 4),
                    comment=f"over {len(values)} items",
                ))

        # Always aggregate token stats from output dict
        input_tokens = [
            r.output.get("total_input_tokens", 0)
            for r in item_results
            if isinstance(r.output, dict)
        ]
        output_tokens = [
            r.output.get("total_output_tokens", 0)
            for r in item_results
            if isinstance(r.output, dict)
        ]
        steps = [
            r.output.get("step_count", 0)
            for r in item_results
            if isinstance(r.output, dict)
        ]

        if input_tokens:
            results.append(Evaluation(
                name="avg_input_tokens",
                value=round(sum(input_tokens) / len(input_tokens), 0),
            ))
        if output_tokens:
            results.append(Evaluation(
                name="avg_output_tokens",
                value=round(sum(output_tokens) / len(output_tokens), 0),
            ))
        if steps:
            results.append(Evaluation(
                name="avg_steps",
                value=round(sum(steps) / len(steps), 1),
            ))

        return results

    return [aggregate]
