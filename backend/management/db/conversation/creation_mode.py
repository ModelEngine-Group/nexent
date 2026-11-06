# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Atomically record an owned creation confirmation using existing message units."""

import json

from sqlalchemy import desc, select

from contracts.clarification import ClarificationResponse
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException, ConversationNotFoundError
from management.db.client import get_db_session
from management.db.models import ConversationMessage, ConversationMessageUnit, ConversationRecord
from management.db.conversation.repository import create_conversation_message


def save_creation_response(conversation_id: int, response: ClarificationResponse, readable: str, user_id: str) -> dict:
    with get_db_session() as session:
        owned = session.execute(select(ConversationRecord.conversation_id, ConversationRecord.workbench_config).where(
            ConversationRecord.conversation_id == conversation_id,
            ConversationRecord.created_by == user_id, ConversationRecord.delete_flag == "N",
        ).with_for_update()).first()
        if owned is None or not isinstance(owned.workbench_config, dict):
            raise ConversationNotFoundError("Workbench conversation not found")
        if owned.workbench_config.get("mode") not in {"generic_chat", "single_agent_chat", "multi_agent_chat"}:
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Creation confirmation requires an ordinary Workbench")
        latest = session.execute(select(
            ConversationMessage.message_id, ConversationMessage.message_index, ConversationMessage.message_role,
        ).where(ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.delete_flag == "N").order_by(
            desc(ConversationMessage.message_index), desc(ConversationMessage.message_id),
        ).limit(1)).first()
        if latest is None:
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Clarification is no longer available")
        raw = response.model_dump()
        if latest.message_role == "user":
            content = session.scalar(select(ConversationMessageUnit.unit_content).where(
                ConversationMessageUnit.message_id == latest.message_id,
                ConversationMessageUnit.conversation_id == conversation_id,
                ConversationMessageUnit.unit_type == "clarification_response",
                ConversationMessageUnit.delete_flag == "N",
            ))
            saved = json.loads(content) if content else None
            if (isinstance(saved, dict) and saved.get("form") == raw["form"]
                    and saved.get("answers") == raw["answers"]
                    and (raw["unit_index"] is None or raw["unit_index"] == saved.get("unit_index"))):
                return {"message_id": latest.message_id, "clarification_response": saved}
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Clarification is no longer available")
        message_id = create_conversation_message({
            "conversation_id": conversation_id, "message_idx": latest.message_index + 1,
            "role": "user", "content": readable, "clarification_response": raw,
        }, user_id, db_session=session)
        saved = session.scalar(select(ConversationMessageUnit.unit_content).where(
            ConversationMessageUnit.message_id == message_id,
            ConversationMessageUnit.unit_type == "clarification_response",
        ))
        return {"message_id": message_id, "clarification_response": json.loads(saved)}
