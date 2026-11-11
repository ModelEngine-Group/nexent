# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Agent request preparation and streaming execution orchestration."""

import asyncio
import logging
from typing import (
    Any,
    Dict,
    Optional,
)

from management.services.agent.lifecycle import (
    require_legacy_execution_host,
    require_legacy_thread_manager,
)
from management.services.agent.preparation.run import LegacyRunMaterializer, create_agent_run_info
from management.services.agent.preprocessing import (
    preprocess_manager,
)
from contracts.constants.constants import LANGUAGE
from contracts.constants.constants import MESSAGE_ROLE
from contracts.errors.exceptions import AgentRunAlreadyActiveError, MemoryPreparationException
from contracts.agent import AgentRequest
from management.services.agent.preparation.request import apply_workbench_runtime_plan, build_run_preparation_arguments
from contracts.agentos import AGENTOS_PREPARATION_STOP
from management.services.agent.context import (
    build_authorized_context_input,
)
from management.services.agent.execution import (
    _agent_run_identifier,
    _cancel_preparation_on_agentos_stop,
    _cancel_task_on_runtime_signal,
    _journal_stop_requested,
    _run_journal,
    _stream_agent_chunks,
)
from management.services.agent.stream import (
    safe_agent_stream_error_chunk as _safe_agent_stream_error_chunk,
)
from nexent.core.agents.run_agent import DeferredAgentRun
from infrastructure.rdb.agent_execution import RunIdentity, mark_running
from nexent.core.concurrency import (
    ManagedExecution,
    ThreadManager,
    run_blocking,
)
from management.services.conversation.service import (
    get_current_run_user_message_id,
    load_historical_context,
    persist_history_summary_candidate,
    save_conversation_user,
)
from management.services.configuration.user.memory import (
    build_memory_context,
)
from infrastructure.agent_stream_channels import (
    streaming_channel_manager,
)

logger = logging.getLogger(__name__)


async def prepare_agent_run(
    agent_request: AgentRequest,
    user_id: str,
    tenant_id: str,
    language: str = LANGUAGE["ZH"],
    allow_memory_search: bool = True,
    reservation_token: Optional[str] = None,
    resource_versions: dict | None = None,
    *,
    legacy_materializer: LegacyRunMaterializer | None = None,
    execution_host=None,
):
    """
    Prepare for an agent run by creating context and run info, and registering the run.
    """

    host = require_legacy_execution_host(execution_host)
    memory_context = build_memory_context(
        user_id, tenant_id, agent_request.agent_id, skip_query=not allow_memory_search
    )

    create_run_kwargs = build_run_preparation_arguments(
        agent_request, user_id, tenant_id, language, allow_memory_search,
    )
    if resource_versions is not None:
        create_run_kwargs["resource_versions"] = resource_versions
    if legacy_materializer is not None:
        create_run_kwargs["legacy_materializer"] = legacy_materializer
    agent_run_info = await create_agent_run_info(
        **create_run_kwargs,
    )
    runtime_mount_plan = getattr(agent_request, "_runtime_mount_plan", None)
    if runtime_mount_plan is not None:
        from management.services.agent.workbench import compile_runtime_mount_plan

        executable_tree = compile_runtime_mount_plan(
            runtime_mount_plan, agent_run_info.agent_config
        )
        agent_run_info.agent_config = executable_tree.root.agent_config
        if resource_versions is not None:
            resource_versions["mounted_agents"] = [
                {"agent_id": child.agent_id, "version_no": child.version_no}
                for child in runtime_mount_plan.child_mounts
            ]
    agent_run_info.runtime_metadata = dict(
        getattr(agent_request, "_runtime_metadata_snapshot", {}) or {}
    )
    agent_run_info.runtime_metadata_version = getattr(
        agent_request,
        "_runtime_metadata_version",
        None,
    )

    historical_context = None
    if not agent_request.is_debug and agent_request.conversation_id is not None:
        current_message_id = get_current_run_user_message_id(
            agent_request.conversation_id, user_id
        )
        if not isinstance(current_message_id, int) or isinstance(
            current_message_id, bool
        ):
            current_message_id = None
            logger.warning(
                "Current user message boundary is unavailable; historical checkpoint loading skipped"
            )
        if current_message_id is not None:
            historical_context = load_historical_context(
                agent_request.conversation_id, current_message_id, user_id, tenant_id
            )
    agent_run_info.context_input = build_authorized_context_input(
        agent_run_info, historical_context
    )
    agent_run_info.conversation_id = agent_request.conversation_id
    agent_run_info.user_id = user_id

    # ContextManager is created exactly once by the SDK Agent creation entry.
    # The application boundary only injects the persistence callback into its
    # configuration before the worker thread starts.
    cm_config = getattr(agent_run_info.agent_config, "context_manager_config", None)
    if cm_config:
        cm_config.history_summary_sink = (
            (
                lambda candidate: persist_history_summary_candidate(
                    agent_request.conversation_id, candidate, user_id, tenant_id
                )
            )
            if historical_context is not None
            else None
        )
    register_kwargs = {}
    if reservation_token is not None:
        register_kwargs["reservation_token"] = reservation_token
    host.registry.register_agent_run(
        _agent_run_identifier(agent_request),
        agent_run_info,
        user_id,
        **register_kwargs,
    )
    return agent_run_info, memory_context


