# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Agent SSE subscriptions, replay and conversation preparation."""

import asyncio
import json
from contracts.exceptions import UnauthorizedError
import logging
import uuid
from copy import (
    deepcopy,
)
from http import (
    HTTPStatus,
)
from typing import (
    Any,
    Dict,
)

from agents.agent_run_manager import (
    AgentRunAlreadyActiveError,
    AgentRunConcurrencyExceededError,
    agent_run_manager,
)
from consts.const import DEFAULT_EN_TITLE, DEFAULT_ZH_TITLE, ENABLE_AGENT_WORKBENCH, LANGUAGE, MESSAGE_ROLE, RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS, STREAM_STATUS_EVENT
from contracts.error_code import ErrorCode, RuntimeMetadataValidationCode
from contracts.exceptions import AppException, ConversationNotFoundError, ForbiddenError, RuntimeCapacityExceededError, RuntimeMetadataValidationError, RuntimeMetadataVersionConflict, RuntimeQueueTimeoutError, ValidationError, WorkbenchError
from contracts.models import AgentRequest, ConversationKnowledgeScopeRequest
from management.db.agent.repository import search_agent_info_by_agent_id
from management.db.conversation.repository import resolve_conversation_runtime_metadata
from fastapi import (
    Request,
)
from fastapi.responses import (
    JSONResponse,
    StreamingResponse,
)
from management.services.agent.context import (
    build_agent_run_context,
    prepend_current_time,
)
from management.services.agent.execution import (
    _agent_run_identifier,
    _agent_stream_producer_tasks,
    _consume_agent_stream_producer,
)
from management.services.agent.run import (
    apply_workbench_runtime_plan,
    generate_stream,
    save_messages,
)
from management.services.agent.stream import (
    safe_agent_stream_error_chunk as _safe_agent_stream_error_chunk,
)
from nexent.core.agents.run_agent import (
    DeferredAgentRun,
)
from nexent.core.concurrency import (
    ManagedTaskSpec,
    ThreadCapacityExceeded,
    ThreadQueueTimedOut,
    run_blocking,
)
from nexent.monitor import (
    agent_monitoring_context,
)
from management.services.conversation.service import (
    create_new_conversation,
    get_conversation_service,
    get_last_unit_for_message,
    get_latest_assistant_message,
    update_conversation_agent_id_service,
    update_conversation_chat_mode_service,
    update_conversation_knowledge_scope_service,
    update_conversation_workbench_and_metadata_service,
    update_conversation_workbench_config_service,
    update_message_status,
)
from management.services.knowledge_base.scope import (
    build_runtime_knowledge_resources,
    resolve_knowledge_scope,
)
from management.services.agent.run_state import (
    runtime_state_service,
)
from infrastructure.streaming.channels import (
    streaming_channel_manager,
)
from infrastructure.concurrency import (
    runtime_thread_manager,
)
from management.utils.request_context import get_user_language
from infrastructure.serialization.runtime_metadata import (
    validate_runtime_metadata,
)

logger = logging.getLogger(__name__)


def _resolve_user_tenant_language(
    http_request: Request | None = None,
    user_id: str | None = None,
    tenant_id: str | None = None,
):
    """Require established identity and read the request language preference."""
    if not user_id or not tenant_id:
        raise UnauthorizedError("Authenticated user and tenant are required")
    return user_id, tenant_id, get_user_language(http_request)


