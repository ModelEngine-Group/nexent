# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Compatibility launch and conversation preparation."""

import asyncio
import json
import logging
import uuid

from contracts.agent import AgentRequest
from contracts.constants.constants import MESSAGE_ROLE
from contracts.constants.environment import ENABLE_AGENT_WORKBENCH
from contracts.errors.exceptions import (
    AgentRunAlreadyActiveError,
    UnauthorizedError,
    WorkbenchError,
)
from fastapi import (
    Request,
)
from fastapi.responses import (
    StreamingResponse,
)
from management.services.agent.agentos_events import active_run_error_response
from management.services.agent.context import build_agent_run_context
from management.services.agent.conversation_preparation import (
    PreparedConversationRequest,
)
from management.services.agent.conversation_preparation import (
    prepare_conversation_request as _prepare_legacy_conversation,
)
from management.services.agent.execution import (
    _agent_run_identifier,
)
from management.services.agent.lifecycle import (
    require_legacy_execution_host,
    require_legacy_thread_manager,
)
from management.services.agent.preparation.run import LegacyRunMaterializer
from management.services.agent.run import generate_stream, save_messages
from management.services.agent.stream import (
    safe_agent_stream_error_chunk as _safe_agent_stream_error_chunk,
)
from management.utils.request_context import get_user_language
from nexent.core.concurrency import ThreadManager

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
