"""Persist Workbench creation runs without changing the editor's ephemeral NL2 flows."""

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from consts.model import MessageRequest, MessageUnit, WorkbenchSessionConfig
from database.agent_db import query_agent_records_for_nl2agent
from database.conversation_db import get_conversation_history, rebind_conversation_agent_id
from services.conversation_management_service import (
    create_new_conversation,
    save_message,
    save_message_unit,
)

logger = logging.getLogger(__name__)
_CREATION_MODES = {"agent_create", "skill_create"}


def _file_object_names(files: Any) -> list[str]:
    if not isinstance(files, list):
        return []
    return [
        item if isinstance(item, str) else str(item.get("object_name") or "")
        for item in files
    ]


def prepare_creation_history(
    *,
    conversation_id: int | None,
    mode: str,
    query: str,
    minio_files: list[dict[str, Any]] | None,
    workbench_config: dict[str, Any] | None,
    agent_id: int | None,
    user_id: str,
    tenant_id: str,
    retry_user_message_id: int | None = None,
    retry_message_index: int | None = None,
) -> tuple[int, int]:
    """Verify the owner and creation mode, then persist the current user turn."""
    if mode not in _CREATION_MODES:
        raise ValueError("Unsupported Workbench creation mode")
    if conversation_id is None:
        if retry_user_message_id is not None or retry_message_index is not None:
            raise ValueError("Cannot retry without a creation conversation")
        if not isinstance(workbench_config, dict):
            raise ValueError("Invalid Workbench creation configuration")
        normalized_config = WorkbenchSessionConfig.model_validate(
            workbench_config
        ).model_dump(mode="json")
        if normalized_config["mode"] != mode:
            raise ValueError("Invalid Workbench creation configuration")
        created = create_new_conversation(
            title="新对话",
            user_id=user_id,
            agent_id=agent_id if mode == "agent_create" else None,
            workbench_config=normalized_config,
        )
        resolved_id = int(created["conversation_id"])
        next_index = 0
    else:
        history = get_conversation_history(conversation_id, user_id)
        if not history or (history.get("workbench_config") or {}).get("mode") != mode:
            raise ValueError("Conversation is not an accessible creation session")
        if mode == "agent_create" and history.get("agent_id") != agent_id:
            old_agent_id = history.get("agent_id")
            old_records = (
                query_agent_records_for_nl2agent(old_agent_id, tenant_id)
                if isinstance(old_agent_id, int) and old_agent_id > 0
                else []
            )
            # An inaccessible or still-live Agent must never be silently replaced.
            # Soft-deleted tenant-owned records are the only recoverable case.
            if (
                retry_user_message_id is not None
                or retry_message_index is not None
                or not isinstance(agent_id, int)
                or agent_id <= 0
                or not old_records
                or any(record.get("delete_flag") != "Y" for record in old_records)
                or not rebind_conversation_agent_id(
                    conversation_id, old_agent_id, agent_id, user_id
                )
            ):
                raise ValueError("Agent does not match the creation session")
        resolved_id = conversation_id
        if retry_user_message_id is not None or retry_message_index is not None:
            user_record = next(
                (
                    item for item in history["message_records"]
                    if item.get("role") == "user"
                    and (
                        item.get("message_id") == retry_user_message_id
                        if retry_user_message_id is not None
                        else item.get("message_index") == retry_message_index
                    )
                ),
                None,
            )
            if (
                user_record is None
                or (retry_message_index is not None and
                    user_record.get("message_index") != retry_message_index)
                or user_record.get("message_content") != query
                or _file_object_names(user_record.get("minio_files"))
                != _file_object_names(minio_files)
            ):
                raise ValueError("Invalid creation retry target")
            assistant_index = int(user_record["message_index"]) + 1
            if not any(
                item.get("role") == "assistant"
                and item.get("message_index") == assistant_index
                for item in history["message_records"]
            ):
                raise ValueError("Creation retry target has no assistant response")
            return resolved_id, assistant_index
        next_index = max(
            (int(item["message_index"]) for item in history["message_records"]),
            default=-1,
        ) + 1

    save_message(
        MessageRequest(
            conversation_id=resolved_id,
            message_idx=next_index,
            role="user",
            message=[MessageUnit(type="string", content=query)],
            minio_files=minio_files,
        ),
        user_id=user_id,
        tenant_id=tenant_id,
    )
    return resolved_id, next_index + 1


async def persist_creation_stream(
    stream: AsyncIterator[str],
    *,
    conversation_id: int,
    assistant_index: int,
    user_id: str,
    tenant_id: str,
) -> AsyncIterator[str]:
    """Forward each SSE event unchanged and save a replayable assistant turn."""
    units: list[tuple[str, str]] = []
    status = "completed"
    try:
        async for event in stream:
            for line in event.splitlines():
                if not line.startswith("data: "):
                    continue
                try:
                    chunk = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                if not isinstance(chunk, dict) or not isinstance(chunk.get("type"), str):
                    continue
                kind = chunk["type"]
                raw_content = chunk.get("content")
                content = (
                    raw_content
                    if isinstance(raw_content, str)
                    else json.dumps(raw_content, ensure_ascii=False)
                )
                if kind in {
                    "skill_body", "file_content", "agent_new_run",
                    "target_files", "model_attempt_control", "done",
                }:
                    content = json.dumps(chunk, ensure_ascii=False)
                units.append((kind, content))
                if kind == "error":
                    status = "failed"
            yield event
    except BaseException:
        status = "stopped"
        raise
    finally:
        try:
            message = MessageRequest(
                conversation_id=conversation_id,
                message_idx=assistant_index,
                role="assistant",
                message=[
                    MessageUnit(type=kind, content=content)
                    for kind, content in units
                ],
            )
            message_id = save_message(
                message,
                user_id=user_id,
                tenant_id=tenant_id,
                status=status,
            )
            for index, (kind, content) in enumerate(units):
                save_message_unit(
                    message_id=message_id,
                    conversation_id=conversation_id,
                    unit_index=index,
                    unit_type=kind,
                    unit_content=content,
                    user_id=user_id,
                )
        except Exception:
            logger.exception("Failed to persist Workbench creation transcript")