def _detect_resume_position(
    conversation_id: int,
    user_id: str,
) -> Dict[str, Any]:
    """
    Determine the position to resume streaming from.

    This function queries the database to check if there's an in-progress
    streaming message for the given conversation. Used when frontend reconnects
    after tab switch.

    Returns:
        Dict containing:
            - should_resume: bool - whether we should resume streaming
            - message_id: int - the assistant message ID
            - message_status: str - current status (streaming/completed/failed/stopped)
            - resume_from_unit_index: int - the unit index to resume from
            - reason: str - explanation of the decision
    """
    latest_msg = get_latest_assistant_message(conversation_id, user_id)

    if latest_msg is None:
        return {
            "should_resume": False,
            "message_id": None,
            "message_status": None,
            "resume_from_unit_index": None,
            "reason": "no_assistant_message",
        }

    message_status = latest_msg.get("status")
    message_id = latest_msg["message_id"]

    # Check if channel exists and is still active
    channel = streaming_channel_manager.get_channel(conversation_id, user_id)
    channel_active = channel is not None and not channel.is_completed

    if message_status == "streaming":
        # Backend still running - get last unit position
        last_unit = get_last_unit_for_message(message_id)
        resume_from = last_unit["unit_index"] + 1 if last_unit else 0
        return {
            "should_resume": True,
            "message_id": message_id,
            "message_status": message_status,
            "resume_from_unit_index": resume_from,
            "resume_message_id": message_id,
            "reason": "backend_streaming",
        }
    elif channel_active:
        # Message shows completed but channel is still active - resume to get remaining chunks
        # This handles edge case where message status was updated but channel not yet cleaned up
        last_unit = get_last_unit_for_message(message_id)
        resume_from = last_unit["unit_index"] + 1 if last_unit else 0
        return {
            "should_resume": True,
            "message_id": message_id,
            "message_status": message_status,
            "resume_from_unit_index": resume_from,
            "resume_message_id": message_id,
            "reason": "channel_active",
        }
    else:
        # Backend finished - no more chunks to stream
        return {
            "should_resume": False,
            "message_id": message_id,
            "message_status": message_status,
            "resume_from_unit_index": None,
            "resume_message_id": None,
            "reason": f"backend_{message_status}",
        }


