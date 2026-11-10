# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Own prepared public turns and reconcile Runtime output through signed AgentOS."""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException
from starlette.responses import JSONResponse

from contracts.agentos import AgentResume, AgentRunLookup, AgentRunReference, AgentStop
from contracts.constants.constants import DEFAULT_EN_TITLE, DEFAULT_ZH_TITLE
from contracts.conversation import MessageSource
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import (
    AppException, ForbiddenError, RunModelControlsError, RuntimeMetadataVersionConflict,
    RuntimeServiceUnavailableError, RuntimeUpstreamError, ValidationError, WorkbenchConfigVersionConflict, WorkbenchError,
)
from infrastructure.agent_tool_config import AUTOMATION_PROPOSAL_TOOL
from infrastructure.rdb.agent_admission import AdmissionScopeError, conversation_claim_scope, set_conversation_admission
from management.db.conversation import prepared_turn as store
from management.db.conversation.repository import get_conversation, get_prepared_projection_receipt
from management.services.agent.agentos_events import knowledge_scope_event_content, present_public_resume
from management.services.agent.context import strip_current_time_prefix
from management.services.agent.preparation.evaluation_snapshot import prepare_conversation_snapshot
from management.services.agent.prepared_projection import resume_assistant_projection
from nexent.core.concurrency import run_blocking

logger = logging.getLogger(__name__)
_STAGED_TIMEOUT = timedelta(minutes=1)
_ACTIVE = {"starting", "running"}
_REJECTED_STATUS = {400, 401, 403, 404, 409, 413, 422}


async def _io(name, fn, *args, **kwargs):
    return await run_blocking(name, fn, *args, lane="control-io", owner="management", **kwargs)


def is_prepared_candidate(payload, request):
    return bool(
        not payload.resume and not request.is_debug
        and (request.entrypoint == "workbench" or (request.agent_id and not request.entrypoint))
        and (request.conversation_id is None or request.conversation_id > 0)
    )


def with_submission_key(payload):
    return payload if payload.idempotency_key is not None else payload.model_copy(
        update={"idempotency_key": f"prepared-{uuid4().hex}"},
    )


def _not_owned():
    return HTTPException(status_code=404, detail={"code": "AGENTOS_RUN_NOT_FOUND"})


def active_turn_conflict():
    return HTTPException(
        status_code=409, detail={"code": "AGENTOS_RUN_ALREADY_ACTIVE"}, headers={"X-Stream-Status": "conflict"},
    )


def _metadata_conflict(error):
    return AppException(ErrorCode.CHAT_METADATA_VERSION_CONFLICT, details={"current_version": error.current_version})


def _workbench_conflict(error: WorkbenchConfigVersionConflict) -> HTTPException:
    return HTTPException(status_code=409, detail={
        "code": "WORKBENCH_CONFIG_VERSION_CONFLICT", "current_version": error.current_version,
    })


async def _prepare_workbench(request, conversation_id, user_id, tenant_id):
    from management.services.agent.workbench import prepare_portable_workbench

    conversation = None
    if conversation_id is not None:
        conversation = await _io("prepared-workbench-owner", get_conversation, conversation_id,
                                 user_id=user_id, tenant_id=tenant_id)
        if conversation is None:
            raise _not_owned()
        if not isinstance(conversation.get("workbench_config"), dict):
            raise HTTPException(status_code=403, detail="Conversation belongs to a different chat entrypoint")
    return await _io("prepared-workbench-plan", prepare_portable_workbench, request, conversation, user_id, tenant_id)


def _definitive_rejection(error):
    if error.status_code in _REJECTED_STATUS:
        return True
    if error.status_code == 503:
        try:
            payload = json.loads(error.content)
            return payload["detail"]["code"] == "AGENTOS_EVENT_STORE_UNAVAILABLE"
        except (TypeError, ValueError, KeyError):
            pass
    return False


async def reject_unstaged_turn(payload, user_id, tenant_id):
    scope = conversation_claim_scope(user_id, tenant_id, payload.idempotency_key)
    await _io("prepared-turn-reject-claim", set_conversation_admission, scope, payload.claimed_run_id, user_id, tenant_id,
              conversation_id=None, journal_available=False)


