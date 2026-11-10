# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Business logic for the ephemeral NL2Skill runtime."""

import threading
from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Any

from nexent.core.agents.agent_model import AgentHistory, AgentRunInfo
from nexent.core.agents.context import ContextManagerConfig
from runtime.adapters.nexent.runner import agent_run
from nexent.core.utils.observer import MessageObserver

from management.services.model.run_budget import _resolve_input_budget
from management.services.model.run_budget import _resolve_context_budget
from management.services.model.run_bindings import create_model_config_list
from management.services.agent.preparation.inputs import join_minio_file_description_to_query
from management.services.skill.creation import create_nl2skill_agent_config
from management.services.agent.context import build_authorized_context_input
from contracts.constants.constants import LANGUAGE
from contracts.constants.constants import MODEL_CONFIG_MAPPING
from contracts.conversation import HistoryItem
from contracts.agent import NL2SkillRunRequest
from management.db.model.repository import get_model_by_model_id
from management.services.configuration.tenant.settings import tenant_config_manager
from management.services.model.names import get_model_name_from_config
from management.services.skill.nl2skill import _extract_target_files, _normalize_draft_snapshot, project_creation_events
from management.services.skill.prompt import (
    get_nl2skill_prompt_template,
)
from runtime.thread_management import runtime_thread_manager
from management.services.model.run_controls import resolve_creator_model, validate_selected_record, preflight_turn_controls

def _convert_history(history: list[HistoryItem] | None) -> list[AgentHistory]:
    return [
        AgentHistory(role=item.role, content=item.content)
        for item in history or []
        if item.role in {"user", "assistant"}
    ]


def _skill_history_turns(history: list[AgentHistory]) -> list[dict[str, Any]]:
    """Preserve failed or unanswered turns without restoring legacy AgentMemory."""
    turns: list[dict[str, Any]] = []
    pending_user = False
    for index, entry in enumerate(history):
        if entry.role == "assistant" and pending_user:
            turns[-1]["assistant_final_answer"] = entry.content
            pending_user = False
            continue
        turns.append({
            "user_message": entry.content if entry.role == "user" else "",
            "assistant_final_answer": entry.content if entry.role == "assistant" else "",
            "attachments": [],
            "user_message_id": -(index * 2 + 1),
            "assistant_message_id": -(index * 2 + 2),
        })
        pending_user = entry.role == "user"
    return turns


def _resolve_model_for_nl2skill(
    tenant_id: str,
    model_id: int | None,
    model_config_list: list,
) -> tuple[str, str, dict]:
    """Resolve the model configuration for NL2Skill.

    Args:
        tenant_id: Current tenant ID
        model_id: Optional model ID override from request
        model_config_list: Full model config list for the tenant

    Returns:
        Tuple of (cite_name, model_name, model_config) for the resolved model

    Raises:
        ValueError: When no valid model is found
    """
    if model_id is not None:
        # Use the explicitly requested model
        model_info = get_model_by_model_id(model_id, tenant_id)
        validate_selected_record(model_info)
        if model_info:
            return (
                model_info["display_name"],
                model_info["display_name"],
                model_info,
            )
        raise ValueError(f"Requested model_id {model_id} not found for tenant")

    # Use the tenant-configured LLM model (MODEL_CONFIG_MAPPING["llm"])
    llm_key = MODEL_CONFIG_MAPPING["llm"]
    llm_config = tenant_config_manager.get_model_config(
        key=llm_key, tenant_id=tenant_id
    )
    if llm_config:
        # Check if there's a matching model in model_config_list with cite_name "main_model"
        for config in model_config_list:
            if config.cite_name == "main_model":
                return ("main_model", config.model_name, llm_config)
        # Fallback: construct from config
        model_name = get_model_name_from_config(llm_config) if llm_config.get(
            "model_name") else ""
        if model_name:
            return ("main_model", model_name, llm_config)

    # Final fallback: use first model in list
    if model_config_list:
        first = model_config_list[0]
        return (first.cite_name, first.model_name, {})

    raise ValueError("No LLM model configured for tenant")


