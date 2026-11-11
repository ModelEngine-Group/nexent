# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Prepare original internal Northbound requests without changing their policy."""

from contracts.agent import AgentRequest
from contracts.agentos import CompatibilityConversationRun, PreparedEphemeralRun
from infrastructure.agentos_identity import ServicePrincipal
from management.services.agent.agentos_events import debug_preparation_events, present_ephemeral_stream
from management.services.agent.preparation.evaluation_snapshot import PreparedDebug, _turn_model_generation
from management.services.agent.preparation.run import create_agent_run_info
from management.services.agent.run import build_run_preparation_arguments
from management.services.agent.subscription import _prepare_legacy_conversation


async def prepare_raw_debug(request: AgentRequest, actor: ServicePrincipal) -> PreparedDebug | None:
    if not request.is_debug:
        return None
    context = await _prepare_legacy_conversation(request, actor.user_id, actor.tenant_id, "zh", None, export_resources=True)
    arguments = build_run_preparation_arguments(request, actor.user_id, actor.tenant_id, "zh", False)
    arguments.update(conversation_id=0, export_evaluation=True, export_debug_planning=bool(request.enable_plan))
    if context.workbench is None and arguments.get("runtime_generation_config"):
        arguments["turn_generation"] = _turn_model_generation(request)
    if context.workbench is not None:
        from management.services.agent.workbench import PreparedWorkbench

        arguments["prepared_workbench"] = PreparedWorkbench(
            context.workbench, request.__dict__["_runtime_mount_plan"], 0, 0, context.knowledge,
            request.__dict__.get("_runtime_knowledge_tools"),
        )
    elif context.knowledge is not None:
        arguments["authorized_knowledge_tools"] = {
            (node["agent_id"], node["version_no"]): context.knowledge.managed_tool_overrides.get(node["agent_name"], {})
            for node in context.knowledge_tree
        }
    snapshot = await create_agent_run_info(**arguments)
    if snapshot is None:
        return None
    payload = PreparedEphemeralRun(
        **snapshot.model_dump(exclude={"conversation_id"}),
        run_id=request.__dict__["_debug_run_id"].removeprefix("debug-"), debug=True,
        runtime_metadata=request.__dict__.get("_runtime_metadata_snapshot", {}),
        native_knowledge=True if context.knowledge is not None and context.workbench is None else None,
    )
    return PreparedDebug(payload, context.knowledge, context.workbench)


async def forward_raw_run(payload: CompatibilityConversationRun, actor: ServicePrincipal):
    from management.services.agent.runtime_client import _agentos_client, _run_prepared_debug

    if payload.resume or payload.idempotency_key is not None or payload.claimed_run_id is not None or payload.user_message != "new":
        raise ValueError("Invalid raw Northbound handoff")
    request = AgentRequest.model_validate(payload.request)
    client = _agentos_client()
    prepared = await prepare_raw_debug(request, actor)
    if prepared is None:
        # Use the original request, before time-prefix and preparation mutations.
        return await client.run_conversation(payload.model_copy(update={"preparation": "legacy"}), actor.user_id, actor.tenant_id)
    response = await _run_prepared_debug(client, prepared, actor.user_id, actor.tenant_id)
    public = present_ephemeral_stream(
        response, actor.user_id, prepared.payload.run_id, opening_events=debug_preparation_events(prepared),
    )
    if public.status_code == 200:
        public.headers["Connection"] = "keep-alive"
        if request.conversation_id is not None:
            public.headers["conversation_id"] = str(request.conversation_id)
    return public
