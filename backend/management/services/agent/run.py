import asyncio
from http import HTTPStatus
import json
import logging
import os
import uuid
from typing import Any, Optional, Dict

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse
from nexent.core.agents.run_agent import agent_run
from nexent.memory.models import MemoryIngestUnit

from agents.agent_run_manager import AgentRunAlreadyActiveError, agent_run_manager
from agents.create_agent_info import create_agent_run_info
from agents.preprocess_manager import preprocess_manager
from consts.const import (
    DEFAULT_EN_TITLE,
    DEFAULT_ZH_TITLE,
    LANGUAGE,
    MESSAGE_ROLE,
    RUNTIME_CANCEL_POLL_INTERVAL_SECONDS,
    STREAM_STATUS_EVENT,
)
from consts.exceptions import (
    AppException,
    ConversationNotFoundError,
    ForbiddenError,
    MemoryPreparationException,
    RuntimeMetadataValidationError,
    RuntimeMetadataVersionConflict,
)
from consts.error_code import ErrorCode, RuntimeMetadataValidationCode
from nexent.core.utils.observer import ProcessType
from consts.model import (
    AgentRequest,
    MessageRequest,
    ConversationKnowledgeScopeRequest,
)
from database.agent_db import (
    search_agent_info_by_agent_id
)
from database.conversation_db import (
    get_units_by_message,
    resolve_conversation_runtime_metadata,
)
from utils.runtime_metadata_utils import (
    validate_runtime_metadata,
)
from database.tool_db import (
    query_tool_instances_by_id,  # noqa: F401 - compatibility patch point
)
from utils.time_context_utils import prepend_current_time
from services.conversation_management_service import (
    create_new_conversation,
    generate_conversation_title_service,  # noqa: F401 - compatibility patch point
    get_conversation_service,
    get_current_run_user_message_id,
    get_latest_assistant_message,
    get_last_unit_for_message,
    load_historical_context,
    persist_assistant_run_batch,
    persist_history_summary_candidate,
    save_conversation_user,
    save_message,
    save_message_unit,  # noqa: F401 - retained as a compatibility re-export
    update_conversation_agent_id_service,
    update_conversation_chat_mode_service,
    update_conversation_knowledge_scope_service,
    update_message_status,
    update_unit_status,  # noqa: F401 - retained as a compatibility re-export
)
from services.memory_config_service import build_memory_context
from services.memory_backend_adapter import _build_ingestion_event_service
from services.knowledge_scope_service import (
    build_runtime_knowledge_policy,
    build_runtime_knowledge_resources,
    resolve_knowledge_scope,
)
from services.streaming_channel import streaming_channel_manager
from services.runtime_state_service import runtime_state_service
from utils.auth_utils import get_current_user_info, get_user_language
from utils.agent_stream_utils import (
    enrich_file_uploads_with_presigned_urls as _enrich_file_uploads_with_presigned_urls,
    extract_json_objects_from_text as _extract_json_objects_from_text,
    process_skill_file_uploads as _process_skill_file_uploads,
    safe_agent_stream_error_chunk as _safe_agent_stream_error_chunk,
    serialize_stream_unit_content as _serialize_stream_unit_content,
    transform_skill_files_to_standard_format as _transform_skill_files_to_standard_format,
)
from utils.context_utils import build_authorized_context_input

# Monitoring utilities: bind Agent metadata once at the request boundary.
from nexent.monitor import agent_monitoring_context

# Import monitoring utilities
from management.services.agent.run_context import build_agent_run_context

logger = logging.getLogger(__name__)
AGENT_ICON_MAX_BYTES = 2 * 1024 * 1024
AGENT_ICON_CONTENT_TYPES = {
    "gif": "image/gif",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}
_channel_cleanup_tasks: set[asyncio.Task[None]] = set()
_agent_stream_producer_tasks: set[asyncio.Task[None]] = set()
_external_memory_ingest_tasks: set[asyncio.Task[None]] = set()


