# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Compatibility launch and conversation preparation."""

import asyncio
import json
from contracts.errors.exceptions import UnauthorizedError
import logging
import uuid
from dataclasses import dataclass
from copy import (
    deepcopy,
)

from management.services.agent.agentos_events import active_run_error_response, knowledge_scope_event_content
from management.services.agent.lifecycle import (
    require_legacy_execution_host,
    require_legacy_thread_manager,
)
from contracts.constants.constants import DEFAULT_EN_TITLE, DEFAULT_ZH_TITLE, MESSAGE_ROLE
from contracts.constants.environment import ENABLE_AGENT_WORKBENCH
from contracts.constants.constants import LANGUAGE
from contracts.errors.codes import ErrorCode, RuntimeMetadataValidationCode
from contracts.errors.exceptions import (
    AgentRunAlreadyActiveError,
    AppException,
    ConversationNotFoundError,
    ForbiddenError,
    RuntimeMetadataValidationError,
    RuntimeMetadataVersionConflict,
    ValidationError,
    WorkbenchError,
)
from contracts.agent import AgentRequest, WorkbenchSessionConfig
from contracts.knowledge import ConversationKnowledgeScopeRequest, ResolvedKnowledgeScope
from management.db.agent.repository import search_agent_info_by_agent_id
from management.db.conversation.repository import resolve_conversation_runtime_metadata
from fastapi import (
    Request,
)
from fastapi.responses import (
    StreamingResponse,
)
from management.services.agent.context import (
    build_agent_run_context,
    prepend_current_time,
)
from management.services.agent.execution import (
    _agent_run_identifier,
)
from management.services.agent.preparation.run import LegacyRunMaterializer
from management.services.agent.run import (
    apply_workbench_runtime_plan,
    generate_stream,
    save_messages,
)
from management.services.agent.stream import (
    safe_agent_stream_error_chunk as _safe_agent_stream_error_chunk,
)
from nexent.core.concurrency import (
    ThreadManager,
    run_blocking,
)
from management.services.conversation.service import (
    create_new_conversation,
    get_conversation_service,
    update_conversation_agent_id_service,
    update_conversation_chat_mode_service,
    update_conversation_knowledge_scope_service,
    update_conversation_workbench_and_metadata_service,
    update_conversation_workbench_config_service,
)
from management.services.knowledge_base.scope import (
    build_runtime_knowledge_resources,
    resolve_knowledge_scope,
)
from management.utils.request_context import get_user_language
from contracts.runtime_metadata import (
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


@dataclass(frozen=True)
class PreparedConversationRequest:
    """Keep the policy result available to both legacy and portable execution."""

    created: bool
    workbench: WorkbenchSessionConfig | None
    knowledge: ResolvedKnowledgeScope | None
    knowledge_tree: tuple[dict, ...] = ()


async def _prepare_legacy_conversation(
    agent_request: AgentRequest,
    resolved_user_id: str,
    resolved_tenant_id: str,
    language: str,
    timezone: str | None,
    *, export_resources: bool = False,
) -> PreparedConversationRequest:
    """Apply the compatibility request's conversation and authorization rules."""
    from management.services.model import run_controls

    if agent_request.entrypoint == "workbench" and not ENABLE_AGENT_WORKBENCH:
        raise WorkbenchError("WORKBENCH_DISABLED", status_code=404)
    run_controls.validate_agent_model_selection(
        agent_request, resolved_tenant_id, search_agent_info_by_agent_id
    )
    if agent_request.is_debug:
        # Debug executions deliberately do not create conversations, so they
        # need a transient identifier for lifecycle operations such as stop.
        agent_request.__dict__["_debug_run_id"] = f"debug-{uuid.uuid4().hex}"

    # Inject current time in the user's timezone so the LLM can answer
    # time-related questions correctly. The SDK strips this prefix before
    # sending AGENT_NEW_RUN to the frontend, so the user message display
    # does not show the time marker.
    agent_request.query = prepend_current_time(
        agent_request.query,
        timezone,
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
        is_workbench_conversation = isinstance(
            conversation.get("workbench_config"), dict
        )
        if is_workbench_conversation != (agent_request.entrypoint == "workbench"):
            raise ForbiddenError(
                "Conversation belongs to a different chat entrypoint"
            )

    canonical_workbench = None
    if agent_request.entrypoint == "workbench":
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

    raw_request_scope = getattr(agent_request, "knowledge_scope", None)
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
    if source_scope is None and stored_scope is not None:
        source_scope = ConversationKnowledgeScopeRequest.model_validate(stored_scope)

    resolved_scope = None
    runtime_knowledge_tree = []
    if source_scope is not None:
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
        if export_resources and not runtime_knowledge_tree:
            from management.services.knowledge_base.scope import resolve_root_version, snapshot_runtime_knowledge_tree

            version = await run_blocking(
                "resolve-knowledge-root-version", resolve_root_version,
                agent_request.agent_id, resolved_tenant_id, agent_request.version_no, bool(agent_request.is_debug),
                lane="control-io", owner="management",
            )
            runtime_knowledge_tree = await run_blocking(
                "freeze-runtime-knowledge-tree", snapshot_runtime_knowledge_tree,
                agent_request.agent_id, resolved_tenant_id, version, lane="control-io", owner="management",
            )
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
        agent_request.__dict__["_resolved_knowledge_scope_event"] = knowledge_scope_event_content(resolved_scope)
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

    return PreparedConversationRequest(is_new_conversation, canonical_workbench, resolved_scope, tuple(runtime_knowledge_tree))


async def run_agent_stream(
    agent_request: AgentRequest,
    http_request: Request,
    user_id: str = None,
    tenant_id: str = None,
    skip_user_save: bool = False,
    *,
    legacy_materializer: LegacyRunMaterializer | None = None,
    thread_manager: ThreadManager | None = None,
    execution_host=None,
):
    """
    Start an agent run and stream responses.
    The gateway must supply the authenticated user and tenant for every entrypoint.

    """
    if agent_request.entrypoint == "workbench" and not ENABLE_AGENT_WORKBENCH:
        raise WorkbenchError("WORKBENCH_DISABLED", status_code=404)

    resolved_user_id, resolved_tenant_id, language = _resolve_user_tenant_language(
        http_request=http_request,
        user_id=user_id,
        tenant_id=tenant_id,
    )
    thread_manager = require_legacy_thread_manager(thread_manager)
    host = require_legacy_execution_host(execution_host)
    prepared_request = await _prepare_legacy_conversation(
        agent_request, resolved_user_id, resolved_tenant_id, language,
        http_request.headers.get("x-user-timezone") if http_request else None,
    )
    is_new_conversation, canonical_workbench = prepared_request.created, prepared_request.workbench

    run_identifier = _agent_run_identifier(agent_request)
    try:
        deferred_run, execution, reservation_token = await host.admit(
            thread_manager, agent_request.agent_id, run_identifier, resolved_user_id,
        )
    except AgentRunAlreadyActiveError:
        logger.warning(
            "Rejected concurrent agent run, user_id=%s, conversation_id=%s",
            resolved_user_id,
            agent_request.conversation_id,
        )
        return active_run_error_response(language)

    channel = None
    admission_scope = getattr(agent_request, "_run_admission_scope", None)
    tracked_execution = None
    try:
        if getattr(agent_request, "_track_execution", False) is True and not agent_request.is_debug:
            agent_request._projection_run_id = agent_request._projection_run_id or uuid.uuid4().hex
            tracked_execution = await host.begin_tracking(
                agent_request.conversation_id, agent_request._projection_run_id, resolved_user_id, resolved_tenant_id,
            )
        await host.reset_stream(agent_request.conversation_id, resolved_user_id)

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

        journal_run_id = None
        if not agent_request.is_debug:
            channel = await host.open_channel(agent_request.conversation_id, resolved_user_id)
            agent_request._projection_run_id = (
                getattr(agent_request, "_projection_run_id", None) or uuid.uuid4().hex
            )
            journal_run_id = await host.bind_channel(
                channel, agent_request._projection_run_id, resolved_user_id, resolved_tenant_id,
                conversation_id=agent_request.conversation_id, identity=tracked_execution, admission_scope=admission_scope,
            )
    except (Exception, asyncio.CancelledError):
        await host.rollback_launch(
            registry=host.registry,
            thread_manager=thread_manager,
            execution=execution,
            deferred_run=deferred_run,
            reservation_token=reservation_token,
            run_identifier=run_identifier,
            user_id=resolved_user_id,
            conversation_id=agent_request.conversation_id,
            tracked_execution=tracked_execution,
            channel=channel,
            admission_scope=admission_scope,
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
        "thread_manager": thread_manager,
        "execution_host": host,
    }
    if channel is not None:
        stream_kwargs["channel"] = channel
    if legacy_materializer is not None:
        stream_kwargs["legacy_materializer"] = legacy_materializer
    stream_gen = generate_stream(agent_request, **stream_kwargs)

    async def stream_with_agent_context():
        try:
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
                async with host.direct_stream(
                    stream_gen, agent_metadata, registry=host.registry, thread_manager=thread_manager,
                    execution=execution, deferred_run=deferred_run, run_identifier=run_identifier,
                    user_id=resolved_user_id, reservation_token=reservation_token,
                ) as direct_stream:
                    async for data_chunk in direct_stream:
                        yield data_chunk
        except Exception as stream_exc:
            logger.error(
                "Agent stream response error: %r",
                stream_exc,
                exc_info=True,
            )
            yield _safe_agent_stream_error_chunk(stream_exc)

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    if tracked_execution is not None:
        headers["run_id"] = tracked_execution.run_id
    if journal_run_id is not None:
        headers["X-AgentOS-Run-ID"] = journal_run_id
    elif tracked_execution is not None:
        headers["X-AgentOS-Run-ID"] = tracked_execution.run_id
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

    response = StreamingResponse(
        stream_with_agent_context(),
        media_type="text/event-stream",
        headers=headers,
    )

    if channel is not None:
        producer_task = host.start_producer(
            stream_gen=stream_gen,
            channel=channel,
            agent_metadata=agent_metadata,
            conversation_id=agent_request.conversation_id,
            user_id=resolved_user_id,
            execution_host=host,
            render_error=_safe_agent_stream_error_chunk,
            tracked_execution=tracked_execution,
            run_identifier=run_identifier,
            reservation_token=reservation_token,
            execution=execution,
            deferred_run=deferred_run,
            thread_manager=thread_manager,
        )
        if tracked_execution is not None:
            response.agentos_producer = producer_task

    return response
