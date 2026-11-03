# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Agent request preparation and streaming execution orchestration."""

import asyncio
import logging
from contextlib import aclosing
from typing import (
    Any,
    Dict,
    Optional,
)

from management.services.agent.lifecycle import (
    AgentRunAlreadyActiveError,
    agent_run_manager,
)
from management.services.agent.background import BackgroundExecutionState
from management.services.agent.run_state import runtime_state_service
from management.services.agent.preparation.run import create_agent_run_info
from management.services.agent.preprocessing import (
    preprocess_manager,
)
from contracts.constants.constants import LANGUAGE
from contracts.constants.constants import MESSAGE_ROLE
from contracts.errors.exceptions import MemoryPreparationException
from contracts.agent import AgentRequest
from management.services.agent.context import (
    build_agent_run_context,
    build_authorized_context_input,
)
from management.services.agent.execution import (
    _agent_run_identifier,
    _cancel_task_on_runtime_signal,
    _stream_agent_chunks,
    _unregister_agent_run_after_execution,
)
from management.services.agent.stream import (
    safe_agent_stream_error_chunk as _safe_agent_stream_error_chunk,
)
from runtime.adapters.nexent.runner import (
    DeferredAgentRun,
)
from nexent.core.concurrency import (
    ManagedExecution,
)
from nexent.monitor import (
    agent_monitoring_context,
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
from infrastructure.streaming.channels import (
    streaming_channel_manager,
)
from infrastructure.concurrency import (
    runtime_thread_manager,
)

logger = logging.getLogger(__name__)


def apply_workbench_runtime_plan(
    agent_request: AgentRequest, canonical_workbench, resolved_plan, tenant_id: str
) -> None:
    """Attach a validated Workbench plan to one in-memory run request."""
    from management.services.knowledge_base.scope import snapshot_runtime_knowledge_tree
    from management.services.agent.workbench import (
        attach_runtime_knowledge_tree,
        runtime_skill_snapshot,
    )

    knowledge_tree = snapshot_runtime_knowledge_tree(
        int(resolved_plan.root.identity.agent_id),
        tenant_id,
        int(resolved_plan.root.identity.version_no),
    )
    if canonical_workbench.knowledge_scope is not None:
        from management.services.knowledge_base.mount import mount_knowledge_records

        knowledge_tree = knowledge_tree[:1]
        knowledge_tree[0]["tools"] = mount_knowledge_records(
            knowledge_tree[0]["tools"], canonical_workbench.knowledge_scope, tenant_id
        )
        agent_request.__dict__["_runtime_knowledge_tools"] = knowledge_tree[0]["tools"]
    resolved_plan = attach_runtime_knowledge_tree(resolved_plan, knowledge_tree)
    root_identity = resolved_plan.root.identity
    agent_request.workbench = canonical_workbench
    agent_request.agent_id = root_identity.agent_id
    agent_request.version_no = root_identity.version_no
    if resolved_plan.overlay.model_id is not None:
        agent_request.model_id = resolved_plan.overlay.model_id
    if resolved_plan.overlay.requested_output_tokens is not None:
        agent_request.requested_output_tokens = (
            resolved_plan.overlay.requested_output_tokens
        )
    agent_request.knowledge_scope = canonical_workbench.knowledge_scope
    agent_request.__dict__["_runtime_skill_snapshot"] = runtime_skill_snapshot(
        resolved_plan
    )
    agent_request.__dict__["_runtime_mount_plan"] = resolved_plan
    agent_request.__dict__["_runtime_root_identity"] = {
        "agent_id": root_identity.agent_id,
        "version_no": root_identity.version_no,
        "runtime_ref": root_identity.runtime_ref,
        "invocation_name": root_identity.invocation_name,
        "display_name": root_identity.display_name,
        "origin": root_identity.origin,
    }
    agent_request.__dict__["_runtime_generation_config"] = (
        canonical_workbench.generation_config.model_dump(mode="json")
    )


async def prepare_agent_run(
    agent_request: AgentRequest,
    user_id: str,
    tenant_id: str,
    language: str = LANGUAGE["ZH"],
    allow_memory_search: bool = True,
    reservation_token: Optional[str] = None,
):
    """
    Prepare for an agent run by creating context and run info, and registering the run.
    """

    memory_context = build_memory_context(
        user_id, tenant_id, agent_request.agent_id, skip_query=not allow_memory_search
    )

    create_run_kwargs = {
        "agent_id": agent_request.agent_id,
        "minio_files": agent_request.minio_files,
        "query": agent_request.query,
        "history": agent_request.history,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "language": language,
        "allow_memory_search": allow_memory_search,
        "is_debug": agent_request.is_debug,
        "override_version_no": agent_request.version_no,
        "override_model_id": agent_request.model_id,
        "reasoning_effort": agent_request.reasoning_effort,
        "reasoning_budget_tokens": agent_request.reasoning_budget_tokens,
        "requested_output_tokens": agent_request.requested_output_tokens,
        "tool_params": agent_request.tool_params,
        "conversation_id": agent_request.conversation_id,
        "context_policy": agent_request.context_policy,
        "enable_planning": agent_request.enable_plan,
    }
    runtime_knowledge_context = getattr(
        agent_request, "_runtime_knowledge_context", None
    )
    if isinstance(runtime_knowledge_context, dict):
        create_run_kwargs["runtime_knowledge_context"] = runtime_knowledge_context
    runtime_skill_snapshot = getattr(agent_request, "_runtime_skill_snapshot", None)
    runtime_knowledge_tools = getattr(agent_request, "_runtime_knowledge_tools", None)
    if runtime_knowledge_tools is not None:
        create_run_kwargs["runtime_knowledge_tools"] = runtime_knowledge_tools
    if runtime_skill_snapshot is not None:
        create_run_kwargs["runtime_skill_snapshot"] = runtime_skill_snapshot
    runtime_generation_config = getattr(
        agent_request, "_runtime_generation_config", None
    )
    if (
        runtime_generation_config is None
        and agent_request.generation_config is not None
    ):
        runtime_generation_config = agent_request.generation_config.model_dump(
            mode="json", exclude_unset=True
        )
    if runtime_generation_config is not None:
        create_run_kwargs["runtime_generation_config"] = runtime_generation_config
    runtime_mount_plan = getattr(agent_request, "_runtime_mount_plan", None)
    if runtime_mount_plan is not None:
        create_run_kwargs["runtime_sub_agent_mounts"] = [
            {
                "agent_id": child.agent_id,
                "version_no": child.version_no,
                "runtime_ref": child.runtime_ref,
                "invocation_name": child.invocation_name,
                "display_name": child.display_name,
            }
            for child in runtime_mount_plan.child_mounts
        ]
    if not agent_request.enable_automation_tool:
        create_run_kwargs["enable_automation_tool"] = False
    agent_run_info = await create_agent_run_info(
        **create_run_kwargs,
    )
    if runtime_mount_plan is not None:
        from management.services.agent.workbench import compile_runtime_mount_plan

        executable_tree = compile_runtime_mount_plan(
            runtime_mount_plan, agent_run_info.agent_config
        )
        agent_run_info.agent_config = executable_tree.root.agent_config
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
    agent_run_info.__dict__["_automation_runtime_generation"] = agent_request.__dict__.get("_runtime_automation_generation")
    register_kwargs = {}
    if reservation_token is not None:
        register_kwargs["reservation_token"] = reservation_token
    agent_run_manager.register_agent_run(
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
    final_answer_mode: str = "delta",
    execution_state: Optional[BackgroundExecutionState] = None,
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
    # Poll for cross-pod cancel signal so the outer generator task can be
    # cancelled when another Pod writes the runtime cancel flag.
    _outer_task = asyncio.current_task()
    cancel_poll_task = (
        asyncio.create_task(
            _cancel_task_on_runtime_signal(
                agent_request.conversation_id, user_id, _outer_task
            )
        )
        if _outer_task
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
        try:
            prepare_kwargs = {}
            if reservation_token is not None:
                prepare_kwargs["reservation_token"] = reservation_token
            agent_run_info, memory_context = await prepare_agent_run(
                agent_request=agent_request,
                user_id=user_id,
                tenant_id=tenant_id,
                language=language,
                allow_memory_search=memory_enabled_runtime,
                **prepare_kwargs,
            )
        except AgentRunAlreadyActiveError:
            raise
        except Exception as prep_err:
            # Normalize any preparation error to MemoryPreparationException so
            # the memory-enabled path can decide between retry-without-memory
            # and propagating the failure.
            raise MemoryPreparationException(str(prep_err)) from prep_err

        background_kwargs = {"execution_state": execution_state} if execution_state is not None else {}
        async with aclosing(_stream_agent_chunks(
            agent_request=agent_request,
            user_id=user_id,
            tenant_id=tenant_id,
            agent_run_info=agent_run_info,
            memory_ctx=memory_context,
            channel=channel,
            execution=execution,
            deferred_run=deferred_run,
            final_answer_mode=final_answer_mode,
            **background_kwargs,
        )) as chunks:
            async for data_chunk in chunks:
                yield data_chunk

    except (asyncio.CancelledError, GeneratorExit):
        if agent_run_info is not None:
            run_identifier = _agent_run_identifier(agent_request)
            agent_run_manager.stop_agent_run(run_identifier, user_id)
            _unregister_agent_run_after_execution(
                run_identifier,
                user_id,
                status="stopped",
                agent_run_info=agent_run_info,
            )
        raise
    except MemoryPreparationException as prep_error:
        if not enable_memory:
            if execution_state is not None:
                execution_state.fail("AUTOMATION_PREPARATION_FAILED", "Agent preparation failed.")
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
            fallback_kwargs = {"execution_state": execution_state} if execution_state is not None else {}
            async with aclosing(generate_stream(
                agent_request,
                user_id=user_id,
                tenant_id=tenant_id,
                language=language,
                enable_memory=False,
                channel=channel,
                reservation_token=reservation_token,
                execution=execution,
                deferred_run=deferred_run,
                final_answer_mode=final_answer_mode,
                **fallback_kwargs,
            )) as chunks:
                async for data_chunk in chunks:
                    yield data_chunk
        except Exception as run_exc:
            if execution_state is not None:
                execution_state.fail("AUTOMATION_EXECUTION_FAILED", "Agent execution failed after memory fallback.")
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
        if execution_state is not None and execution_state.outcome != "failed":
            execution_state.fail("AUTOMATION_EXECUTION_FAILED", "Agent execution failed.")
        if execution_state is not None and agent_run_info is not None:
            _unregister_agent_run_after_execution(
                _agent_run_identifier(agent_request), user_id,
                status="failed", agent_run_info=agent_run_info,
            )
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
        if cancel_poll_task is not None:
            await asyncio.gather(cancel_poll_task, return_exceptions=True)
        if (
            agent_run_info is None
            and deferred_run is not None
            and execution is not None
            and not execution.future.done()
        ):
            deferred_run.cancel()
            runtime_thread_manager.cancel(
                execution.execution_id,
                reason="agent preparation ended before worker binding",
                wait_timeout=0,
                mark_stuck_on_timeout=False,
            )
        if reservation_token is not None:
            agent_run_manager.release_agent_run_reservation(
                _agent_run_identifier(agent_request),
                user_id,
                reservation_token,
            )


async def run_agent_background(
    agent_request: AgentRequest,
    user_id: str,
    tenant_id: str,
    language: str = LANGUAGE["ZH"],
    skip_user_save: bool = False,
    execution_state: Optional[BackgroundExecutionState] = None,
) -> Dict[str, Any]:
    """
    Run an agent without returning an SSE response.

    This path is used by background automation tasks. It reuses the same
    preparation, monitoring, memory and message persistence flow as
    run_agent_stream, but consumes generated chunks internally.
    """
    if not agent_request.conversation_id:
        raise ValueError("conversation_id is required for background agent runs")

    execution_state = execution_state or BackgroundExecutionState()
    reservation = agent_run_manager.reserve_agent_run(agent_request.conversation_id, user_id)
    try:
        agent_request.__dict__["_runtime_automation_generation"] = execution_state.runtime_generation
        await runtime_state_service.reset_stream_async(
            user_id, agent_request.conversation_id, generation=execution_state.runtime_generation,
        )
        # A user cancellation may have committed before reset or during preparation.
        if execution_state.is_active is not None and not execution_state.is_active():
            raise asyncio.CancelledError()
        # Background automation provenance is server-owned, including run-now.
        agent_request._message_source = "AUTOMATION"

        if not agent_request.is_debug and not skip_user_save:
            save_messages(
                agent_request,
                target=MESSAGE_ROLE["USER"],
                user_id=user_id,
                tenant_id=tenant_id,
            )

        run_context = build_agent_run_context(
            agent_request,
            user_id,
            tenant_id,
            language,
            extra_metadata={"background": True, "skip_user_save": skip_user_save},
        )
        agent_metadata = run_context.metadata
        stream_gen = generate_stream(
            agent_request,
            user_id=user_id,
            tenant_id=tenant_id,
            language=language,
            enable_memory=run_context.enable_memory,
            execution_state=execution_state,
            reservation_token=reservation,
        )

        chunks = 0
        with agent_monitoring_context(agent_metadata):
            async with aclosing(stream_gen):
                async for _ in stream_gen:
                    chunks += 1
        return {
            "conversation_id": agent_request.conversation_id,
            **execution_state.result(),
            "chunks": chunks,
        }
    finally:
        agent_run_manager.release_agent_run_reservation(agent_request.conversation_id, user_id, reservation)


def stop_agent_tasks(conversation_id: int | str, user_id: str, expected_generation: Optional[str] = None):
    """
    Stop an agent run by its conversation ID or ephemeral debug run ID.
    Matches the behavior of agent_app.agent_stop_api.
    """
    # Stop agent run
    if expected_generation is None:
        agent_stopped = agent_run_manager.stop_agent_run(conversation_id, user_id)
    else:
        agent_stopped = agent_run_manager.stop_agent_run(conversation_id, user_id, expected_generation=expected_generation)

    # Preprocess tasks are associated only with persisted conversations.
    preprocess_stopped = (
        preprocess_manager.stop_preprocess_tasks(conversation_id)
        if isinstance(conversation_id, int) and expected_generation is None
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


def is_agent_running(conversation_id: int, user_id: str) -> bool:
    return agent_run_manager.get_agent_run_info(conversation_id, user_id) is not None
