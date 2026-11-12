# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Own standard execution for old background callers without an automation source."""

from contracts.agent import AgentRequest
from contracts.agentos import AgentRunReference, TrackedBackgroundResult
from contracts.conversation import MessageSource
from contracts.errors.exceptions import (
    AgentBackgroundError, RuntimeMetadataVersionConflict, RuntimeServiceUnavailableError, RuntimeUpstreamError,
    WorkbenchConfigVersionConflict, WorkbenchError,
)
from infrastructure.rdb.agent_admission import (
    AdmissionRequestConflict, AdmissionScopeError, claim_conversation_run, conversation_claim_scope,
    conversation_request_fingerprint, set_conversation_admission,
)
from management.db.conversation import prepared_turn as store
from management.db.conversation.repository import get_conversation, get_prepared_projection_receipt
from management.services.agent.preparation.evaluation_snapshot import prepare_conversation_snapshot, prepare_native_knowledge
from management.services.agent.prepared_projection import resume_assistant_projection
from management.services.conversation.service import get_current_run_user_message_id
from nexent.core.concurrency import run_blocking


async def _io(task, function, *args, **kwargs):
    return await run_blocking(task, function, *args, lane="control-io", owner="management", **kwargs)


async def _prepare(request, reference, actor):
    conversation = await _io("background-compat-owner", get_conversation, reference.conversation_id,
                             user_id=actor.user_id, tenant_id=actor.tenant_id)
    if conversation is None:
        raise AdmissionScopeError
    workbench = None
    knowledge = None
    if request.entrypoint == "workbench":
        from management.services.agent.prepared_turn import _prepare_workbench

        workbench = await _prepare_workbench(request, reference.conversation_id, actor.user_id, actor.tenant_id)
        if workbench is None:
            return None
    elif isinstance(conversation.get("workbench_config"), dict):
        return None
    elif request.knowledge_scope is not None or isinstance(conversation.get("knowledge_scope"), dict):
        knowledge = await _io("background-compat-knowledge", prepare_native_knowledge,
                              request, conversation, actor.user_id, actor.tenant_id)
    current = await _io("background-compat-history-boundary", get_current_run_user_message_id,
                        reference.conversation_id, actor.user_id)
    history = {"current_user_message_id": current} if type(current) is int else {}
    snapshot = await prepare_conversation_snapshot(
        request, reference, actor.user_id, actor.tenant_id, owned_conversation=conversation,
        workbench=workbench, native_knowledge=knowledge, preserve_shared_reasoning=True, **history,
    )
    if snapshot is None:
        return None
    user_turn = {
        "query": request.query, "minio_files": request.minio_files, "agent_id": snapshot.resource.agent_id,
        "chat_mode": "planning" if request.enable_plan else "execution", "automation": None,
    }
    if snapshot.memory_enabled:
        user_turn["memory_agent_id"] = snapshot.resource.agent_id
    if request.metadata is not None:
        user_turn["metadata_update"] = {"expected_version": snapshot.runtime_metadata_version - 1, "value": request.metadata}
    if workbench is not None:
        user_turn["workbench_update"] = {
            "config": workbench.config.model_dump(mode="json"), "expected_version": workbench.previous_version,
            "version": workbench.version,
        }
        if snapshot.resource.workbench_skill_refs:
            user_turn["workbench_skill_root"] = {
                "agent_id": snapshot.resource.agent_id, "version_no": snapshot.resource.version_no,
            }
    elif knowledge is not None and request.knowledge_scope is not None:
        user_turn["knowledge_update"] = {
            "expected": conversation.get("knowledge_scope"), "value": knowledge.resolution.desired_scope,
        }
    return snapshot, user_turn