def save_messages(
    agent_request, target: str, user_id: str, tenant_id: str, messages=None
):
    if target == MESSAGE_ROLE["USER"]:
        if messages is not None:
            raise ValueError("Messages should be None when saving for user.")
        # Historical checkpoint lookup for this run needs the current message boundary.
        save_conversation_user(agent_request, user_id, tenant_id)
        return

    if target == MESSAGE_ROLE["ASSISTANT"]:
        raise ValueError(
            "save_messages no longer persists the assistant message; "
            "_stream_agent_chunks persists the assistant run as a final batch."
        )

    raise ValueError(f"Unsupported target for save_messages: {target!r}")


async def generate_stream(
    agent_request: AgentRequest,
    user_id: str,
    tenant_id: str,
    language: str = LANGUAGE["ZH"],
    enable_memory: bool = False,
    channel: Optional[Any] = None,
    reservation_token: Optional[str] = None,
    execution: Optional[ManagedExecution] = None,
    deferred_run: Optional[DeferredAgentRun] = None,
    *,
    legacy_materializer: LegacyRunMaterializer | None = None,
    thread_manager: ThreadManager | None = None,
    execution_host=None,
):
    """Unified streaming entry point.

    Args:
        agent_request: The agent run payload.
        user_id: The caller user id.
        tenant_id: The caller tenant id.
        language: UI/i18n language (``"zh"`` / ``"en"``).
        enable_memory: When ``True``, memory retrieval runs once before the
            model loop and store_memory is loaded for model-directed use. A
            ``MemoryPreparationException`` triggers a single fallback to the
            no-memory path so the run still produces output.
        channel: Optional streaming channel; when ``None`` a fresh channel
            is created lazily when memory is enabled.
    """
    thread_manager = require_legacy_thread_manager(thread_manager)
    host = require_legacy_execution_host(execution_host)

    # Poll for cross-pod cancel signal so the outer generator task can be
    # cancelled when another Pod writes the runtime cancel flag.
    _outer_task = asyncio.current_task()
    journal = _run_journal(channel)
    cancel_poll_task = (
        asyncio.create_task(
            _cancel_task_on_runtime_signal(
                agent_request.conversation_id, user_id, _outer_task
            )
        )
        if _outer_task and not isinstance(journal, RunIdentity)
        else None
    )

    # Lazily open the streaming channel. Recursive fallback below needs to
    # reuse the same channel so subscribers stay connected.
    if channel is None and enable_memory:
        channel = await streaming_channel_manager.get_or_create_channel(
            conversation_id=agent_request.conversation_id,
            user_id=user_id,
        )

    memory_enabled_runtime = False
    agent_run_info = None
    scoped_preparation_stop = False
    try:
        if enable_memory:
            # Resolve the user-level switch for tool loading only.
            memory_context_preview = build_memory_context(
                user_id, tenant_id, agent_request.agent_id
            )
            memory_enabled_runtime = bool(
                memory_context_preview.user_config.memory_switch
            )

        # Prepare the agent with or without memory. The preparation path runs
        # fixed retrieval before the model loop and exposes only store_memory.
        preparation_poll = None
        resource_versions = {}
        try:
            if journal is not None and _outer_task is not None:
                if await _journal_stop_requested(journal):
                    raise asyncio.CancelledError(AGENTOS_PREPARATION_STOP)
                preparation_poll = asyncio.create_task(_cancel_preparation_on_agentos_stop(journal, _outer_task))
            prepare_kwargs = {}
            if isinstance(journal, RunIdentity):
                prepare_kwargs["resource_versions"] = resource_versions
            if reservation_token is not None:
                prepare_kwargs["reservation_token"] = reservation_token
            if legacy_materializer is not None:
                prepare_kwargs["legacy_materializer"] = legacy_materializer
            agent_run_info, memory_context = await prepare_agent_run(
                agent_request=agent_request,
                user_id=user_id,
                tenant_id=tenant_id,
                language=language,
                allow_memory_search=memory_enabled_runtime,
                execution_host=host,
                **prepare_kwargs,
            )
        except AgentRunAlreadyActiveError:
            raise
        except Exception as prep_err:
            # Normalize any preparation error to MemoryPreparationException so
            # the memory-enabled path can decide between retry-without-memory
            # and propagating the failure.
            raise MemoryPreparationException(str(prep_err)) from prep_err
        finally:
            if preparation_poll is not None:
                preparation_poll.cancel()

        if isinstance(journal, RunIdentity):
            for version in ("runtime_metadata_version", "workbench_config_version"):
                value = getattr(agent_request, f"_{version}", None)
                if type(value) is int:
                    resource_versions[version] = value
            if not await run_blocking(
                "agentos-execution-running", mark_running, journal, resource_versions,
                lane="control-io", owner="runtime",
            ):
                host.registry.stop_local_run(_agent_run_identifier(agent_request), user_id, agent_run_info)

        async for data_chunk in _stream_agent_chunks(
            agent_request=agent_request,
            user_id=user_id,
            tenant_id=tenant_id,
            agent_run_info=agent_run_info,
            memory_ctx=memory_context,
            channel=channel,
            execution=execution,
            deferred_run=deferred_run,
            thread_manager=thread_manager,
            execution_host=host,
        ):
            yield data_chunk

    except (asyncio.CancelledError, GeneratorExit) as exc:
        scoped_preparation_stop = journal is not None and exc.args == (AGENTOS_PREPARATION_STOP,)
        if agent_run_info is not None:
            run_identifier = _agent_run_identifier(agent_request)
            if journal is None:
                host.registry.stop_agent_run(run_identifier, user_id)
            else:
                host.registry.stop_local_run(run_identifier, user_id, agent_run_info)
            host.unregister(
                run_identifier,
                user_id,
                status="stopped",
                agent_run_info=agent_run_info,
            )
        raise
    except MemoryPreparationException as prep_error:
        if not enable_memory:
            # No-memory path has no fallback; surface the failure cleanly.
            logger.error(
                "Agent run preparation failed without memory: %s",
                type(prep_error.__cause__ or prep_error).__name__,
                exc_info=True,
            )
            error_chunk = _safe_agent_stream_error_chunk()
            if channel is not None:
                await channel.publish(error_chunk)
            yield error_chunk
            return

        try:
            # Single fallback: re-issue this generator with memory turned off
            # so the actual ``_stream_agent_chunks`` still runs.
            async for data_chunk in generate_stream(
                agent_request,
                user_id=user_id,
                tenant_id=tenant_id,
                language=language,
                enable_memory=False,
                channel=channel,
                reservation_token=reservation_token,
                execution=execution,
                deferred_run=deferred_run,
                legacy_materializer=legacy_materializer,
                thread_manager=thread_manager,
                execution_host=host,
            ):
                yield data_chunk
        except Exception as run_exc:
            logger.error(
                "Agent run error after memory failure: %r",
                run_exc,
                exc_info=True,
            )
            error_chunk = _safe_agent_stream_error_chunk(run_exc)
            if channel is not None:
                await channel.publish(error_chunk)
            yield error_chunk
            return
    except Exception as stream_exc:
        logger.error(
            "Generate stream error: %r",
            stream_exc,
            exc_info=True,
        )
        error_chunk = _safe_agent_stream_error_chunk(stream_exc)
        if channel is not None:
            await channel.publish(error_chunk)
        yield error_chunk
        return
    finally:
        if cancel_poll_task and not cancel_poll_task.done():
            cancel_poll_task.cancel()
        if (
            (agent_run_info is None or (
                isinstance(journal, RunIdentity) and getattr(agent_run_info, "thread_future", None) is None
            ))
            and deferred_run is not None
            and execution is not None
            and not execution.future.done()
        ):
            deferred_run.cancel()
            thread_manager.cancel(
                execution.execution_id,
                reason="agent preparation ended before worker binding",
                wait_timeout=0,
                mark_stuck_on_timeout=False,
            )
        # The detached producer owns terminal publication and releases a
        # stopped preparation's reservation in its done callback.
        if reservation_token is not None and not scoped_preparation_stop:
            host.registry.release_agent_run_reservation(
                _agent_run_identifier(agent_request),
                user_id,
                reservation_token,
            )


