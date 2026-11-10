# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Agent execution, message persistence and process-local task ownership."""

import asyncio
from functools import partial
from management.services.agent.persistence import finalize_assistant_projection
import json
import logging
import os
from typing import (
    Any,
    Optional,
)

from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from management.services.agent.lifecycle import (
    agent_run_manager,
    require_legacy_thread_manager,
)
from contracts.constants.constants import MESSAGE_ROLE
from contracts.constants.constants import MODEL_CONFIG_MAPPING
from contracts.constants.environment import RUNTIME_CANCEL_POLL_INTERVAL_SECONDS
from contracts.constants.constants import STREAM_STATUS_EVENT
from contracts.agent import AgentRequest
from contracts.conversation import MessageRequest
from management.db.conversation.repository import get_units_by_message
from management.services.agent.artifacts import (
    enrich_file_uploads_with_presigned_urls as _enrich_file_uploads_with_presigned_urls,
)
from management.services.agent.artifacts import (
    extract_json_objects_from_text as _extract_json_objects_from_text,
)
from management.services.agent.artifacts import (
    process_skill_file_uploads as _process_skill_file_uploads,
)
from management.services.agent.artifacts import (
    transform_skill_files_to_standard_format as _transform_skill_files_to_standard_format,
)
from management.services.agent.stream import AssistantMessageProjection
from management.services.agent.stream import safe_agent_stream_error_chunk as _safe_agent_stream_error_chunk
from nexent.core.agents.run_agent import (
    DeferredAgentRun,
    agent_run,
)
from nexent.core.concurrency import (
    ManagedExecution,
    ManagedTaskSpec,
    RunCancellationScope,
    ThreadManager,
    run_blocking,
)
from nexent.core.utils.observer import (
    ProcessType,
)
from nexent.memory.models import (
    MemoryIngestUnit,
)
from nexent.monitor import (
    agent_monitoring_context,
)
from management.services.conversation.service import (
    persist_assistant_run_batch,
    save_message,
    update_message_status,
)
from management.services.memory.extraction import (
    FaMemoryExtractor,
)
from management.services.memory.provider import (
    _build_ingestion_event_service,
    build_memory_service_for_fa_extraction,
)
from infrastructure.rdb.agent_execution import RunIdentity, finish_execution, stop_requested
from infrastructure.redis.agent_events import RunJournal
from infrastructure.redis.run_state import (
    runtime_state_service,
)
from management.services.agent.channels import (
    streaming_channel_manager,
)
from runtime.thread_management import (
    agent_stream_producer_tasks as _agent_stream_producer_tasks,
    channel_cleanup_tasks as _channel_cleanup_tasks,
    external_memory_ingest_tasks as _external_memory_ingest_tasks,
    fa_extraction_tasks as _fa_extraction_tasks,
    unregister_after_worker_exit,
    shutdown_agent_stream_tasks as shutdown_agent_stream_tasks,
)
from management.services.configuration.tenant.settings import (
    tenant_config_manager,
)

logger = logging.getLogger(__name__)
AGENTOS_PREPARATION_STOP = "agentos preparation stop"


def _unregister_agent_run_after_execution(conversation_id, user_id, status, agent_run_info=None) -> bool:
    return unregister_after_worker_exit(agent_run_manager, conversation_id, user_id, status, agent_run_info)


async def _cleanup_channel_later(
    conversation_id: int,
    user_id: str,
    delay: float = 5.0,
    expected_channel=None,
):
    """
    Remove the streaming channel after a delay to allow subscribers to finish.
    This gives reconnected clients time to receive the final chunks before cleanup.
    """
    await asyncio.sleep(delay)
    remove_kwargs = {}
    if expected_channel is not None:
        remove_kwargs["expected_channel"] = expected_channel
    await streaming_channel_manager.remove_channel(
        conversation_id,
        user_id,
        **remove_kwargs,
    )