async def _project(client, turn):
    receipt = await _io(
        "background-compat-receipt", get_prepared_projection_receipt,
        projection_run_id=turn.reference.run_id, conversation_id=turn.reference.conversation_id,
        message_index=turn.message_index, message_source=MessageSource.AUTOMATION,
        user_id=turn.user_id, tenant_id=turn.tenant_id,
    )
    if receipt is not None:
        if receipt[0] != turn.assistant_message_id:
            raise RuntimeServiceUnavailableError("Background projection receipt does not match its reserved message")
        message_id, status, chunks = receipt[0], receipt[1], 0
    else:
        projected = await resume_assistant_projection(
            client.resume, turn.reference, turn.user_id, turn.tenant_id, message_index=turn.message_index,
            message_source=MessageSource.AUTOMATION, assistant_message_id=turn.assistant_message_id,
            **({"memory_agent_id": turn.memory_agent_id} if turn.memory_agent_id is not None else {}),
        )
        message_id, status, chunks = projected.assistant_message_id, projected.status, projected.chunks
    await _io("background-compat-finished", store.close_turn, turn)
    if status != "completed":
        raise AgentBackgroundError("AGENTOS_BACKGROUND_NOT_COMPLETED")
    return TrackedBackgroundResult(**turn.reference.model_dump(), assistant_message_id=message_id, chunks=chunks)


async def run_background(client, payload, actor):
    request = AgentRequest.model_validate(payload.request)
    request.enable_automation_tool = False
    reference = AgentRunReference(conversation_id=request.conversation_id, run_id=payload.run_id)
    scope = conversation_claim_scope(actor.user_id, actor.tenant_id, "compatibility-background-" + payload.run_id)
    fingerprint = conversation_request_fingerprint(payload.model_dump(mode="json"))
    try:
        claim = await _io("background-compat-claim", claim_conversation_run, scope, fingerprint,
                          actor.user_id, actor.tenant_id, requested_run_id=payload.run_id)
        if not claim.acquired:
            if claim.status == "rejected":
                return None
            turn = await _io("background-compat-restore", store.read_background_turn,
                             scope, reference, actor.user_id, actor.tenant_id)
            if turn is None:
                raise AgentBackgroundError("AGENTOS_BACKGROUND_NOT_COMPLETED")
            if turn.assistant_message_id is None:
                state = await client.inspect_run(reference, actor.user_id, actor.tenant_id)
                if (state.run_id, state.conversation_id) != (reference.run_id, reference.conversation_id):
                    raise RuntimeServiceUnavailableError("AgentOS returned a different background run")
                if state.status == "starting" and state.latest_event_id is None:
                    raise AgentBackgroundError("AGENTOS_BACKGROUND_NOT_COMPLETED")
            else:
                return await _project(client, turn)
        else:
            try:
                prepared = await _prepare(request, reference, actor)
                if prepared is not None:
                    snapshot, user_turn = prepared
                    boundary = 2 * sum(item.role == "user" for item in request.history or [])
                    turn = await _io("background-compat-stage", store.stage_turn, scope, reference,
                                     actor.user_id, actor.tenant_id, boundary, user_turn, omitted_user=True, background_run=True)
            except Exception:
                # This guarded update cannot reject a marker committed by a racing stage.
                await _io("background-compat-prepare-rejected", set_conversation_admission,
                          scope, reference.run_id, actor.user_id, actor.tenant_id,
                          conversation_id=None, journal_available=False)
                raise
            if prepared is None:
                await _io("background-compat-unsupported", set_conversation_admission,
                          scope, reference.run_id, actor.user_id, actor.tenant_id,
                          conversation_id=None, journal_available=False)
                return None
            try:
                admitted = await client.start_prepared_run(snapshot, actor.user_id, actor.tenant_id)
            except RuntimeUpstreamError as exc:
                from management.services.agent.prepared_turn import _definitive_rejection

                if _definitive_rejection(exc):
                    await _io("background-compat-rejected", store.close_turn, turn)
                raise
            if admitted != reference:
                raise RuntimeServiceUnavailableError("AgentOS returned a different background run")
        try:
            confirmed = await _io("background-compat-confirm", store.confirm_turn, turn)
        except (AdmissionScopeError, store.PreparedTurnConflict, RuntimeMetadataVersionConflict,
                WorkbenchConfigVersionConflict, WorkbenchError):
            from management.services.agent.prepared_turn import _cancel_unbound_turn

            await _cancel_unbound_turn(client, turn)
            raise
        if confirmed is None:
            raise RuntimeServiceUnavailableError("Background admission is no longer pending")
        return await _project(client, confirmed)
    except AdmissionScopeError as exc:
        raise AgentBackgroundError("AGENTOS_RUN_NOT_FOUND", status_code=404) from exc
    except (AdmissionRequestConflict, store.PreparedTurnConflict) as exc:
        raise AgentBackgroundError("AGENTOS_BACKGROUND_SOURCE_MISMATCH") from exc