def stop_agent_tasks(conversation_id: int | str, user_id: str, *, execution_host=None):
    """
    Stop an agent run by its conversation ID or ephemeral debug run ID.
    Matches the behavior of agent_app.agent_stop_api.
    """
    # Stop agent run
    host = require_legacy_execution_host(execution_host)
    agent_stopped = host.registry.stop_agent_run(conversation_id, user_id)

    # Preprocess tasks are associated only with persisted conversations.
    preprocess_stopped = (
        preprocess_manager.stop_preprocess_tasks(conversation_id)
        if isinstance(conversation_id, int)
        else False
    )

    if agent_stopped or preprocess_stopped:
        message_parts = []
        if agent_stopped:
            message_parts.append("agent run")
        if preprocess_stopped:
            message_parts.append("preprocess tasks")

        message = f"successfully stopped {' and '.join(message_parts)} for user_id {user_id}, run_id {conversation_id}"
        logging.info(message)
        return {"status": "success", "message": message}
    else:
        message = f"no running agent or preprocess tasks found for user_id {user_id}, run_id {conversation_id}"
        logging.info(message)
        return {"status": "success", "message": message, "already_stopped": True}


def is_agent_running(conversation_id: int, user_id: str, *, execution_host=None) -> bool:
    host = require_legacy_execution_host(execution_host)
    return host.registry.get_agent_run_info(conversation_id, user_id) is not None
