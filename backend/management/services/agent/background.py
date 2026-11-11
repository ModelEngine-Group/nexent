# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Prepare and project old background requests at their Management owner."""

import asyncio
import logging

from fastapi import HTTPException
from pydantic import ValidationError

from contracts.agent import AgentRequest
from contracts.agentos import AgentRunReference, AgentStop, BackgroundRun, TrackedBackgroundResult
from contracts.errors.exceptions import RuntimeServiceTimeoutError, RuntimeServiceUnavailableError, RuntimeUpstreamError
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb.agent_admission import AdmissionScopeError
from infrastructure.rdb.conversation_state import conversation_belongs_to
from management.db.automation import repository as runs
from management.db.conversation import prepared_turn as turns
from management.services.agent.context import strip_current_time_prefix
from management.services.agent.preparation.evaluation_snapshot import prepare_conversation_snapshot
from nexent.core.concurrency import run_blocking

logger = logging.getLogger(__name__)


async def _io(task, function, *args, **kwargs):
    return await run_blocking(task, function, *args, lane="control-io", owner="management", **kwargs)


async def _project(client, reference, record):
    from management.services.automation.runner import AgentAutomationRunner

    projected = await AgentAutomationRunner()._project_prepared_run(client, reference, record)
    if projected.status != "completed":
        raise HTTPException(status_code=409, detail={"code": "AGENTOS_BACKGROUND_NOT_COMPLETED"})
    return TrackedBackgroundResult(
        **reference.model_dump(), assistant_message_id=projected.assistant_message_id, chunks=projected.chunks,
    )


async def dispatch_background(payload: BackgroundRun, actor: ServicePrincipal) -> TrackedBackgroundResult:
    from management.services.agent.runtime_client import _agentos_client

    try:
        request = AgentRequest.model_validate(payload.request)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "AGENTOS_INVALID_AGENT_REQUEST"}) from exc
    conversation_id = request.conversation_id
    if request.is_debug or type(conversation_id) is not int or conversation_id <= 0:
        raise HTTPException(status_code=422, detail={"code": "AGENTOS_INVALID_AGENT_REQUEST"})
    if not await _io(
        "background-owner", conversation_belongs_to, conversation_id, user_id=actor.user_id, tenant_id=actor.tenant_id,
    ):
        raise HTTPException(status_code=404, detail={"code": "AGENTOS_RUN_NOT_FOUND"})
    reference = AgentRunReference(run_id=payload.run_id, conversation_id=conversation_id)
    client = _agentos_client()
    try:
        record = await _io(
            "background-source-run", runs.get_run_by_runtime_id, payload.run_id, actor.tenant_id, actor.user_id,
            conversation_id=conversation_id,
        )
        if record is not None and record["status"] not in {"RUNNING", "SUCCEEDED"}:
            raise HTTPException(status_code=409, detail={"code": "AGENTOS_BACKGROUND_NOT_COMPLETED"})
        if record is None or record.get("user_message_id") is None or record.get("generated_prompt") is None:
            return await client.run_tracked_background(payload.model_copy(update={"preparation": "legacy"}), actor.user_id, actor.tenant_id)
        if (record["conversation_id"], record["runtime_run_id"], record["generated_prompt"]) != (
            conversation_id, payload.run_id, strip_current_time_prefix(request.query),
        ):
            raise HTTPException(status_code=409, detail={"code": "AGENTOS_BACKGROUND_SOURCE_MISMATCH"})
        try:
            source = await _io(
                "background-source-message", turns.read_saved_user_turn_by_id,
                conversation_id, actor.user_id, actor.tenant_id, record["user_message_id"],
                record["generated_prompt"], request.minio_files,
            )
        except AdmissionScopeError as exc:
            raise HTTPException(status_code=404, detail={"code": "AGENTOS_RUN_NOT_FOUND"}) from exc
        except turns.PreparedTurnConflict as exc:
            raise HTTPException(status_code=409, detail={"code": "AGENTOS_BACKGROUND_SOURCE_MISMATCH"}) from exc
        if source.message_source != "AUTOMATION":
            raise HTTPException(status_code=422, detail={"code": "AGENTOS_INVALID_BACKGROUND_SOURCE"})
        if record["status"] == "SUCCEEDED" and record.get("assistant_message_id") is not None:
            return TrackedBackgroundResult(**reference.model_dump(), assistant_message_id=record["assistant_message_id"], chunks=0)
        if record["status"] != "RUNNING":
            raise HTTPException(status_code=409, detail={"code": "AGENTOS_BACKGROUND_NOT_COMPLETED"})
        if record.get("projection_message_index") is not None:
            return await _project(client, reference, record)

        request.enable_automation_tool = False
        snapshot = await prepare_conversation_snapshot(
            request, reference, actor.user_id, actor.tenant_id, current_user_message_id=source.message_id,
        )
        if snapshot is None:
            return await client.run_tracked_background(payload.model_copy(update={"preparation": "legacy"}), actor.user_id, actor.tenant_id)
        pending = await _io("background-record-projection", runs.update_run, record["run_id"], {
            "projection_message_index": source.message_index + 1,
            "projection_memory_agent_id": snapshot.resource.agent_id if snapshot.memory_enabled else None,
        }, actor.user_id, expected_statuses=["RUNNING"], tenant_id=actor.tenant_id)
        if pending is None:
            raise HTTPException(status_code=409, detail={"code": "AGENTOS_BACKGROUND_NOT_COMPLETED"})
        record.update(pending)
        admitted = await client.start_prepared_run(snapshot, actor.user_id, actor.tenant_id)
        if admitted != reference:
            raise RuntimeServiceUnavailableError("AgentOS returned a different background run")
        return await _project(client, reference, record)
    except asyncio.CancelledError:
        try:
            await asyncio.wait_for(client.stop_run(
                AgentStop(**reference.model_dump(), prevent_start=True), actor.user_id, actor.tenant_id,
            ), timeout=3)
        except (TimeoutError, RuntimeServiceTimeoutError, RuntimeServiceUnavailableError, RuntimeUpstreamError):
            logger.warning("Background disconnect cancellation deferred run_id=%s", payload.run_id)
        raise