async def start_turn(
    payload, request, user_id, tenant_id, client, *, include_journal_controls=True, allow_metadata_update=False,
):
    run_id = payload.claimed_run_id
    scope = conversation_claim_scope(user_id, tenant_id, payload.idempotency_key)
    initial_title = None
    try:
        conversation_id = request.conversation_id
        workbench = None
        if request.entrypoint == "workbench":
            workbench = await _prepare_workbench(request, conversation_id, user_id, tenant_id)
            if workbench is None:
                return None
        if conversation_id is None:
            conversation_id = await _io("prepared-turn-sequence", store.allocate_conversation_id)
            request = request.model_copy(update={"conversation_id": conversation_id})
            boundary = 0
            initial_title = DEFAULT_EN_TITLE if payload.language == "en" else DEFAULT_ZH_TITLE
            options = {"new_conversation": True}
        else:
            boundary = await _io("prepared-turn-boundary", store.next_message_index,
                                 conversation_id, user_id, tenant_id)
            options = {"before_message_index": boundary}
        if allow_metadata_update:
            options["allow_metadata_update"] = True
        if workbench is not None:
            options["workbench"] = workbench
        reference = AgentRunReference(conversation_id=conversation_id, run_id=run_id)
        snapshot = await prepare_conversation_snapshot(
            request, reference, user_id, tenant_id, language=payload.language, timezone=payload.timezone, **options,
        )
        if snapshot is None:
            return None
        if (initial_title is None
                and await client.find_active_run(reference.conversation_id, user_id, tenant_id) is not None):
            raise active_turn_conflict()
        automation = None
        if request.enable_automation_tool and any(
            tool.tool_id == AUTOMATION_PROPOSAL_TOOL for tool in snapshot.resource.tools
        ):
            tool_params = request.tool_params
            if workbench is not None and workbench.knowledge is not None:
                tool_params = workbench.knowledge.tool_params
            automation = {
                "agent_id": snapshot.resource.agent_id,
                "agent_version_no": snapshot.resource.version_no,
                "model_id": (workbench.config.model_id if workbench is not None else None) or request.model_id,
                "tool_params": tool_params.model_dump(mode="json") if tool_params else None,
                "has_attachments": bool(request.minio_files),
            }
        creation = {"initial_title": initial_title} if initial_title is not None else {}
        user_turn = {
            "query": strip_current_time_prefix(request.query), "minio_files": request.minio_files,
            "chat_mode": "planning" if request.enable_plan else "execution",
            "agent_id": snapshot.resource.agent_id if workbench is not None else request.agent_id,
            "automation": automation,
        }
        if workbench is not None:
            user_turn["workbench_update"] = {
                "config": workbench.config.model_dump(mode="json"), "expected_version": workbench.previous_version,
                "version": workbench.version,
            }
        if request.metadata is not None and (allow_metadata_update or workbench is not None):
            user_turn["metadata_update"] = {
                "expected_version": snapshot.runtime_metadata_version - 1, "value": request.metadata,
            }
        turn = await _io("prepared-turn-stage", store.stage_turn, scope, reference, user_id, tenant_id, boundary,
                         user_turn, **creation)
    except Exception as exc:
        await reject_unstaged_turn(payload, user_id, tenant_id)
        if isinstance(exc, (AdmissionScopeError, ForbiddenError)):
            raise _not_owned() from exc
        if isinstance(exc, store.PreparedTurnConflict):
            raise active_turn_conflict() from exc
        if isinstance(exc, RuntimeMetadataVersionConflict):
            raise _metadata_conflict(exc) from exc
        if isinstance(exc, WorkbenchConfigVersionConflict):
            raise _workbench_conflict(exc) from exc
        if isinstance(exc, WorkbenchError):
            raise HTTPException(status_code=exc.status_code, detail={"code": exc.code}) from exc
        if isinstance(exc, RunModelControlsError):
            status = {"model_not_available": 404, "model_unavailable": 409, "model_type_invalid": 400}.get(exc.code, 422)
            raise HTTPException(status_code=status, detail={"code": exc.code}) from exc
        if isinstance(exc, ValidationError):
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        raise

    try:
        admitted = await client.start_prepared_run(snapshot, user_id, tenant_id)
    except RuntimeUpstreamError as exc:
        if _definitive_rejection(exc):
            await _io("prepared-turn-rejected", store.close_turn, turn)
        if exc.status_code == 409:
            exc.headers["X-Stream-Status"] = "conflict"
        raise
    if admitted != reference:
        raise RuntimeServiceUnavailableError("AgentOS returned a different conversation run")
    try:
        confirmed = await _io("prepared-turn-confirm", store.confirm_turn, turn)
    except (AdmissionScopeError, store.PreparedTurnConflict, RuntimeMetadataVersionConflict,
            WorkbenchConfigVersionConflict, WorkbenchError) as exc:
        await _cancel_unbound_turn(client, turn)
        if isinstance(exc, AdmissionScopeError):
            raise _not_owned() from exc
        if isinstance(exc, RuntimeMetadataVersionConflict):
            raise _metadata_conflict(exc) from exc
        if isinstance(exc, WorkbenchConfigVersionConflict):
            raise _workbench_conflict(exc) from exc
        if isinstance(exc, WorkbenchError):
            raise HTTPException(status_code=exc.status_code, detail={"code": exc.code}) from exc
        raise active_turn_conflict() from exc
    if confirmed is None:
        raise RuntimeServiceUnavailableError("Prepared conversation admission is no longer pending")
    return await _stream_turn(
        confirmed, client, metadata_version=snapshot.runtime_metadata_version, created=initial_title is not None,
        include_journal_controls=include_journal_controls, workbench=workbench,
    )