async def _consume_agent_stream_producer(
    stream_gen,
    channel,
    agent_metadata,
    conversation_id: int,
    user_id: str,
) -> None:
    """Consume a non-debug agent stream independently from its SSE subscriber."""
    fallback_status = "failed"
    producer_error = False
    try:
        with agent_monitoring_context(agent_metadata):
            async for _ in stream_gen:
                pass
    except asyncio.CancelledError as exc:
        if exc.args == (AGENTOS_PREPARATION_STOP,):
            fallback_status = "stopped"
        try:
            await stream_gen.aclose()
        except (AttributeError, RuntimeError):
            logger.debug(
                "Agent stream generator was already closing conversation=%s",
                conversation_id,
            )
        raise
    except Exception as stream_exc:
        producer_error = True
        logger.error(
            "Agent stream response error: %r",
            stream_exc,
            exc_info=True,
        )
        if not channel.is_completed:
            try:
                await channel.publish(_safe_agent_stream_error_chunk(stream_exc))
            except Exception:
                logger.exception(
                    "Failed to publish producer error conversation=%s",
                    conversation_id,
                )
    finally:
        # _stream_agent_chunks normally owns persistence and terminal state.
        # This fallback covers failures before that generator is entered.
        if not channel.is_completed:
            if fallback_status == "failed" and not producer_error:
                logger.error(
                    "Agent stream producer exited without terminal state conversation=%s",
                    conversation_id,
                )
            try:
                run_info = agent_run_manager.get_agent_run_info(
                    conversation_id, user_id
                )
                _unregister_agent_run_after_execution(
                    conversation_id,
                    user_id,
                    status=fallback_status,
                    agent_run_info=run_info,
                )
            except Exception:
                logger.exception(
                    "Failed to unregister incomplete producer conversation=%s",
                    conversation_id,
                )
            try:
                await streaming_channel_manager.complete_channel(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    status=fallback_status,
                )
            except Exception:
                logger.exception(
                    "Failed to complete producer channel conversation=%s",
                    conversation_id,
                )
            cleanup_task = asyncio.create_task(
                _cleanup_channel_later(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    expected_channel=channel,
                )
            )
            _channel_cleanup_tasks.add(cleanup_task)
            cleanup_task.add_done_callback(_channel_cleanup_tasks.discard)
        identity = getattr(channel, "execution_identity", None)
        if isinstance(identity, RunIdentity):
            await run_blocking(
                "agentos-execution-finish", finish_execution, identity, channel.completion_status or fallback_status,
                lane="control-io", owner="runtime",
            )
        logger.info(
            "Agent stream cleanup conversation=%s status=%s active_runs=%s "
            "active_channels=%s active_producers=%s replay_bytes=%s",
            conversation_id,
            "failed" if not channel.is_completed else channel.completion_status,
            agent_run_manager.get_active_run_count(),
            streaming_channel_manager.get_active_channel_count(),
            len(_agent_stream_producer_tasks),
            streaming_channel_manager.get_retained_history_bytes(),
        )


def _run_journal(channel) -> RunIdentity | RunJournal | None:
    identity = getattr(channel, "execution_identity", None)
    if isinstance(identity, RunIdentity):
        return identity
    journal = getattr(channel, "run_journal", None)
    return journal if isinstance(journal, RunJournal) else None


async def _journal_stop_requested(journal: RunIdentity | RunJournal | None) -> bool:
    if journal is None:
        return False
    try:
        if isinstance(journal, RunIdentity):
            return await run_blocking(
                "agentos-poll-stop", stop_requested, journal, lane="control-io", owner="runtime",
            )
        return await run_blocking(
            "agentos-poll-stop", journal.is_stop_requested, lane="control-io", owner="runtime",
        )
    except (RedisError, SQLAlchemyError, RuntimeError):
        logger.warning("Could not check AgentOS stop signal for run %s", journal.run_id)
        return False


async def _cancel_preparation_on_agentos_stop(journal: RunIdentity | RunJournal, task: asyncio.Task) -> None:
    while not task.done():
        if await _journal_stop_requested(journal):
            task.cancel(AGENTOS_PREPARATION_STOP)
            return
        await asyncio.sleep(RUNTIME_CANCEL_POLL_INTERVAL_SECONDS)


async def _poll_runtime_cancel_signal(
    conversation_id: int, user_id: str, stop_event, cancellation_scope=None, *, journal=None,
) -> None:
    """Mirror Redis cancel signal into the local agent stop_event."""
    while not stop_event.is_set():
        scoped_stop = await _journal_stop_requested(journal)
        legacy_stop = not isinstance(journal, RunIdentity) and not scoped_stop and await runtime_state_service.is_cancelled_async(
            user_id=user_id, conversation_id=conversation_id,
        )
        if scoped_stop or legacy_stop:
            stop_event.set()
            if cancellation_scope is not None:
                cancellation_scope.cancel()
            logger.info(
                "Runtime cancel signal received, user_id=%s, conversation_id=%s",
                user_id,
                conversation_id,
            )
            return
        await asyncio.sleep(RUNTIME_CANCEL_POLL_INTERVAL_SECONDS)