def _finalize_buffered_unit_fragments(message_units: list[dict[str, Any]]) -> int:
    """Join mergeable unit fragments once and return finalized UTF-8 bytes."""
    finalized_bytes = 0
    for unit in message_units:
        fragments = unit.pop("_content_fragments", None)
        if fragments is not None:
            content = "".join(fragments)
            unit["content"] = content
            unit["unit_content"] = content
        finalized_bytes += len(str(unit.get("unit_content", "")).encode("utf-8"))
    return finalized_bytes


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
    producer_error = False
    try:
        with agent_monitoring_context(agent_metadata):
            async for _ in stream_gen:
                pass
    except asyncio.CancelledError:
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
                await channel.publish(_safe_agent_stream_error_chunk())
            except Exception:
                logger.exception(
                    "Failed to publish producer error conversation=%s",
                    conversation_id,
                )
    finally:
        # _stream_agent_chunks normally owns persistence and terminal state.
        # This fallback covers failures before that generator is entered.
        if not channel.is_completed:
            if not producer_error:
                logger.error(
                    "Agent stream producer exited without terminal state conversation=%s",
                    conversation_id,
                )
            try:
                agent_run_manager.unregister_agent_run(
                    conversation_id,
                    user_id,
                    status="failed",
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
                    status="failed",
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


async def _poll_runtime_cancel_signal(conversation_id: int, user_id: str, stop_event) -> None:
    """Mirror Redis cancel signal into the local agent stop_event."""
    while not stop_event.is_set():
        if await runtime_state_service.is_cancelled_async(user_id=user_id, conversation_id=conversation_id):
            stop_event.set()
            logger.info(
                "Runtime cancel signal received, user_id=%s, conversation_id=%s",
                user_id,
                conversation_id,
            )
            return
        await asyncio.sleep(RUNTIME_CANCEL_POLL_INTERVAL_SECONDS)


async def _cancel_task_on_runtime_signal(conversation_id: int, user_id: str, task: asyncio.Task) -> None:
    """Cancel a local asyncio task when another Pod writes the runtime cancel signal."""
    while not task.done():
        if await runtime_state_service.is_cancelled_async(user_id=user_id, conversation_id=conversation_id):
            task.cancel()
            logger.info(
                "Runtime cancel signal cancelled task, user_id=%s, conversation_id=%s",
                user_id,
                conversation_id,
            )
            return
        await asyncio.sleep(RUNTIME_CANCEL_POLL_INTERVAL_SECONDS)


def _resolve_user_tenant_language(
    authorization: str,
    http_request: Request | None = None,
    user_id: str | None = None,
    tenant_id: str | None = None,
):
    """Resolve user_id, tenant_id, language with optional overrides.

    If user_id and tenant_id are provided, do not parse from authorization again.
    """
    if user_id is None or tenant_id is None:
        return get_current_user_info(authorization, http_request)
    else:
        return user_id, tenant_id, get_user_language(http_request)


async def _stream_agent_chunks(
    agent_request: "AgentRequest",
    user_id: str,
    tenant_id: str,
    agent_run_info,
    memory_ctx,
    resume_from_unit_index: int = 0,
    resume_message_id: Optional[int] = None,
    channel: Optional[Any] = None,
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

    # Types whose chunks should be merged into the previous unit boundary,
    # matching the legacy batch merge logic.
    _MERGEABLE_TYPES = {
        ProcessType.MODEL_OUTPUT_CODE.value,
        ProcessType.MODEL_OUTPUT_THINKING.value,
        ProcessType.MODEL_OUTPUT_DEEP_THINKING.value,
    }

    captured_skill_files: dict[str, dict] = {}
    skill_file_uploads: list[dict] = []
    workspace_file_uploads: dict[str, dict] = {}
    frontend_skill_files: list[dict] = []
    buffered_units: list[dict[str, Any]] = []
    buffered_search_records: list[dict[str, Any]] = []
    buffered_image_urls: list[str] = []
    buffered_image_url_set: set[str] = set()
    buffered_automation_proposals: list[dict[str, Any]] = []
    final_answer_content = ""

    # Determine if we're in resume mode
    is_resume_mode = resume_from_unit_index > 0

    # Persist the parent ConversationMessage row up front with status='streaming'
    # so history and recovery can observe the active assistant run.
    streaming_message_id: Optional[int] = resume_message_id
    if not is_resume_mode and not agent_request.is_debug:
        user_role_count = sum(
            1 for item in (getattr(agent_request, "history", None) or ())
            if item.role == MESSAGE_ROLE["USER"]
        )
        assistant_message_req = MessageRequest(
            conversation_id=agent_request.conversation_id,
            message_idx=user_role_count * 2 + 1,
            role=MESSAGE_ROLE["ASSISTANT"],
            message=[],
            minio_files=None,
        )
        try:
            streaming_message_id = save_message(
                assistant_message_req,
                user_id=user_id,
                tenant_id=tenant_id,
                status="streaming",
            )
        except Exception as msg_exc:
            logger.error(
                "Failed to create streaming message row: %r", msg_exc, exc_info=True)

    # Tracks the unit currently being accumulated in memory. Assistant output
    # is written to PostgreSQL only once, after the stream reaches a terminal
    # state. Redis/channel publication remains per chunk.
    current_unit: Optional[Dict[str, Any]] = None
    # The next unit_index to assign to a brand-new (non-merge) unit.
    # In resume mode, start from the position after the last persisted unit.
    next_unit_index: int = resume_from_unit_index
    # Set when the agent run loop finishes successfully.
    stream_completed_normally: bool = False

    # Get or create streaming channel for multi-subscriber support
    if channel is None:
        channel = await streaming_channel_manager.get_or_create_channel(
            conversation_id=agent_request.conversation_id,
            user_id=user_id
        )

    cancel_poll_task = asyncio.create_task(
        _poll_runtime_cancel_signal(
            conversation_id=agent_request.conversation_id,
            user_id=user_id,
            stop_event=agent_run_info.stop_event,
        )
    )

    # In resume mode, emit a status event first
    if is_resume_mode:
        await channel.publish(STREAM_STATUS_EVENT)
        await channel.publish(f'data: {{"status": "resumed", "last_unit_index": {resume_from_unit_index - 1}}}\n\n')
        yield STREAM_STATUS_EVENT
        yield f'data: {{"status": "resumed", "last_unit_index": {resume_from_unit_index - 1}}}\n\n'

    async def _iter_run_chunks():
        for event in getattr(
            agent_run_info.agent_config,
            "pre_run_tool_events",
            (),
        ):
            yield json.dumps(event, ensure_ascii=False)
        async for agent_chunk in agent_run(agent_run_info):
            yield agent_chunk

    try:
        async for chunk in _iter_run_chunks():
            chunk_type: Optional[str] = None
            chunk_content: str = ""
            try:
                data = json.loads(chunk)
                chunk_type = data.get("type")
                chunk_content = data.get("content", "") or ""

                # Add unit_index to the chunk data for frontend resume skip logic.
                # This allows frontend to accurately skip chunks that were already persisted.
                # For mergeable types (continuing chunks), use the current unit's index.
                # For new units, use the next_unit_index that will be assigned.
                if streaming_message_id is not None and chunk_type:
                    mergeable = chunk_type in _MERGEABLE_TYPES
                    if current_unit is not None and mergeable and current_unit.get("type") == chunk_type:
                        # Continuing chunk - use current unit's index
                        data["unit_index"] = current_unit["unit_index"]
                    elif chunk_type not in ("search_content_placeholder",):
                        # New unit - this will be the next index after assignment
                        data["unit_index"] = next_unit_index
                    # Tool events and side-channel output carry the same ID
                    # from the observer's actual invocation context.
                    # Re-serialize the chunk with unit_index for accurate frontend skip
                    chunk = json.dumps(data)
                    logger.debug(f"[resume-debug] Added unit_index to chunk: type={chunk_type}, unit_index={data.get('unit_index')}")
            except Exception:
                # Malformed chunk: emit as-is and skip persistence bookkeeping.
                await channel.publish(f"data: {chunk}\n\n")
                yield f"data: {chunk}\n\n"
                continue

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
                            extracted_payloads = _extract_json_objects_from_text(text_value)
                            for payload in extracted_payloads:
                                absolute_path = str(payload.get("absolute_path") or "").strip()
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

            # Buffer assistant persistence in memory. Redis/channel publication
            # below remains per chunk; PostgreSQL is touched only once after the
            # stream reaches a terminal state.
            if streaming_message_id is not None and chunk_type:
                mergeable = chunk_type in _MERGEABLE_TYPES
                is_continuation = (
                    current_unit is not None
                    and mergeable
                    and current_unit.get("type") == chunk_type
                )

                if is_continuation:
                    current_unit["_content_fragments"].append(chunk_content)
                else:
                    if chunk_type == "final_answer":
                        final_answer_content = chunk_content

                    if chunk_type == "picture_web":
                        try:
                            content_json = json.loads(chunk_content)
                            if isinstance(content_json, dict) and "images_url" in content_json:
                                for image_url in content_json["images_url"]:
                                    if image_url and image_url not in buffered_image_url_set:
                                        buffered_image_url_set.add(image_url)
                                        buffered_image_urls.append(image_url)
                        except Exception as img_exc:
                            logger.error(
                                "Failed to buffer picture_web sources: %r", img_exc, exc_info=True
                            )

                    if chunk_type == "search_content":
                        placeholder_index = next_unit_index
                        buffered_units.append({
                            "type": "search_content_placeholder",
                            "content": '{"placeholder": true}',
                            "unit_index": placeholder_index,
                            "unit_type": "search_content_placeholder",
                            "unit_content": '{"placeholder": true}',
                            "tool_call_id": data.get("tool_call_id"),
                            "invocation_id": data.get("invocation_id"),
                            "mergeable": False,
                        })
                        try:
                            search_results = json.loads(chunk_content)
                            if not isinstance(search_results, list):
                                search_results = [search_results]
                            for result in search_results:
                                buffered_search_records.append({
                                    "unit_index": placeholder_index,
                                    "source_type": result.get("source_type", ""),
                                    "source_title": result.get("title", ""),
                                    "source_location": result.get("url", ""),
                                    "source_content": result.get("text", ""),
                                    "score_overall": float(result.get("score"))
                                    if result.get("score") not in (None, "")
                                    else None,
                                    "score_accuracy": float(result.get("score_details", {}).get("accuracy"))
                                    if result.get("score_details", {}).get("accuracy") not in (None, "")
                                    else None,
                                    "score_semantic": float(result.get("score_details", {}).get("semantic"))
                                    if result.get("score_details", {}).get("semantic") not in (None, "")
                                    else None,
                                    "published_date": result.get("published_date")
                                    if result.get("published_date") not in (None, "")
                                    else None,
                                    "cite_index": result.get("cite_index")
                                    if result.get("cite_index") != ""
                                    else None,
                                    "search_type": result.get("search_type")
                                    if result.get("search_type")
                                    else None,
                                    "tool_sign": result.get("tool_sign", ""),
                                })
                        except Exception as src_exc:
                            logger.error(
                                "Failed to buffer search_content sources: %r", src_exc, exc_info=True
                            )
                        current_unit = None
                        next_unit_index += 1
                        await channel.publish(f"data: {chunk}\n\n")
                        yield f"data: {chunk}\n\n"
                        continue

                    # history_summary is already persisted once by the canonical
                    # checkpoint sink on its covered assistant message. The stream
                    # event is display-only and must not create a duplicate unit on
                    # the currently-running assistant message.
                    if chunk_type == "history_summary":
                        current_unit = None
                    elif streaming_message_id is not None and chunk_type not in (
                        "search_content_placeholder",
                    ):
                        persisted_content = _serialize_stream_unit_content(
                            data, chunk_content
                        )
                        current_unit = {
                            "type": chunk_type,
                            "content": persisted_content,
                            "unit_index": next_unit_index,
                            "unit_type": chunk_type,
                            "unit_content": persisted_content,
                            "tool_call_id": data.get("tool_call_id"),
                            "invocation_id": data.get("invocation_id"),
                            "mergeable": mergeable,
                        }
                        if mergeable:
                            current_unit["_content_fragments"] = [persisted_content]
                            current_unit["content"] = ""
                            current_unit["unit_content"] = ""
                        buffered_units.append(current_unit)
                        if chunk_type == "automation_proposal":
                            try:
                                proposal_payload = json.loads(persisted_content)
                                buffered_automation_proposals.append({
                                    "unit_index": next_unit_index,
                                    "proposal_id": int(proposal_payload["proposal_id"]),
                                })
                            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                                logger.warning(
                                    "Invalid persisted automation proposal event payload"
                                )
                        next_unit_index += 1

            await channel.publish(f"data: {chunk}\n\n")
            yield f"data: {chunk}\n\n"
        stream_completed_normally = True
    except Exception as run_exc:
        logger.error("Agent run error: %r", run_exc, exc_info=True)
        await channel.publish(_safe_agent_stream_error_chunk())
        yield _safe_agent_stream_error_chunk()
    finally:
        if not cancel_poll_task.done():
            cancel_poll_task.cancel()

        was_stopped = getattr(agent_run_info, "stop_event", None) and agent_run_info.stop_event.is_set()
        terminal_status = 'stopped' if was_stopped else 'completed' if stream_completed_normally else 'failed'

        try:
            skill_file_payloads = list(captured_skill_files.values())
            if skill_file_payloads:
                skill_file_uploads = await _process_skill_file_uploads(
                    payloads=skill_file_payloads,
                    user_id=user_id,
                    tenant_id=tenant_id,
                )
                skill_file_uploads = await asyncio.to_thread(
                    _enrich_file_uploads_with_presigned_urls,
                    skill_file_uploads,
                )
                logger.info(
                    "[skill-file] upload finished conversation=%s result_count=%s results=%s",
                    agent_request.conversation_id,
                    len(skill_file_uploads), skill_file_uploads
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
            uploaded_files = await asyncio.to_thread(
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

        persistence_failed = False
        if streaming_message_id is not None:
            try:
                persistence_bytes = _finalize_buffered_unit_fragments(buffered_units)
                logger.info(
                    "Finalizing assistant persistence conversation=%s units=%s bytes=%s",
                    agent_request.conversation_id,
                    len(buffered_units),
                    persistence_bytes,
                )
                await asyncio.to_thread(
                    persist_assistant_run_batch,
                    message_id=streaming_message_id,
                    conversation_id=agent_request.conversation_id,
                    message_content=final_answer_content,
                    terminal_status=terminal_status,
                    message_units=buffered_units,
                    search_records=buffered_search_records,
                    image_urls=buffered_image_urls,
                    skill_files=frontend_skill_files,
                    automation_proposals=buffered_automation_proposals,
                    user_id=user_id,
                    tenant_id=tenant_id,
                )
            except Exception:
                persistence_failed = True
                terminal_status = "failed"
                logger.exception(
                    "Failed to persist assistant stream batch conversation=%s message=%s",
                    agent_request.conversation_id,
                    streaming_message_id,
                )
                try:
                    await asyncio.to_thread(
                        update_message_status,
                        streaming_message_id,
                        "failed",
                        user_id,
                    )
                except Exception:
                    logger.exception(
                        "Failed to mark assistant message as failed after batch rollback"
                    )

        if persistence_failed and channel is not None:
            persistence_error_chunk = _safe_agent_stream_error_chunk()
            await channel.publish(persistence_error_chunk)
            try:
                yield persistence_error_chunk
            except RuntimeError:
                pass

        agent_run_manager.unregister_agent_run(
            _agent_run_identifier(agent_request),
            user_id,
            status=terminal_status,
            agent_run_info=agent_run_info,
        )

        if channel is not None:
            await streaming_channel_manager.complete_channel(
                conversation_id=agent_request.conversation_id,
                user_id=user_id,
                status=terminal_status
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
            and getattr(getattr(memory_ctx, "user_config", None), "memory_switch", False)
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


def _agent_run_identifier(agent_request: AgentRequest) -> int | str | None:
    debug_run_id = getattr(agent_request, "_debug_run_id", None)
    if isinstance(debug_run_id, str) and debug_run_id:
        return debug_run_id
    return agent_request.conversation_id


# Helper function for run_agent_stream, used to prepare context for an agent run
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
        user_id, tenant_id, agent_request.agent_id, skip_query=not allow_memory_search)

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
        "requested_output_tokens": agent_request.requested_output_tokens,
        "tool_params": agent_request.tool_params,
        "conversation_id": agent_request.conversation_id,
        "context_policy": agent_request.context_policy,
        "enable_planning": agent_request.enable_plan,
    }
    runtime_knowledge_context = getattr(agent_request, "_runtime_knowledge_context", None)
    if isinstance(runtime_knowledge_context, dict):
        create_run_kwargs["runtime_knowledge_context"] = runtime_knowledge_context
    if not agent_request.enable_automation_tool:
        create_run_kwargs["enable_automation_tool"] = False
    agent_run_info = await create_agent_run_info(
        **create_run_kwargs,
    )
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
        if not isinstance(current_message_id, int) or isinstance(current_message_id, bool):
            current_message_id = None
            logger.warning("Current user message boundary is unavailable; historical checkpoint loading skipped")
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
    cm_config = getattr(agent_run_info.agent_config,
                        'context_manager_config', None)
    if cm_config:
        cm_config.history_summary_sink = (
            (lambda candidate: persist_history_summary_candidate(
                agent_request.conversation_id, candidate, user_id, tenant_id
            )) if historical_context is not None else None
        )
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


# Helper function for run_agent_stream, used to save the user-side message
# before streaming begins. Assistant output is buffered by _stream_agent_chunks
# and finalized through persist_assistant_run_batch.
def save_messages(agent_request, target: str, user_id: str, tenant_id: str, messages=None):
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


# Helper function for run_agent_stream. ``enable_memory`` controls whether
# fixed pre-run retrieval and the model-directed store_memory tool are enabled.
async def generate_stream(
    agent_request: AgentRequest,
    user_id: str,
    tenant_id: str,
    language: str = LANGUAGE["ZH"],
    enable_memory: bool = False,
    channel: Optional[Any] = None,
    reservation_token: Optional[str] = None,
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

        async for data_chunk in _stream_agent_chunks(
            agent_request=agent_request,
            user_id=user_id,
            tenant_id=tenant_id,
            agent_run_info=agent_run_info,
            memory_ctx=memory_context,
            channel=channel,
        ):
            yield data_chunk

    except MemoryPreparationException:
        if not enable_memory:
            # No-memory path has no fallback; surface the failure cleanly.
            logger.error(
                "Agent run error without memory: %r", None, exc_info=True
            )
            await channel.publish(_safe_agent_stream_error_chunk())
            yield _safe_agent_stream_error_chunk()
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
            ):
                yield data_chunk
        except Exception as run_exc:
            logger.error(
                "Agent run error after memory failure: %r",
                run_exc,
                exc_info=True,
            )
            await channel.publish(_safe_agent_stream_error_chunk())
            yield _safe_agent_stream_error_chunk()
            return
    except Exception as stream_exc:
        logger.error(
            "Generate stream error: %r",
            stream_exc,
            exc_info=True,
        )
        await channel.publish(_safe_agent_stream_error_chunk())
        yield _safe_agent_stream_error_chunk()
        return
    finally:
        if cancel_poll_task and not cancel_poll_task.done():
            cancel_poll_task.cancel()
        if reservation_token is not None:
            agent_run_manager.release_agent_run_reservation(
                _agent_run_identifier(agent_request),
                user_id,
                reservation_token,
            )


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
            'should_resume': False,
            'message_id': None,
            'message_status': None,
            'resume_from_unit_index': None,
            'reason': 'no_assistant_message'
        }

    message_status = latest_msg.get('status')
    message_id = latest_msg['message_id']

    # Check if channel exists and is still active
    channel = streaming_channel_manager.get_channel(conversation_id, user_id)
    channel_active = channel is not None and not channel.is_completed

    if message_status == 'streaming':
        # Backend still running - get last unit position
        last_unit = get_last_unit_for_message(message_id)
        resume_from = last_unit['unit_index'] + 1 if last_unit else 0
        return {
            'should_resume': True,
            'message_id': message_id,
            'message_status': message_status,
            'resume_from_unit_index': resume_from,
            'resume_message_id': message_id,
            'reason': 'backend_streaming'
        }
    elif channel_active:
        # Message shows completed but channel is still active - resume to get remaining chunks
        # This handles edge case where message status was updated but channel not yet cleaned up
        last_unit = get_last_unit_for_message(message_id)
        resume_from = last_unit['unit_index'] + 1 if last_unit else 0
        return {
            'should_resume': True,
            'message_id': message_id,
            'message_status': message_status,
            'resume_from_unit_index': resume_from,
            'resume_message_id': message_id,
            'reason': 'channel_active'
        }
    else:
        # Backend finished - no more chunks to stream
        return {
            'should_resume': False,
            'message_id': message_id,
            'message_status': message_status,
            'resume_from_unit_index': None,
            'resume_message_id': None,
            'reason': f'backend_{message_status}'
        }


async def run_agent_stream(
    agent_request: AgentRequest,
    http_request: Request,
    authorization: str,
    user_id: str = None,
    tenant_id: str = None,
    skip_user_save: bool = False,
    resume: bool = False,
):
    """
    Start an agent run and stream responses.
    If user_id or tenant_id is provided, authorization will be overridden. (Useful in northbound apis)

    Args:
        resume: If True, check for existing streaming message and continue from where it left off
    """
    resolved_user_id, resolved_tenant_id, language = _resolve_user_tenant_language(
        authorization=authorization,
        http_request=http_request,
        user_id=user_id,
        tenant_id=tenant_id,
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
    )  # pragma: no cover

    conversation = None
    if not agent_request.is_debug and agent_request.conversation_id is not None:
        conversation = get_conversation_service(
            conversation_id=agent_request.conversation_id,
            user_id=resolved_user_id,
            tenant_id=resolved_tenant_id,
        )
        if conversation is None:
            raise ForbiddenError("Conversation is not accessible to the current identity")

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
    metadata_entrypoint = getattr(agent_request, "_runtime_metadata_entrypoint", "native")
    if metadata_update_requested and metadata_entrypoint in {"native", "debug"}:
        agent_record = search_agent_info_by_agent_id(
            agent_id=agent_request.agent_id,
            tenant_id=resolved_tenant_id,
            version_no=agent_request.version_no or 0,
        )
        if not bool(agent_record.get("allow_chat_metadata", False)):
            raise AppException(ErrorCode.CHAT_METADATA_NOT_ALLOWED)

    raw_request_scope = None if resume else getattr(agent_request, "knowledge_scope", None)
    if isinstance(raw_request_scope, ConversationKnowledgeScopeRequest):
        request_scope = raw_request_scope
    elif isinstance(raw_request_scope, dict):
        request_scope = ConversationKnowledgeScopeRequest.model_validate(raw_request_scope)
    else:
        request_scope = None
    stored_scope = conversation.get("knowledge_scope") if conversation else None
    if not isinstance(stored_scope, dict):
        stored_scope = None
    source_scope = request_scope
    if source_scope is None and stored_scope is not None and not resume:
        source_scope = ConversationKnowledgeScopeRequest.model_validate(stored_scope)

    resolved_scope = None
    if source_scope is not None and not resume:
        if agent_request.agent_id is None:
            raise ValueError("agent_id is required when knowledge_scope is set")
        resolved_scope = resolve_knowledge_scope(
            scope=source_scope,
            agent_id=agent_request.agent_id,
            tenant_id=resolved_tenant_id,
            user_id=resolved_user_id,
            version_no=agent_request.version_no,
            is_debug=bool(agent_request.is_debug),
            request_tool_params=agent_request.tool_params,
        )
        agent_request.tool_params = resolved_scope.tool_params
        agent_request.__dict__["_runtime_knowledge_context"] = {
            "policy": build_runtime_knowledge_policy(language),
            "resources": build_runtime_knowledge_resources(resolved_scope, language),
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
        default_title = DEFAULT_EN_TITLE if language == LANGUAGE["EN"] else DEFAULT_ZH_TITLE
        conversation_kwargs = {
            "title": default_title,
            "user_id": resolved_user_id,
            "agent_id": agent_request.agent_id,
            "chat_mode": "planning" if agent_request.enable_plan else "execution",
        }
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
        if agent_request.is_debug:
            metadata_snapshot = dict(agent_request.metadata or {}) if metadata_update_requested else {}
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
        elif not metadata_update_requested:
            metadata_snapshot = dict((conversation or {}).get("runtime_metadata") or {})
            metadata_version = int((conversation or {}).get("runtime_metadata_version") or 0)
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

        if not resume_info['should_resume']:
            # Backend already finished
            return JSONResponse(
                status_code=HTTPStatus.OK,
                content={
                    'status': resume_info['message_status'],
                    'message': f"Stream already {resume_info['message_status']}: {resume_info['reason']}",
                }
            )

        # Check if the agent is still running by querying the agent_run_manager
        existing_run_info = agent_run_manager.get_agent_run_info(
            user_id=resolved_user_id,
            conversation_id=agent_request.conversation_id
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
                    message_id=resume_info['message_id'],
                    status='completed'
                )
            except Exception:
                pass

            return JSONResponse(
                status_code=HTTPStatus.OK,
                content={
                    'status': 'completed',
                    'message': 'Agent finished during disconnection',
                }
            )

        # Agent is still running - subscribe to the channel to receive new chunks
        channel = streaming_channel_manager.get_channel(
            conversation_id=agent_request.conversation_id,
            user_id=resolved_user_id
        )
        last_unit_index = resume_info["resume_from_unit_index"] - 1

        def _resume_status_chunk(replay_chunk_count: int) -> str:
            payload = {
                'status': 'resumed',
                'last_unit_index': last_unit_index,
                'replay_chunk_count': replay_chunk_count,
            }
            return f"data: {json.dumps(payload)}\n\n"

        def _resume_completed_chunk(status: str = "completed") -> str:
            payload = {
                'status': status,
                'last_unit_index': last_unit_index,
            }
            return f"data: {json.dumps(payload)}\n\n"

        if channel is None:
            if runtime_state_service.enabled and is_remote_running:
                async def redis_channel_stream():
                    replay_events = await runtime_state_service.read_stream_events_async(
                        user_id=resolved_user_id,
                        conversation_id=agent_request.conversation_id,
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
                        events = await runtime_state_service.wait_for_stream_events_async(
                            user_id=resolved_user_id,
                            conversation_id=agent_request.conversation_id,
                            last_id=last_event_id,
                        )
                        for event_id, chunk in events:
                            last_event_id = event_id
                            if chunk:
                                yield chunk

                        stream_status = await runtime_state_service.get_stream_status_async(
                            user_id=resolved_user_id,
                            conversation_id=agent_request.conversation_id,
                        )
                        latest_run_state = await runtime_state_service.get_run_state_async(
                            user_id=resolved_user_id,
                            conversation_id=agent_request.conversation_id,
                        )
                        if stream_status.get("status") or latest_run_state.get("status") in {
                            "completed",
                            "failed",
                            "stopped",
                        }:
                            break

                    terminal_status = stream_status.get("status") or latest_run_state.get("status") or "completed"
                    yield STREAM_STATUS_EVENT
                    yield _resume_completed_chunk(terminal_status)

                return StreamingResponse(
                    redis_channel_stream(),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Stream-Status": "resumed",
                        "X-Last-Unit-Index": str(resume_info['resume_from_unit_index']),
                    },
                )

            # No channel exists, agent might be in a different state
            return JSONResponse(
                status_code=HTTPStatus.OK,
                content={
                    'status': 'streaming',
                    'message': 'Stream channel not found',
                }
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
                "X-Stream-Status": "resumed",
                "X-Last-Unit-Index": str(resume_info['resume_from_unit_index']),
            },
        )

    # Normal mode: start new stream
    try:
        reservation_token = agent_run_manager.reserve_agent_run(
            _agent_run_identifier(agent_request),
            resolved_user_id,
        )
    except AgentRunAlreadyActiveError:
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
            agent_request, resolved_user_id, resolved_tenant_id, language,
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
                producer_task.add_done_callback(
                    _agent_stream_producer_tasks.discard
                )

            # Emit conversation_created event for new conversations
            if is_new_conversation:
                yield "data: " + json.dumps({"type": "conversation_created", "content": {"conversation_id": agent_request.conversation_id}}, ensure_ascii=False) + "\n\n"

            scope_event = getattr(agent_request, "_resolved_knowledge_scope_event", None)
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
            yield _safe_agent_stream_error_chunk()
        finally:
            agent_run_manager.release_agent_run_reservation(
                _agent_run_identifier(agent_request),
                resolved_user_id,
                reservation_token,
            )

    headers = {"Cache-Control": "no-cache", "Connection": "keep-alive"}
    debug_run_id = getattr(agent_request, "_debug_run_id", None)
    if debug_run_id is not None:
        headers["run_id"] = debug_run_id
    if agent_request.conversation_id is not None:
        headers["conversation_id"] = str(agent_request.conversation_id)
    runtime_metadata_version = getattr(
        agent_request, "_runtime_metadata_version", None
    )
    if runtime_metadata_version is not None:
        headers["X-Runtime-Metadata-Version"] = str(runtime_metadata_version)

    return StreamingResponse(
        stream_with_agent_context(),
        media_type="text/event-stream",
        headers=headers,
    )


async def run_agent_background(
    agent_request: AgentRequest,
    user_id: str,
    tenant_id: str,
    language: str = LANGUAGE["ZH"],
    skip_user_save: bool = False,
) -> Dict[str, Any]:
    """
    Run an agent without returning an SSE response.

    This path is used by background automation tasks. It reuses the same
    preparation, monitoring, memory and message persistence flow as
    run_agent_stream, but consumes generated chunks internally.
    """
    if not agent_request.conversation_id:
        raise ValueError("conversation_id is required for background agent runs")

    if not agent_request.is_debug and not skip_user_save:
        save_messages(
            agent_request,
            target=MESSAGE_ROLE["USER"],
            user_id=user_id,
            tenant_id=tenant_id,
        )

    run_context = build_agent_run_context(
        agent_request, user_id, tenant_id, language,
        extra_metadata={"background": True, "skip_user_save": skip_user_save},
    )
    agent_metadata = run_context.metadata
    stream_gen = generate_stream(
        agent_request, user_id=user_id, tenant_id=tenant_id, language=language,
        enable_memory=run_context.enable_memory,
    )

    chunks = 0
    with agent_monitoring_context(agent_metadata):
        async for _ in stream_gen:
            chunks += 1

    latest_message = get_latest_assistant_message(agent_request.conversation_id, user_id)
    return {
        "conversation_id": agent_request.conversation_id,
        "assistant_message_id": latest_message.get("message_id") if latest_message else None,
        "chunks": chunks,
    }


def stop_agent_tasks(conversation_id: int | str, user_id: str):
    """
    Stop an agent run by its conversation ID or ephemeral debug run ID.
    Matches the behavior of agent_app.agent_stop_api.
    """
    # Stop agent run
    agent_stopped = agent_run_manager.stop_agent_run(conversation_id, user_id)

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


def is_agent_running(conversation_id: int, user_id: str) -> bool:
    return agent_run_manager.get_agent_run_info(conversation_id, user_id) is not None
