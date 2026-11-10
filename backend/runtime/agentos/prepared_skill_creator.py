# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Materialize a signed NL2Skill request inside Runtime."""

from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError

from contracts.agentos import PreparedSkillCreatorRun
from infrastructure.agentos_identity import ServicePrincipal
from nexent.core.agents.agent_model import AgentConfig, AgentHistory, AgentRunInfo
from nexent.core.agents.context import ContextItemInput, ContextItemType, ContextManagerConfig
from nexent.core.agents.context_input import build_authorized_context_input
from nexent.core.agents.prompt.meta import compose_nl2skill
from nexent.core.models.capacity_budget import ContextBudgetSnapshot
from nexent.core.utils.observer import MessageObserver, ProcessType
from runtime.adapters.nexent.factory import build_run_info
from runtime.agentos.prepared_attachments import materialize_evaluation_input
from runtime.agentos.prepared_evaluation import _materialize_model

NL2SKILL_NAME = "__skill_creator__"


def get_nl2skill_prompt_template(
    language: str = "zh", existing_skill: dict[str, Any] | None = None,
    user_request: str = "", target_files: list[str] | None = None,
) -> dict[str, str]:
    return compose_nl2skill(
        "en" if language == "en" else "zh", existing_skill=existing_skill,
        user_request=user_request, target_files=target_files or [],
    )


def create_nl2skill_agent_config(
    system_prompt: str,
    model_name: str,
) -> AgentConfig:
    """Create one request-scoped skill creator without persistent state."""

    if not system_prompt.strip():
        raise ValueError("Skill creation system prompt must not be empty")

    return AgentConfig(
        name=NL2SKILL_NAME,
        display_name="技能创建助手",
        description="Ephemeral natural-language skill builder",
        # A non-empty mapping disables CodeAgent's default English templates.
        # Keep the rendered prompt in context_items to preserve literal Jinja syntax.
        prompt_templates={
            "system_prompt": "",
            "planning": {
                "initial_plan": "",
                "update_plan_pre_messages": "",
                "update_plan_post_messages": "",
            },
            "managed_agent": {"task": "", "report": ""},
            "final_answer": {"pre_messages": "", "post_messages": "{{task}}"},
        },
        tools=[],
        max_steps=5,
        model_name=model_name,
        output_protocol="final_envelope",
        provide_run_summary=False,
        context_items=[
            ContextItemInput(
                id="system:nl2skill_prompt",
                type=ContextItemType.SYSTEM,
                content={"text": system_prompt},
                source=("prompt:nl2skill",),
                priority=100,
                metadata={"authority": "platform", "layout_order": -1},
            )
        ],
        enable_planning=False,
    )


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


class _SkillCreatorObserver(MessageObserver):
    def add_message(self, agent_name, process_type, content, **kwargs):
        # The SDK worker emits a legacy, unscoped error as a final answer before raising.
        # Runtime reports the worker failure separately using the AgentOS terminal.
        if not agent_name and process_type == ProcessType.FINAL_ANSWER:
            return
        super().add_message(agent_name, process_type, content, **kwargs)


def prepare_skill_creator_run(payload: PreparedSkillCreatorRun, actor: ServicePrincipal) -> AgentRunInfo:
    if payload.model.provider_body_revision is not None or payload.model.root_generation is not None:
        raise HTTPException(status_code=422, detail={"code": "AGENTOS_RESOURCE_UNSUPPORTED"})
    model = _materialize_model(payload.model, actor, None)
    query, _, _ = materialize_evaluation_input(payload.input, actor, payload.language)
    template = get_nl2skill_prompt_template(
        payload.language, existing_skill=payload.draft.model_dump() if payload.draft else None,
        user_request=query, target_files=payload.target_files,
    )
    agent = create_nl2skill_agent_config(template.get("system_prompt", ""), model.cite_name)
    try:
        budget = (ContextBudgetSnapshot.model_validate(payload.context_budget_snapshot)
                  if payload.context_budget_snapshot is not None else None)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "AGENTOS_RESOURCE_UNSUPPORTED"}) from exc
    agent.capacity_snapshot = payload.capacity_snapshot
    agent.context_budget_snapshot = budget
    agent.context_manager_config = ContextManagerConfig(
        token_threshold=budget.compaction_trigger_threshold_tokens if budget else payload.input_budget,
        context_window_tokens=payload.context_window_tokens,
        effective_input_limit_tokens=budget.effective_input_limit_tokens if budget else 0,
        compaction_trigger_threshold_tokens=budget.compaction_trigger_threshold_tokens if budget else 0,
        compaction_target_tokens=budget.compaction_target_tokens if budget else 0,
    )
    info = build_run_info(
        language=payload.language, observer=_SkillCreatorObserver(lang=payload.language),
        query=template.get("user_prompt") or query, agent_config=agent,
        model_config_list=[model], enable_planning=False, sandbox_config=None, redis_client=None,
        capacity_snapshot=payload.capacity_snapshot, context_budget_snapshot=budget,
        workspace_run_id=payload.run_id, user_id=actor.user_id, tenant_id=actor.tenant_id,
        history=[AgentHistory(role=item.role, content=item.content) for item in payload.input.history],
    )
    info.context_input = build_authorized_context_input(
        info, historical_context={"conversation_turns": _skill_history_turns(info.history)},
    )
    return info
