# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Serve cursorless compatibility replays from Runtime-owned stream state."""

from fastapi import HTTPException
from starlette.responses import JSONResponse

from contracts.agentos import AgentLegacyResume
from contracts.constants.environment import ENABLE_AGENT_WORKBENCH
from contracts.errors.exceptions import ForbiddenError, WorkbenchError
from infrastructure.agent_stream_channels import streaming_channel_manager
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.legacy_stream_replay import replay_legacy_stream
from infrastructure.rdb.conversation_state import read_legacy_resume_state
from infrastructure.redis.run_state import runtime_state_service
from nexent.core.concurrency import run_blocking
from runtime.executions import agent_run_manager


async def resume_legacy_run(payload: AgentLegacyResume, actor: ServicePrincipal):
    try:
        return await resume_legacy_conversation(payload.conversation_id, actor, workbench=payload.workbench)
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except WorkbenchError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code}) from exc


async def resume_legacy_conversation(conversation_id: int, actor: ServicePrincipal, *, workbench: bool):
    if workbench and not ENABLE_AGENT_WORKBENCH:
        raise WorkbenchError("WORKBENCH_DISABLED", status_code=404)
    try:
        stored_workbench, assistant = await run_blocking(
            "agentos-legacy-resume-state", read_legacy_resume_state,
            conversation_id, actor.user_id, actor.tenant_id, lane="control-io", owner="runtime",
        )
    except PermissionError as exc:
        raise ForbiddenError(str(exc)) from exc
    if stored_workbench and not ENABLE_AGENT_WORKBENCH:
        raise WorkbenchError("WORKBENCH_DISABLED", status_code=404)
    if assistant is None:
        return JSONResponse({"status": None, "message": "Stream already None: no_assistant_message"})

    status, last_unit = assistant
    channel = streaming_channel_manager.get_channel(conversation_id, actor.user_id)
    if status != "streaming" and (channel is None or channel.is_completed):
        return JSONResponse({"status": status, "message": f"Stream already {status}: backend_{status}"})

    local_run = agent_run_manager.get_agent_run_info(conversation_id, actor.user_id)
    remote_state = await runtime_state_service.get_run_state_async(
        user_id=actor.user_id, conversation_id=conversation_id,
    )
    is_remote_running = remote_state.get("status") == "running"
    if local_run is None and not is_remote_running:
        return JSONResponse({"status": "completed", "message": "Agent finished during disconnection"})
    return replay_legacy_stream(
        conversation_id, actor.user_id, last_unit + 1 if last_unit is not None else 0,
        channel_manager=streaming_channel_manager, state_service=runtime_state_service,
        is_remote_running=is_remote_running,
    )
