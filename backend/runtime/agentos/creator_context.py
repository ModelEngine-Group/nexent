# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Restore the versioned context budget shared by request-owned creator runs."""

from fastapi import HTTPException
from pydantic import ValidationError

from contracts.agentos import PreparedCreatorRun
from nexent.core.agents.agent_model import AgentConfig
from nexent.core.agents.context import ContextManagerConfig
from nexent.core.models.capacity_budget import ContextBudgetSnapshot


def apply_creator_budget(payload: PreparedCreatorRun, agent: AgentConfig) -> ContextBudgetSnapshot | None:
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
    return budget