async def _cancel_unbound_turn(client, turn):
    try:
        await client.stop_run(
            AgentStop(**turn.reference.model_dump(), prevent_start=True), turn.user_id, turn.tenant_id,
        )
    except RuntimeUpstreamError as exc:
        if exc.status_code != 404:
            raise
    await _io("prepared-turn-unbound", store.close_turn, turn)


async def _stream_turn(
    turn, client, *, metadata_version=None, resumed=False, created=False, include_journal_controls=True, workbench=None,
):
    reference = turn.reference
    cursor = AgentResume(**reference.model_dump())
    upstream = await client.resume(cursor, turn.user_id, turn.tenant_id)

    async def on_terminal():
        try:
            await _finish_projection(turn, client)
        except Exception as exc:
            logger.warning("Deferred terminal conversation projection run_id=%s error=%s",
                           reference.run_id, type(exc).__name__)

    opening_events = []
    if workbench is not None:
        opening_events.append({"type": "workbench_config_resolved", "content": {
            "config_version": workbench.version,
            "schema_version": workbench.config.schema_version,
            "mode": workbench.config.mode,
            "agent_mounts": [mount.model_dump(mode="json") for mount in workbench.config.agent_mounts],
        }})
        if workbench.knowledge is not None:
            opening_events.append({
                "type": "knowledge_scope_resolved", "content": knowledge_scope_event_content(workbench.knowledge),
            })
    response = present_public_resume(
        upstream, cursor, turn.user_id, on_terminal=on_terminal, created=created,
        include_journal_controls=include_journal_controls, opening_events=opening_events,
    )
    if workbench is not None:
        response.headers["X-Workbench-Config-Version"] = str(workbench.version)
    response.headers["conversation_id"] = str(reference.conversation_id)
    if include_journal_controls:
        response.headers["run_id"] = reference.run_id
    if metadata_version is not None:
        response.headers["X-Runtime-Metadata-Version"] = str(metadata_version)
    if resumed and response.status_code == 200:
        response.headers["X-Stream-Status"] = "resumed"
    return response


async def find_pending_turn(conversation_id, user_id, tenant_id):
    try:
        return await _io("prepared-turn-lookup", store.pending_turn, conversation_id, user_id, tenant_id)
    except AdmissionScopeError:
        # No pending run is visible. Preserve the compatibility route's denial.
        return None


async def resume_turn(turn, client):
    if turn.assistant_message_id is None:
        return JSONResponse({"status": "streaming", "message": "Waiting for Runtime admission"})
    return await _stream_turn(turn, client, resumed=True)


