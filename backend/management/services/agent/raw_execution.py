# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Prepare original internal Northbound requests without changing their policy."""

from contracts.agent import AgentRequest
from contracts.agentos import CompatibilityConversationRun, PreparedEphemeralRun
from infrastructure.agentos_identity import ServicePrincipal
from management.services.agent.agentos_events import present_ephemeral_stream
from management.services.agent.preparation.run import create_agent_run_info
from management.services.agent.run import build_run_preparation_arguments
from management.services.agent.subscription import _prepare_legacy_conversation


async def prepare_raw_debug(request: AgentRequest, actor: ServicePrincipal) -> PreparedEphemeralRun | None:
    # Complex branches keep their original preparation until their complete resource plan is portable.
    if not request.is_debug or request.entrypoint or request.workbench is not None or request.knowledge_scope is not None:
        return None
    await _prepare_legacy_conversation(request, actor.user_id, actor.tenant_id, "zh", None)
    arguments = build_run_preparation_arguments(request, actor.user_id, actor.tenant_id, "zh", False)
    arguments.update(conversation_id=0, export_evaluation=True, export_debug_planning=bool(request.enable_plan))
    snapshot = await create_agent_run_info(**arguments)
    if snapshot is None:
        return None
    return PreparedEphemeralRun(
        **snapshot.model_dump(exclude={"conversation_id"}),
        run_id=request.__dict__["_debug_run_id"].removeprefix("debug-"), debug=True,
        runtime_metadata=request.__dict__.get("_runtime_metadata_snapshot", {}),
    )


async def forward_raw_run(payload: CompatibilityConversationRun, actor: ServicePrincipal):
    from management.services.agent.runtime_client import _agentos_client

    if payload.resume or payload.idempotency_key is not None or payload.claimed_run_id is not None or payload.user_message != "new":
        raise ValueError("Invalid raw Northbound handoff")
    request = AgentRequest.model_validate(payload.request)
    client = _agentos_client()
    prepared = await prepare_raw_debug(request, actor)
    if prepared is None:
        # Use the original request, before time-prefix and preparation mutations.
        return await client.run_conversation(payload.model_copy(update={"preparation": "legacy"}), actor.user_id, actor.tenant_id)
    response = await client.run_ephemeral(prepared, actor.user_id, actor.tenant_id)
    public = present_ephemeral_stream(response, actor.user_id, prepared.run_id)
    if public.status_code == 200:
        public.headers["Connection"] = "keep-alive"
        if request.conversation_id is not None:
            public.headers["conversation_id"] = str(request.conversation_id)
    return public
