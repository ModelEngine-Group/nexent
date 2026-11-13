# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Resolve a signed Runtime proposal callback against its authorized public turn."""

from contracts.agentos import AgentRunLookup, AgentRunReference
from contracts.errors.exceptions import AppException, RuntimeUpstreamError
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb.agent_admission import AdmissionScopeError
from management.db.conversation import prepared_turn as store
from management.services.agent.runtime_client import _agentos_client
from management.services.automation.proposal import AutomationToolRuntimeContext, agent_loop_automation_tool_adapter
from nexent.core.concurrency import run_blocking


def _read_context(turn) -> AutomationToolRuntimeContext | None:
    source = store.automation_source(turn)
    if source is None:
        return None
    return AutomationToolRuntimeContext(
        tenant_id=turn.tenant_id, user_id=turn.user_id,
        conversation_id=turn.reference.conversation_id, **source,
    )


async def create_automation_proposal(reference: AgentRunReference, actor: ServicePrincipal) -> dict | None:
    async def read(name, fn, *args):
        return await run_blocking(name, fn, *args, lane="control-io", owner="management")

    turn = await read("agentos-automation-turn", store.automation_turn, reference, actor.user_id, actor.tenant_id)
    if turn is None:
        return None
    try:
        state = await _agentos_client().inspect_run(
            AgentRunLookup(**reference.model_dump()), actor.user_id, actor.tenant_id,
        )
    except RuntimeUpstreamError as exc:
        if exc.status_code == 404:
            return None
        raise
    if (state.run_id != reference.run_id or state.conversation_id != reference.conversation_id
            or state.status != "running" or state.cancellation_requested):
        return None
    if turn.assistant_message_id is None:
        try:
            turn = await read("agentos-automation-confirm", store.confirm_turn, turn)
        except (AdmissionScopeError, AppException, store.PreparedTurnConflict):
            return None
        if turn is None:
            return None
    context = await read("agentos-automation-source", _read_context, turn)
    if context is None:
        return None
    return await agent_loop_automation_tool_adapter.create_proposal(context, "")