async def _cancel_task_on_runtime_signal(
    conversation_id: int, user_id: str, task: asyncio.Task
) -> None:
    """Cancel a local asyncio task when another Pod writes the runtime cancel signal."""
    while not task.done():
        if await runtime_state_service.is_cancelled_async(
            user_id=user_id, conversation_id=conversation_id
        ):
            task.cancel()
            logger.info(
                "Runtime cancel signal cancelled task, user_id=%s, conversation_id=%s",
                user_id,
                conversation_id,
            )
            return
        await asyncio.sleep(RUNTIME_CANCEL_POLL_INTERVAL_SECONDS)


async def _stream_agent_chunks(
    agent_request: "AgentRequest",
    user_id: str,
    tenant_id: str,
    agent_run_info,
    memory_ctx,
    resume_from_unit_index: int = 0,
    resume_message_id: Optional[int] = None,
    channel: Optional[Any] = None,
    execution: Optional[ManagedExecution] = None,
    deferred_run: Optional[DeferredAgentRun] = None,
    *,
    thread_manager: ThreadManager | None = None,
):
    """
    Yield SSE chunks from agent_run while buffering assistant persistence.

    Args:
        resume_from_unit_index: If > 0, we're in resume mode and should start
                                the unit index counter from this position.
        resume_message_id: The existing message_id to use in resume mode
                          (instead of creating a new one).
        channel: Optional StreamingChannel for multi-subscriber support.
    """

    thread_manager = require_legacy_thread_manager(thread_manager)

    captured_skill_files: dict[str, dict] = {}
    skill_file_uploads: list[dict] = []
    workspace_file_uploads: dict[str, dict] = {}
    frontend_skill_files: list[dict] = []

    # Determine if we're in resume mode
    is_resume_mode = resume_from_unit_index > 0

    # Persist the parent ConversationMessage row up front with status='streaming'
    # so history and recovery can observe the active assistant run.
    streaming_message_id: Optional[int] = resume_message_id
    if not is_resume_mode and not agent_request.is_debug:
        user_role_count = sum(
            1
            for item in (getattr(agent_request, "history", None) or ())
            if item.role == MESSAGE_ROLE["USER"]
        )
        assistant_message_req = MessageRequest(
            conversation_id=agent_request.conversation_id,
            message_idx=user_role_count * 2 + 1,
            role=MESSAGE_ROLE["ASSISTANT"],
            message=[],
            minio_files=None,
        )
        tracking = _run_journal(channel)
        projection_options = {"execution_identity": tracking} if isinstance(tracking, RunIdentity) else {}
        try:
            streaming_message_id = save_message(
                assistant_message_req,
                user_id=user_id,
                tenant_id=tenant_id,
                status="streaming",
                message_source=getattr(agent_request, "_message_source", "CHAT"),
                **projection_options,
            )
        except Exception as msg_exc:
            if isinstance(tracking, RunIdentity):
                raise
            logger.error(
                "Failed to create streaming message row: %r", msg_exc, exc_info=True
            )

    projection = AssistantMessageProjection(
        persist_units=streaming_message_id is not None, next_unit_index=resume_from_unit_index,
    )
    # Set when the agent run loop finishes successfully.
    stream_completed_normally: bool = False

    # Get or create streaming channel for multi-subscriber support
    if channel is None:
        channel = await streaming_channel_manager.get_or_create_channel(
            conversation_id=agent_request.conversation_id, user_id=user_id
        )

    if agent_run_info.cancellation_scope is None:
        agent_run_info.cancellation_scope = RunCancellationScope(
            agent_run_info.stop_event
        )
    journal = _run_journal(channel)
    cancel_poll_task = asyncio.create_task(
        _poll_runtime_cancel_signal(
            conversation_id=agent_request.conversation_id,
            user_id=user_id,
            stop_event=agent_run_info.stop_event,
            cancellation_scope=agent_run_info.cancellation_scope,
            journal=journal,
        )
    )

    # In resume mode, emit a status event first
    if is_resume_mode:
        await channel.publish(STREAM_STATUS_EVENT)
        await channel.publish(
            f'data: {{"status": "resumed", "last_unit_index": {resume_from_unit_index - 1}}}\n\n'
        )
        yield STREAM_STATUS_EVENT
        yield f'data: {{"status": "resumed", "last_unit_index": {resume_from_unit_index - 1}}}\n\n'

    async def _iter_run_chunks():
        if journal is not None and (await _journal_stop_requested(journal) or agent_run_info.stop_event.is_set()):
            agent_run_info.cancellation_scope.cancel()
            if deferred_run is not None and execution is not None:
                agent_run_info.thread_future = execution.future
                agent_run_info.thread_execution_id = execution.execution_id
                deferred_run.cancel()
            return
        for event in getattr(
            agent_run_info.agent_config,
            "pre_run_tool_events",
            (),
        ):
            yield json.dumps(event, ensure_ascii=False)
        source = agent_run(
            agent_run_info,
            thread_manager=thread_manager,
            execution=execution,
            deferred_run=deferred_run,
        )
        async for agent_chunk in source:
            yield agent_chunk

    try:
        async for chunk in _iter_run_chunks():
            chunk, data = projection.project(chunk)
            chunk_type = data.get("type")

            if chunk_type == ProcessType.SKILL_ARTIFACT.value:
                artifact_content = data.get("content")
                if isinstance(artifact_content, str):
                    try:
                        artifact_content = json.loads(artifact_content)
                    except json.JSONDecodeError:
                        artifact_content = {}

                artifacts = (
                    artifact_content.get("artifacts", [])
                    if isinstance(artifact_content, dict)
                    else []
                )
                for artifact in artifacts:
                    if not isinstance(artifact, dict):
                        continue
                    absolute_path = str(artifact.get("absolute_path") or "").strip()
                    if not absolute_path or absolute_path in captured_skill_files:
                        continue
                    captured_skill_files[absolute_path] = artifact

                logger.info(
                    "[skill-file] received structured artifacts count=%s current_total=%s",
                    len(artifacts),
                    len(captured_skill_files),
                )
                continue

            if chunk_type == ProcessType.FILE_ARTIFACT.value:
                artifact_content = data.get("content")
                if isinstance(artifact_content, str):
                    try:
                        artifact_content = json.loads(artifact_content)
                    except json.JSONDecodeError:
                        artifact_content = {}
                artifacts = (
                    artifact_content.get("artifacts", [])
                    if isinstance(artifact_content, dict)
                    else []
                )
                for artifact in artifacts:
                    if not isinstance(artifact, dict):
                        continue
                    object_name = str(artifact.get("object_name") or "").strip()
                    if object_name:
                        workspace_file_uploads[object_name] = artifact
                continue

            should_parse_skill_file = (
                chunk_type in {"execution_logs", "parse"}
                or data.get("role") == "tool-response"
            )
            if should_parse_skill_file:
                extracted_payload_count = 0
                content_value = data.get("content")
                if isinstance(content_value, list):
                    content_items = content_value
                elif content_value:
                    content_items = [{"type": "text", "text": str(content_value)}]
                else:
                    content_items = []

                for item in content_items:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_value = item.get("text")
                        if text_value:
                            extracted_payloads = _extract_json_objects_from_text(
                                text_value
                            )
                            for payload in extracted_payloads:
                                absolute_path = str(
                                    payload.get("absolute_path") or ""
                                ).strip()
                                if not absolute_path:
                                    continue
                                if absolute_path in captured_skill_files:
                                    continue
                                if not os.path.exists(absolute_path):
                                    continue
                                captured_skill_files[absolute_path] = payload
                                extracted_payload_count += 1
                if extracted_payload_count:
                    logger.info(
                        "[skill-file] captured payloads count=%s current_total=%s",
                        extracted_payload_count,
                        len(captured_skill_files),
                    )

            await channel.publish(f"data: {chunk}\n\n")
            yield f"data: {chunk}\n\n"
        stream_completed_normally = True
    except Exception as run_exc:
        logger.error("Agent run error: %r", run_exc, exc_info=True)
        await channel.publish(_safe_agent_stream_error_chunk(run_exc))
        yield _safe_agent_stream_error_chunk(run_exc)
    finally:
        if not cancel_poll_task.done():
            cancel_poll_task.cancel()

        was_stopped = (
            getattr(agent_run_info, "stop_event", None)
            and agent_run_info.stop_event.is_set()
        )
        terminal_status = (
            "stopped"
            if was_stopped
            else "completed"
            if stream_completed_normally
            else "failed"
        )
        outcome = getattr(agent_run_info, "attempt_outcome", None)
        if outcome in {"failed", "stopped"}:
            # A typed terminal model error is delivered as a normal observer
            # ``error`` chunk, so the async iterator can finish normally while
            # the worker outcome still authoritatively marks the run failed.
            terminal_status = outcome

        try:
            skill_file_payloads = list(captured_skill_files.values())
            if skill_file_payloads:
                skill_file_uploads = await _process_skill_file_uploads(
                    payloads=skill_file_payloads,
                    user_id=user_id,
                    tenant_id=tenant_id,
                )
                skill_file_uploads = await thread_manager.run(
                    "control-io",
                    ManagedTaskSpec(
                        task_name="enrich-skill-file-urls",
                        owner="management.services.agent.run",
                    ),
                    _enrich_file_uploads_with_presigned_urls,
                    skill_file_uploads,
                )
                logger.info(
                    "[skill-file] upload finished conversation=%s result_count=%s results=%s",
                    agent_request.conversation_id,
                    len(skill_file_uploads),
                    skill_file_uploads,
                )
                if skill_file_uploads:
                    files_payload = json.dumps(
                        {"file_uploads": skill_file_uploads},
                        ensure_ascii=False,
                    )
                    files_chunk = (
                        "data: "
                        + json.dumps(
                            {"type": "files", "content": files_payload},
                            ensure_ascii=False,
                        )
                        + "\n\n"
                    )
                    try:
                        await channel.publish(files_chunk)
                        yield files_chunk
                    except RuntimeError:
                        # Stream is closing (e.g., client disconnect). Avoid raising during generator teardown.
                        pass
                    frontend_skill_files.extend(
                        _transform_skill_files_to_standard_format(skill_file_uploads)
                    )
        except Exception:
            logger.exception("Failed to process skill file uploads")

        if workspace_file_uploads:
            uploaded_files = await thread_manager.run(
                "control-io",
                ManagedTaskSpec(
                    task_name="enrich-workspace-file-urls",
                    owner="management.services.agent.run",
                ),
                _enrich_file_uploads_with_presigned_urls,
                list(workspace_file_uploads.values()),
            )
            files_payload = json.dumps(
                {"file_uploads": uploaded_files},
                ensure_ascii=False,
            )
            files_chunk = (
                "data: "
                + json.dumps(
                    {"type": "files", "content": files_payload},
                    ensure_ascii=False,
                )
                + "\n\n"
            )
            try:
                await channel.publish(files_chunk)
                yield files_chunk
            except RuntimeError:
                pass
            frontend_skill_files.extend(
                _transform_skill_files_to_standard_format(uploaded_files)
            )

        projection_run_id = getattr(agent_request, "_projection_run_id", None)
        mark_failed = update_message_status
        if projection_run_id is not None:
            from management.db.conversation.repository import fail_unfinished_assistant_projection

            mark_failed = partial(fail_unfinished_assistant_projection, tenant_id=tenant_id)
        terminal_status, persistence_failed, final_answer_content = await finalize_assistant_projection(
            thread_manager=thread_manager,
            message_id=streaming_message_id,
            conversation_id=agent_request.conversation_id,
            terminal_status=terminal_status,
            buffered_units=projection.units,
            buffered_search_records=projection.search_records,
            buffered_image_urls=projection.image_urls,
            frontend_skill_files=frontend_skill_files,
            buffered_automation_proposals=projection.automation_proposals,
            user_id=user_id,
            tenant_id=tenant_id,
            final_answer_content=projection.final_answer_content,
            run_outcome=agent_run_info,
            persist_batch=persist_assistant_run_batch,
            mark_failed=mark_failed,
            logger=logger,
            projection_run_id=projection_run_id,
        )
        if persistence_failed and channel is not None:
            persistence_error_chunk = _safe_agent_stream_error_chunk()
            await channel.publish(persistence_error_chunk)
            try:
                yield persistence_error_chunk
            except RuntimeError:
                pass

        _unregister_agent_run_after_execution(
            _agent_run_identifier(agent_request),
            user_id,
            status=terminal_status,
            agent_run_info=agent_run_info,
        )

        if channel is not None:
            await streaming_channel_manager.complete_channel(
                conversation_id=agent_request.conversation_id,
                user_id=user_id,
                status=terminal_status,
            )
            cleanup_task = asyncio.create_task(
                _cleanup_channel_later(
                    conversation_id=agent_request.conversation_id,
                    user_id=user_id,
                    expected_channel=channel,
                )
            )
            _channel_cleanup_tasks.add(cleanup_task)
            cleanup_task.add_done_callback(_channel_cleanup_tasks.discard)
        # Memory recording is now handled by the agent-side ``StoreMemoryTool``
        # (which delegates to the new ``MemoryService`` facade). The legacy
        # background ``add_memory_in_levels`` call has been removed because
        # its dual-level ``agent``/``user_agent`` semantics no longer map to
        # the new layered architecture (agents may only write to
        # ``agent.short_term``).

        if (
            terminal_status == "completed"
            and streaming_message_id is not None
            and memory_ctx is not None
            and getattr(
                getattr(memory_ctx, "user_config", None), "memory_switch", False
            )
        ):

            async def _per_turn_supplement() -> None:
                try:
                    units = get_units_by_message(streaming_message_id)
                    ingest_units = [
                        MemoryIngestUnit(
                            event_id=str(unit["unit_id"]),
                            event_type="turn_completed",
                            unit_type=unit["unit_type"],
                            unit_content=unit["unit_content"],
                            unit_index=unit["unit_index"],
                        )
                        for unit in units
                        if unit["unit_type"] != "final_answer"
                    ]
                    if not ingest_units:
                        return
                    await _build_ingestion_event_service().send_ingest_all_enabled(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        agent_id=str(getattr(agent_request, "agent_id", "")),
                        conversation_id=str(agent_request.conversation_id),
                        event_type="turn_completed",
                        event_id=str(streaming_message_id),
                        units=ingest_units,
                    )
                except Exception as exc:
                    logger.warning("Per-turn supplement failed: %s", exc)

            supplement_task = asyncio.create_task(_per_turn_supplement())
            _external_memory_ingest_tasks.add(supplement_task)
            supplement_task.add_done_callback(_external_memory_ingest_tasks.discard)

        if (
            final_answer_content
            and memory_ctx is not None
            and getattr(
                getattr(memory_ctx, "user_config", None), "memory_switch", False
            )
        ):

            async def _run_fa_extraction() -> None:
                try:
                    model_id = tenant_config_manager.get_app_config(
                        key=MODEL_CONFIG_MAPPING["llm"], tenant_id=tenant_id,
                    )
                    if not model_id:
                        logger.warning(
                            "fa_memory_extraction: no tenant LLM configured, skipping"
                        )
                        return

                    from management.services.memory.extraction import AgentOSMemoryExtractionModel

                    extractor = FaMemoryExtractor(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        agent_id=str(getattr(agent_request, "agent_id", "")),
                        conversation_id=str(
                            getattr(agent_request, "conversation_id", "")
                        ),
                        memory_service=build_memory_service_for_fa_extraction(),
                        model_client=AgentOSMemoryExtractionModel(
                            model_id=int(model_id), user_id=user_id, tenant_id=tenant_id,
                        ),
                    )
                    result = await extractor.extract_and_store(
                        final_answer_content,
                        user_query=str(getattr(agent_request, "query", "") or ""),
                    )
                    logger.info(
                        "fa_memory_extraction: tenant=%s user=%s agent=%s items=%d reason=%s",
                        tenant_id,
                        user_id,
                        str(getattr(agent_request, "agent_id", "")),
                        len(result.items),
                        result.reason,
                    )
                except Exception:
                    logger.exception("fa_memory_extraction: unexpected error")

            extraction_task = asyncio.create_task(_run_fa_extraction())
            _fa_extraction_tasks.add(extraction_task)
            extraction_task.add_done_callback(_fa_extraction_tasks.discard)


def _agent_run_identifier(agent_request: AgentRequest) -> int | str | None:
    debug_run_id = getattr(agent_request, "_debug_run_id", None)
    if isinstance(debug_run_id, str) and debug_run_id:
        return debug_run_id
    return agent_request.conversation_id