async def _finish_projection(turn, client):
    reference = turn.reference
    receipt = await _io(
        "prepared-turn-receipt", get_prepared_projection_receipt,
        projection_run_id=reference.run_id, conversation_id=reference.conversation_id,
        message_index=turn.message_index, message_source=MessageSource.CHAT, user_id=turn.user_id, tenant_id=turn.tenant_id,
    )
    if receipt is not None and receipt[0] != turn.assistant_message_id:
        raise RuntimeServiceUnavailableError("Prepared conversation receipt does not match the reserved message")
    if receipt is None:
        await resume_assistant_projection(
            client.resume, reference, turn.user_id, turn.tenant_id, message_index=turn.message_index,
            message_source=MessageSource.CHAT, assistant_message_id=turn.assistant_message_id,
        )
    await _io("prepared-turn-finished", store.close_turn, turn)


async def reconcile_turn(turn, client):
    reference = turn.reference
    lookup = AgentRunLookup(**reference.model_dump())
    fenced_missing_run = False
    try:
        state = await client.inspect_run(lookup, turn.user_id, turn.tenant_id)
    except RuntimeUpstreamError as exc:
        if exc.status_code != 404:
            raise
        if datetime.now(timezone.utc) - turn.staged_at < _STAGED_TIMEOUT:
            return
        try:
            state = await client.stop_run(
                AgentStop(**reference.model_dump(), prevent_start=True), turn.user_id, turn.tenant_id,
            )
        except RuntimeUpstreamError as stop_error:
            if stop_error.status_code != 404:
                raise
            await _io("prepared-turn-gone", store.close_turn, turn, failure_status="failed")
            return
        fenced_missing_run = True
    if (state.run_id, state.conversation_id) != (reference.run_id, reference.conversation_id):
        raise RuntimeServiceUnavailableError("AgentOS returned a different conversation run")
    if turn.assistant_message_id is None:
        if state.status == "stopped" and state.latest_event_id is None and (
            fenced_missing_run or (state.cancellation_requested and state.resource_versions is None)
        ):
            await _io("prepared-turn-unstarted", store.close_turn, turn)
            return
        if state.status == "starting" and state.latest_event_id is None:
            # The ledger is created before the output journal. Confirm only after
            # the Runtime acknowledgement or visible output/terminal state.
            return
        try:
            turn = await _io("prepared-turn-recovered", store.confirm_turn, turn)
        except AdmissionScopeError:
            await _io("prepared-turn-outside-scope", store.close_turn, turn, failure_status="failed")
            return
        except (store.PreparedTurnConflict, RuntimeMetadataVersionConflict, WorkbenchConfigVersionConflict, WorkbenchError):
            await _cancel_unbound_turn(client, turn)
            return
        if turn is None:
            return
    if state.status in _ACTIVE:
        return
    try:
        await _finish_projection(turn, client)
    except RuntimeUpstreamError as exc:
        if exc.status_code not in {404, 410}:
            raise
        failure_status = "stopped" if state.status == "stopped" else "failed"
        await _io("prepared-turn-log-expired", store.close_turn, turn, failure_status=failure_status)


async def _recover_pending_turns():
    from management.services.agent.runtime_client import _agentos_client

    async def recover(turn):
        try:
            await asyncio.wait_for(reconcile_turn(turn, _agentos_client()), timeout=30)
        except Exception as exc:
            logger.warning("Deferred conversation recovery run_id=%s error=%s",
                           turn.reference.run_id, type(exc).__name__)

    after_run_id = ""
    while True:
        try:
            turns = await _io("prepared-turn-recovery-list", store.pending_turns, after_run_id, 4)
            after_run_id = turns[-1].reference.run_id if turns else ""
            await asyncio.gather(*(recover(turn) for turn in turns))
        except Exception as exc:
            logger.warning("Unable to read pending conversation turns error=%s", type(exc).__name__)
        await asyncio.sleep(1 if after_run_id else 3)


@asynccontextmanager
async def prepared_turn_lifespan():
    recovery = asyncio.create_task(_recover_pending_turns(), name="prepared-public-turn-recovery")
    try:
        yield
    finally:
        recovery.cancel()
        await asyncio.gather(recovery, return_exceptions=True)