async def build_nl2skill_run_info(
    request: NL2SkillRunRequest,
    tenant_id: str,
    language: str,
) -> AgentRunInfo:
    """Build all request-scoped objects for one NL2Skill turn."""

    template_language = LANGUAGE["EN"] if language == LANGUAGE["EN"] else LANGUAGE["ZH"]
    preflight_turn_controls(request, tenant_id)
    target_files = _extract_target_files(request.query, request.draft_snapshot)
    draft_snapshot = _normalize_draft_snapshot(request.draft_snapshot)
    final_query = await join_minio_file_description_to_query(
        minio_files=request.minio_files,
        query=request.query,
        history=request.history,
        language=template_language,
    )
    template = get_nl2skill_prompt_template(
        language=template_language,
        existing_skill=draft_snapshot,
        user_request=final_query,
        target_files=target_files,
    )
    model_config_list = await create_model_config_list(tenant_id)
    if not model_config_list:
        raise ValueError("No LLM model configured for tenant")

    # Resolve model: use request.model_id if provided, otherwise use tenant-configured model
    cite_name, model_name, model_info = _resolve_model_for_nl2skill(
        tenant_id=tenant_id,
        model_id=request.model_id,
        model_config_list=model_config_list,
    )

    agent_config = create_nl2skill_agent_config(
        system_prompt=template.get("system_prompt", ""),
        model_name=cite_name,
    )
    if request.model_id is not None or request.generation_config is not None:
        model_info = resolve_creator_model(
            model_config_list, agent_config, tenant_id, request.model_id,
            request.generation_config.model_dump(exclude_unset=True) if request.generation_config else None,
            model_info,
        )
    input_budget, capacity_snapshot, resolved_capacity = _resolve_input_budget(model_info)
    context_budget = _resolve_context_budget(
        capacity_snapshot=resolved_capacity, tenant_id=tenant_id,
        agent_requested_output_tokens=None, request_requested_output_tokens=None,
    )
    agent_config.capacity_snapshot = capacity_snapshot
    agent_config.context_budget_snapshot = context_budget
    # The SDK consumes the same selected-model capacity snapshot as the root.
    agent_config.context_manager_config = ContextManagerConfig(
        token_threshold=context_budget.compaction_trigger_threshold_tokens if context_budget else input_budget,
        context_window_tokens=(resolved_capacity.context_window_tokens if resolved_capacity else None) or input_budget,
        effective_input_limit_tokens=context_budget.effective_input_limit_tokens if context_budget else 0,
        compaction_trigger_threshold_tokens=context_budget.compaction_trigger_threshold_tokens if context_budget else 0,
        compaction_target_tokens=context_budget.compaction_target_tokens if context_budget else 0,
    )
    run_info = AgentRunInfo(
        query=template.get("user_prompt") or final_query,
        model_config_list=model_config_list,
        observer=MessageObserver(lang=template_language),
        agent_config=agent_config,
        capacity_snapshot=capacity_snapshot,
        context_budget_snapshot=context_budget,
        history=_convert_history(request.history),
        stop_event=threading.Event(),
        enable_planning=False,
        sandbox_config=None,
        redis_client=None,
    )
    run_info.context_input = build_authorized_context_input(
        run_info, historical_context={"conversation_turns": _skill_history_turns(run_info.history)},
    )
    return run_info


async def create_nl2skill_stream(
    request: NL2SkillRunRequest,
    tenant_id: str,
    language: str,
) -> AsyncIterator[str]:
    """Run the transitional local executor and project its observer events."""
    run_info = await build_nl2skill_run_info(request, tenant_id, language)
    target_files = _extract_target_files(request.query, request.draft_snapshot)

    async def generate() -> AsyncIterator[str]:
        try:
            events = agent_run(run_info, thread_manager=runtime_thread_manager)
            async with aclosing(events), aclosing(project_creation_events(events, target_files)) as stream:
                async for event in stream:
                    yield event
        finally:
            run_info.stop_event.set()

    return generate()