async def run_agent_stream(
    agent_request: AgentRequest,
    http_request: Request,
    user_id: str = None,
    tenant_id: str = None,
    skip_user_save: bool = False,
    resume: bool = False,
):
    """
    Start an agent run and stream responses.
    The gateway must supply the authenticated user and tenant for every entrypoint.

    Args:
        resume: If True, check for existing streaming message and continue from where it left off
    """
    if agent_request.entrypoint == "workbench" and not ENABLE_AGENT_WORKBENCH:
        raise WorkbenchError("WORKBENCH_DISABLED", status_code=404)

    resolved_user_id, resolved_tenant_id, language = _resolve_user_tenant_language(
        http_request=http_request,
        user_id=user_id,
        tenant_id=tenant_id,
    )
    if not resume:
        from management.services.model import run_controls

        run_controls.validate_agent_model_selection(
            agent_request, resolved_tenant_id, search_agent_info_by_agent_id
        )
    if agent_request.is_debug and not resume:
        # Debug executions deliberately do not create conversations, so they
        # need a transient identifier for lifecycle operations such as stop.
        agent_request.__dict__["_debug_run_id"] = f"debug-{uuid.uuid4().hex}"

    # Inject current time in the user's timezone so the LLM can answer
    # time-related questions correctly. The SDK strips this prefix before
    # sending AGENT_NEW_RUN to the frontend, so the user message display
    # does not show the time marker.
    agent_request.query = prepend_current_time(
        agent_request.query,
        http_request.headers.get("x-user-timezone") if http_request else None,
        language=language,
    )  # pragma: no cover

    conversation = None
    if not agent_request.is_debug and agent_request.conversation_id is not None:
        conversation = get_conversation_service(
            conversation_id=agent_request.conversation_id,
            user_id=resolved_user_id,
            tenant_id=resolved_tenant_id,
        )
        if conversation is None:
            raise ForbiddenError(
                "Conversation is not accessible to the current identity"
            )
        if not ENABLE_AGENT_WORKBENCH and conversation.get("workbench_config"):
            raise WorkbenchError("WORKBENCH_DISABLED", status_code=404)
        if not resume:
            is_workbench_conversation = isinstance(
                conversation.get("workbench_config"), dict
            )
            if is_workbench_conversation != (agent_request.entrypoint == "workbench"):
                raise ForbiddenError(
                    "Conversation belongs to a different chat entrypoint"
                )

    canonical_workbench = None
    if agent_request.entrypoint == "workbench" and not resume:
        from management.services.agent.workbench import (
            assert_workbench_version,
            resolve_workbench_config,
        )

        requested_workbench = agent_request.workbench
        if conversation is not None:
            assert_workbench_version(
                conversation, agent_request.expected_workbench_config_version
            )
            if requested_workbench is None and isinstance(
                conversation.get("workbench_config"), dict
            ):
                from contracts.models import WorkbenchSessionConfig

                requested_workbench = WorkbenchSessionConfig.model_validate(
                    conversation["workbench_config"]
                )
            if (
                agent_request.metadata is not None
                and agent_request.expected_metadata_version is not None
            ):
                current_metadata_version = int(
                    conversation.get("runtime_metadata_version") or 0
                )
                if agent_request.expected_metadata_version != current_metadata_version:
                    raise AppException(
                        ErrorCode.CHAT_METADATA_VERSION_CONFLICT,
                        details={"current_version": current_metadata_version},
                    )
        if requested_workbench is None:
            raise ValidationError("Workbench configuration is required")
        canonical_workbench, resolved_tree = resolve_workbench_config(
            requested_workbench,
            tenant_id=resolved_tenant_id,
            is_debug=bool(agent_request.is_debug),
            user_id=resolved_user_id,
        )
        apply_workbench_runtime_plan(
            agent_request, canonical_workbench, resolved_tree, resolved_tenant_id
        )
        if conversation is not None:
            assert_workbench_version(
                conversation,
                agent_request.expected_workbench_config_version,
            )

    if not resume:
        run_controls.preflight_agent_turn_controls(
            agent_request, resolved_tenant_id, search_agent_info_by_agent_id
        )

    metadata_supplied = "metadata" in agent_request.model_fields_set
    metadata_update_requested = metadata_supplied and agent_request.metadata is not None
    if metadata_update_requested:
        try:
            validate_runtime_metadata(agent_request.metadata)
        except RuntimeMetadataValidationError as exc:
            error_code = (
                ErrorCode.CHAT_METADATA_TOO_LARGE
                if exc.code == RuntimeMetadataValidationCode.METADATA_TOO_LARGE
                else ErrorCode.CHAT_METADATA_INVALID
            )
            raise AppException(
                error_code,
                details={"reason": exc.code.value},
            ) from exc
    metadata_entrypoint = getattr(
        agent_request, "_runtime_metadata_entrypoint", "native"
    )
    if metadata_update_requested and metadata_entrypoint in {"native", "debug"}:
        agent_record = search_agent_info_by_agent_id(
            agent_id=agent_request.agent_id,
            tenant_id=resolved_tenant_id,
            version_no=agent_request.version_no or 0,
        )
        if not bool(agent_record.get("allow_chat_metadata", False)):
            raise AppException(ErrorCode.CHAT_METADATA_NOT_ALLOWED)

    raw_request_scope = (
        None if resume else getattr(agent_request, "knowledge_scope", None)
    )
    if isinstance(raw_request_scope, ConversationKnowledgeScopeRequest):
        request_scope = raw_request_scope
    elif isinstance(raw_request_scope, dict):
        request_scope = ConversationKnowledgeScopeRequest.model_validate(
            raw_request_scope
        )
    else:
        request_scope = None
    stored_scope = (
        conversation.get("knowledge_scope")
        if conversation and canonical_workbench is None
        else None
    )
    if not isinstance(stored_scope, dict):
        stored_scope = None
    source_scope = request_scope
    if source_scope is None and stored_scope is not None and not resume:
        source_scope = ConversationKnowledgeScopeRequest.model_validate(stored_scope)

    resolved_scope = None
    if source_scope is not None and not resume:
        if agent_request.agent_id is None:
            raise ValueError("agent_id is required when knowledge_scope is set")
        runtime_knowledge_tree = [
            deepcopy(dict(node))
            for node in getattr(
                getattr(agent_request, "_runtime_mount_plan", None),
                "knowledge_tree",
                (),
            )
        ]
        resolve_scope_kwargs = {}
        if runtime_knowledge_tree:
            resolve_scope_kwargs["runtime_agent_tree"] = runtime_knowledge_tree

        resolved_scope = await run_blocking(
            "resolve-runtime-knowledge-scope",
            resolve_knowledge_scope,
            scope=source_scope,
            agent_id=agent_request.agent_id,
            tenant_id=resolved_tenant_id,
            user_id=resolved_user_id,
            version_no=agent_request.version_no,
            is_debug=bool(agent_request.is_debug),
            request_tool_params=agent_request.tool_params,
            lane="control-io",
            owner="management.services.agent.run",
            **resolve_scope_kwargs,
        )
        agent_request.tool_params = resolved_scope.tool_params
        agent_request.__dict__["_runtime_knowledge_context"] = {
            "scope": build_runtime_knowledge_resources(resolved_scope),
        }
        agent_request.__dict__["_resolved_knowledge_scope_event"] = {
            "effective": {
                "local": {
                    "disabled": resolved_scope.local_disabled,
                    "knowledge_ids": resolved_scope.local_knowledge_ids,
                    "display_names": resolved_scope.local_display_names,
                },
                "aidp": {
                    "disabled": resolved_scope.aidp_disabled,
                    "kds_ids": resolved_scope.aidp_kds_ids,
                    "display_names": resolved_scope.aidp_display_names,
                },
            },
            "warnings": resolved_scope.warnings,
        }
        if resolved_scope.warnings:
            logger.warning(
                "Knowledge scope resolved with warnings conversation_id=%s warnings=%s",
                agent_request.conversation_id,
                resolved_scope.warnings,
            )
    # Auto-create conversation when conversation_id is not provided.
    # Skip in debug mode: debug runs are ephemeral and must not persist
    # conversations, titles, or messages to the user's history.
    is_new_conversation = False
    if agent_request.is_debug:
        logger.info(
            "Skipping conversation auto-create: is_debug=True (conversation_id=%s)",
            agent_request.conversation_id,
        )
    elif agent_request.conversation_id is None:
        default_title = (
            DEFAULT_EN_TITLE if language == LANGUAGE["EN"] else DEFAULT_ZH_TITLE
        )
        conversation_kwargs = {
            "title": default_title,
            "user_id": resolved_user_id,
            "agent_id": agent_request.agent_id,
            "chat_mode": "planning" if agent_request.enable_plan else "execution",
        }
        if canonical_workbench is not None:
            conversation_kwargs["workbench_config"] = canonical_workbench.model_dump(
                mode="json"
            )
        if resolved_scope is not None:
            conversation_kwargs["knowledge_scope"] = resolved_scope.desired_scope
        if metadata_update_requested:
            conversation_kwargs["runtime_metadata"] = agent_request.metadata or {}
        conversation_data = create_new_conversation(**conversation_kwargs)
        agent_request.conversation_id = conversation_data["conversation_id"]
        is_new_conversation = True
        logger.info(
            "Auto-created conversation_id=%s for user=%s (new conversation)",
            agent_request.conversation_id,
            resolved_user_id,
        )

    if not resume:
        joint_runtime_state = None
        if (
            canonical_workbench is not None
            and not is_new_conversation
            and metadata_update_requested
            and not agent_request.is_debug
        ):
            try:
                joint_runtime_state = update_conversation_workbench_and_metadata_service(
                    conversation_id=agent_request.conversation_id,
                    user_id=resolved_user_id,
                    config=canonical_workbench.model_dump(mode="json"),
                    expected_config_version=agent_request.expected_workbench_config_version,
                    metadata=agent_request.metadata or {},
                    expected_metadata_version=agent_request.expected_metadata_version,
                )
            except RuntimeMetadataVersionConflict as exc:
                raise AppException(
                    ErrorCode.CHAT_METADATA_VERSION_CONFLICT,
                    details={"current_version": exc.current_version},
                ) from exc
            conversation = {**(conversation or {}), **joint_runtime_state}
        elif (
            canonical_workbench is not None
            and not is_new_conversation
            and not agent_request.is_debug
        ):
            updated = update_conversation_workbench_config_service(
                conversation_id=agent_request.conversation_id,
                user_id=resolved_user_id,
                config=canonical_workbench.model_dump(mode="json"),
                expected_version=agent_request.expected_workbench_config_version,
                only_if_changed=True,
            )
            conversation = {**(conversation or {}), **updated}

        if canonical_workbench is not None and not agent_request.is_debug:
            workbench_state = (
                conversation_data if is_new_conversation else (conversation or {})
            )
            agent_request.__dict__["_workbench_config_version"] = int(
                workbench_state.get("workbench_config_version") or 0
            )

        if agent_request.is_debug:
            metadata_snapshot = (
                dict(agent_request.metadata or {}) if metadata_update_requested else {}
            )
            metadata_version = None
        elif is_new_conversation:
            metadata_snapshot = dict(
                conversation_data.get(
                    "runtime_metadata",
                    agent_request.metadata if metadata_update_requested else {},
                )
                or {}
            )
            metadata_version = int(
                conversation_data.get(
                    "runtime_metadata_version",
                    1 if metadata_update_requested else 0,
                )
                or 0
            )
        elif joint_runtime_state is not None:
            metadata_snapshot = dict(joint_runtime_state["runtime_metadata"] or {})
            metadata_version = int(joint_runtime_state["runtime_metadata_version"])
        elif not metadata_update_requested:
            metadata_snapshot = dict((conversation or {}).get("runtime_metadata") or {})
            metadata_version = int(
                (conversation or {}).get("runtime_metadata_version") or 0
            )
        else:
            try:
                resolved_metadata = resolve_conversation_runtime_metadata(
                    conversation_id=agent_request.conversation_id,
                    user_id=resolved_user_id,
                    request_metadata=agent_request.metadata,
                    update_requested=metadata_update_requested,
                    expected_version=agent_request.expected_metadata_version,
                )
            except ConversationNotFoundError as exc:
                raise AppException(
                    ErrorCode.CHAT_CONVERSATION_NOT_FOUND,
                ) from exc
            except RuntimeMetadataVersionConflict as exc:
                raise AppException(
                    ErrorCode.CHAT_METADATA_VERSION_CONFLICT,
                    details={"current_version": exc.current_version},
                ) from exc
            metadata_snapshot = resolved_metadata["runtime_metadata"]
            metadata_version = resolved_metadata["runtime_metadata_version"]

        agent_request.__dict__["_runtime_metadata_snapshot"] = metadata_snapshot
        agent_request.__dict__["_runtime_metadata_version"] = metadata_version

    if (
        not agent_request.is_debug
        and not is_new_conversation
        and agent_request.conversation_id is not None
    ):
        update_conversation_chat_mode_service(
            conversation_id=agent_request.conversation_id,
            chat_mode="planning" if agent_request.enable_plan else "execution",
            user_id=resolved_user_id,
        )

    if (
        request_scope is not None
        and resolved_scope is not None
        and not agent_request.is_debug
        and not resume
        and not is_new_conversation
        and agent_request.conversation_id is not None
        and agent_request.entrypoint != "workbench"
    ):
        update_conversation_knowledge_scope_service(
            conversation_id=agent_request.conversation_id,
            knowledge_scope=resolved_scope.desired_scope,
            user_id=resolved_user_id,
            tenant_id=resolved_tenant_id,
        )

    if (
        not agent_request.is_debug
        and not resume
        and not is_new_conversation
        and agent_request.conversation_id is not None
        and agent_request.agent_id is not None
        and agent_request.entrypoint != "workbench"
    ):
        update_conversation_agent_id_service(
            conversation_id=agent_request.conversation_id,
            agent_id=agent_request.agent_id,
            user_id=resolved_user_id,
        )

    # Resume mode: check for existing streaming message
    if resume:
        resume_info = _detect_resume_position(
            conversation_id=agent_request.conversation_id,
            user_id=resolved_user_id,
        )

        if not resume_info["should_resume"]:
            # Backend already finished
            return JSONResponse(
                status_code=HTTPStatus.OK,
                content={
                    "status": resume_info["message_status"],
                    "message": f"Stream already {resume_info['message_status']}: {resume_info['reason']}",
                },
            )

        # Check if the agent is still running by querying the agent_run_manager
        existing_run_info = agent_run_manager.get_agent_run_info(
            user_id=resolved_user_id, conversation_id=agent_request.conversation_id
        )
        run_state = await runtime_state_service.get_run_state_async(
            user_id=resolved_user_id,
            conversation_id=agent_request.conversation_id,
        )
        is_remote_running = run_state.get("status") == "running"

        if existing_run_info is None and not is_remote_running:
            # Agent has finished while frontend was disconnected
            # Update message status to completed if it's still streaming
            try:
                update_message_status(
                    message_id=resume_info["message_id"], status="completed"
                )
            except Exception:
                pass

            return JSONResponse(
                status_code=HTTPStatus.OK,
                content={
                    "status": "completed",
                    "message": "Agent finished during disconnection",
                },
            )

        # Agent is still running - subscribe to the channel to receive new chunks
        channel = streaming_channel_manager.get_channel(
            conversation_id=agent_request.conversation_id, user_id=resolved_user_id
        )
        last_unit_index = resume_info["resume_from_unit_index"] - 1

        def _resume_status_chunk(replay_chunk_count: int) -> str:
            payload = {
                "status": "resumed",
                "last_unit_index": last_unit_index,
                "replay_chunk_count": replay_chunk_count,
            }
            return f"data: {json.dumps(payload)}\n\n"

        def _resume_completed_chunk(status: str = "completed") -> str:
            payload = {
                "status": status,
                "last_unit_index": last_unit_index,
            }
            return f"data: {json.dumps(payload)}\n\n"

        if channel is None:
            if runtime_state_service.enabled and is_remote_running:

                async def redis_channel_stream():
                    replay_events = (
                        await runtime_state_service.read_stream_events_async(
                            user_id=resolved_user_id,
                            conversation_id=agent_request.conversation_id,
                        )
                    )
                    replay_chunk_count = len(replay_events)

                    yield STREAM_STATUS_EVENT
                    yield _resume_status_chunk(replay_chunk_count)

                    last_event_id = "0-0"
                    for event_id, chunk in replay_events:
                        last_event_id = event_id
                        if chunk:
                            yield chunk

                    while True:
                        events = (
                            await runtime_state_service.wait_for_stream_events_async(
                                user_id=resolved_user_id,
                                conversation_id=agent_request.conversation_id,
                                last_id=last_event_id,
                            )
                        )
                        for event_id, chunk in events:
                            last_event_id = event_id
                            if chunk:
                                yield chunk

                        stream_status = (
                            await runtime_state_service.get_stream_status_async(
                                user_id=resolved_user_id,
                                conversation_id=agent_request.conversation_id,
                            )
                        )
                        latest_run_state = (
                            await runtime_state_service.get_run_state_async(
                                user_id=resolved_user_id,
                                conversation_id=agent_request.conversation_id,
                            )
                        )
                        if stream_status.get("status") or latest_run_state.get(
                            "status"
                        ) in {
                            "completed",
                            "failed",
                            "stopped",
                        }:
                            break

                    terminal_status = (
                        stream_status.get("status")
                        or latest_run_state.get("status")
                        or "completed"
                    )
                    yield STREAM_STATUS_EVENT
                    yield _resume_completed_chunk(terminal_status)

                return StreamingResponse(
                    redis_channel_stream(),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Accel-Buffering": "no",
                        "X-Stream-Status": "resumed",
                        "X-Last-Unit-Index": str(resume_info["resume_from_unit_index"]),
                    },
                )

            # No channel exists, agent might be in a different state
            return JSONResponse(
                status_code=HTTPStatus.OK,
                content={
                    "status": "streaming",
                    "message": "Stream channel not found",
                },
            )

        # Subscribe to the channel and stream chunks to the frontend
        async def channel_stream():
            # Include the current buffer size so frontend knows how many chunks to skip
            replay_chunk_count = channel.history_size if channel else 0

            # Emit status event first with chunk count for skip tracking
            yield STREAM_STATUS_EVENT
            yield _resume_status_chunk(replay_chunk_count)

            # Use subscribe_with_history(0) to replay ALL chunks from the buffer
            # This ensures no chunks are lost even if frontend disconnected during streaming
            # The frontend skips all chunks until replay_chunk_count is reached
            async for chunk in channel.subscribe_with_history(0):
                yield chunk

            # Mark as complete when channel ends
            yield STREAM_STATUS_EVENT
            yield _resume_completed_chunk()

        return StreamingResponse(
            channel_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "X-Stream-Status": "resumed",
                "X-Last-Unit-Index": str(resume_info["resume_from_unit_index"]),
            },
        )

    # Normal mode: start new stream
    deferred_run = DeferredAgentRun()
    run_identifier = _agent_run_identifier(agent_request)
    execution = None
    agent_capacity_token = None
    try:
        agent_capacity_token = agent_run_manager.reserve_agent_capacity(
            agent_request.agent_id,
            RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS,
        )
        execution = runtime_thread_manager.submit(
            "agent-run",
            ManagedTaskSpec(
                task_name="agent-run",
                owner="backend.management.services.agent.run",
                run_id=str(run_identifier),
                close_hook=deferred_run.cancel,
                pass_cancel_event=True,
            ),
            deferred_run.run,
        )
        execution.future.add_done_callback(
            lambda _future: agent_run_manager.release_agent_capacity(
                agent_capacity_token
            )
        )
        await runtime_thread_manager.wait_until_started(execution)
    except AgentRunConcurrencyExceededError as exc:
        raise RuntimeCapacityExceededError() from exc
    except ThreadCapacityExceeded as exc:
        if execution is None and agent_capacity_token is not None:
            agent_run_manager.release_agent_capacity(agent_capacity_token)
        raise RuntimeCapacityExceededError() from exc
    except ThreadQueueTimedOut as exc:
        deferred_run.cancel()
        raise RuntimeQueueTimeoutError(exc.timeout_seconds) from exc
    except BaseException:
        deferred_run.cancel()
        if execution is not None:
            runtime_thread_manager.cancel(
                execution.execution_id,
                reason="agent admission failed",
                wait_timeout=0,
                mark_stuck_on_timeout=False,
            )
        elif agent_capacity_token is not None:
            agent_run_manager.release_agent_capacity(agent_capacity_token)
        raise

    try:
        reservation_token = agent_run_manager.reserve_agent_run(
            run_identifier,
            resolved_user_id,
        )
    except AgentRunAlreadyActiveError:
        deferred_run.cancel()
        runtime_thread_manager.cancel(
            execution.execution_id,
            reason="agent run already active",
            wait_timeout=0,
            mark_stuck_on_timeout=False,
        )
        logger.warning(
            "Rejected concurrent agent run, user_id=%s, conversation_id=%s",
            resolved_user_id,
            agent_request.conversation_id,
        )
        active_message = (
            "当前会话已有智能体任务正在运行，请等待任务完成或先停止任务后再重试。"
            if language == LANGUAGE["ZH"]
            else "An agent run is already active for this conversation. Wait for it to finish or stop it before retrying."
        )

        async def active_run_error_stream():
            payload = json.dumps(
                {"type": "error", "content": active_message},
                ensure_ascii=False,
            )
            yield f"data: {payload}\n\n"

        return StreamingResponse(
            active_run_error_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "X-Stream-Status": "conflict",
            },
        )

    try:
        await runtime_state_service.reset_stream_async(
            user_id=resolved_user_id,
            conversation_id=agent_request.conversation_id,
        )

        if not agent_request.is_debug and not skip_user_save:
            save_messages(
                agent_request,
                target=MESSAGE_ROLE["USER"],
                user_id=resolved_user_id,
                tenant_id=resolved_tenant_id,
            )

        run_context = build_agent_run_context(
            agent_request,
            resolved_user_id,
            resolved_tenant_id,
            language,
            extra_metadata={
                "skip_user_save": skip_user_save,
                "has_override_user_id": user_id is not None,
                "has_override_tenant_id": tenant_id is not None,
            },
        )
        agent_metadata = run_context.metadata
        use_memory_stream = run_context.enable_memory

        channel = None
        if not agent_request.is_debug:
            channel = await streaming_channel_manager.get_or_create_channel(
                conversation_id=agent_request.conversation_id,
                user_id=resolved_user_id,
            )
    except Exception:
        deferred_run.cancel()
        runtime_thread_manager.cancel(
            execution.execution_id,
            reason="agent stream setup failed",
            wait_timeout=0,
            mark_stuck_on_timeout=False,
        )
        agent_run_manager.release_agent_run_reservation(
            _agent_run_identifier(agent_request),
            resolved_user_id,
            reservation_token,
        )
        raise

    stream_kwargs = {
        "user_id": resolved_user_id,
        "tenant_id": resolved_tenant_id,
        "language": language,
        "enable_memory": use_memory_stream,
        "reservation_token": reservation_token,
        "execution": execution,
        "deferred_run": deferred_run,
    }
    if channel is not None:
        stream_kwargs["channel"] = channel
    stream_gen = generate_stream(agent_request, **stream_kwargs)

    async def stream_with_agent_context():
        try:
            producer_task = None
            if channel is not None:
                producer_task = asyncio.create_task(
                    _consume_agent_stream_producer(
                        stream_gen=stream_gen,
                        channel=channel,
                        agent_metadata=agent_metadata,
                        conversation_id=agent_request.conversation_id,
                        user_id=resolved_user_id,
                    )
                )
                _agent_stream_producer_tasks.add(producer_task)
                producer_task.add_done_callback(_agent_stream_producer_tasks.discard)

            # Emit conversation_created event for new conversations
            if is_new_conversation:
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "type": "conversation_created",
                            "content": {
                                "conversation_id": agent_request.conversation_id
                            },
                        },
                        ensure_ascii=False,
                    )
                    + "\n\n"
                )

            scope_event = getattr(
                agent_request, "_resolved_knowledge_scope_event", None
            )
            if canonical_workbench is not None:
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "type": "workbench_config_resolved",
                            "content": {
                                "config_version": getattr(
                                    agent_request, "_workbench_config_version", 0
                                ),
                                "schema_version": 3,
                                "mode": canonical_workbench.mode,
                                "agent_mounts": [
                                    mount.model_dump(mode="json")
                                    for mount in canonical_workbench.agent_mounts
                                ],
                            },
                        },
                        ensure_ascii=False,
                    )
                    + "\n\n"
                )
            if scope_event is not None:
                yield (
                    "data: "
                    + json.dumps(
                        {"type": "knowledge_scope_resolved", "content": scope_event},
                        ensure_ascii=False,
                    )
                    + "\n\n"
                )

            if channel is not None:
                async for data_chunk in channel.subscribe_with_history(0):
                    yield data_chunk
            else:
                # Debug/A2A streams intentionally retain the direct execution
                # path and its existing disconnect semantics.
                with agent_monitoring_context(agent_metadata):
                    async for data_chunk in stream_gen:
                        yield data_chunk
        except Exception as stream_exc:
            logger.error(
                "Agent stream response error: %r",
                stream_exc,
                exc_info=True,
            )
            yield _safe_agent_stream_error_chunk(stream_exc)
        finally:
            if channel is None and not execution.future.done():
                deferred_run.cancel()
                runtime_thread_manager.cancel(
                    execution.execution_id,
                    reason="agent response stream closed",
                    wait_timeout=0,
                    mark_stuck_on_timeout=False,
                )
            agent_run_manager.release_agent_run_reservation(
                _agent_run_identifier(agent_request),
                resolved_user_id,
                reservation_token,
            )

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    debug_run_id = getattr(agent_request, "_debug_run_id", None)
    if debug_run_id is not None:
        headers["run_id"] = debug_run_id
    if agent_request.conversation_id is not None:
        headers["conversation_id"] = str(agent_request.conversation_id)
    runtime_metadata_version = getattr(agent_request, "_runtime_metadata_version", None)
    if runtime_metadata_version is not None:
        headers["X-Runtime-Metadata-Version"] = str(runtime_metadata_version)
    workbench_config_version = getattr(agent_request, "_workbench_config_version", None)
    if workbench_config_version is not None:
        headers["X-Workbench-Config-Version"] = str(workbench_config_version)

    return StreamingResponse(
        stream_with_agent_context(),
        media_type="text/event-stream",
        headers=headers,
    )
