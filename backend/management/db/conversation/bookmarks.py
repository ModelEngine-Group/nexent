# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Owner-private question bookmarks without modifying conversation activity."""

from sqlalchemy import select, update

from contracts.errors.exceptions import ConversationNotFoundError
from management.db.client import get_db_session
from management.db.conversation.models import ConversationMessage, ConversationRecord


def _owned_conversation(conversation_id: int, user_id: str):
    return (
        ConversationRecord.conversation_id == conversation_id,
        ConversationRecord.created_by == user_id,
        ConversationRecord.delete_flag == "N",
    )


def _questions(conversation_id: int):
    return (
        ConversationMessage.conversation_id == conversation_id,
        ConversationMessage.message_role == "user",
        ConversationMessage.delete_flag == "N",
    )


def question_bookmarks(conversation_id: int, user_id: str, message_id=None, bookmarked=None) -> list[int]:
    """Read or atomically set an explicit desired state on an owned question."""
    with get_db_session() as session:
        statement = select(ConversationRecord.conversation_id).where(*_owned_conversation(conversation_id, user_id))
        # Serialize writes within this conversation; list calls remain read-only.
        if message_id is not None:
            statement = statement.with_for_update()
        if session.scalar(statement) is None:
            raise ConversationNotFoundError("Conversation not found")
        if message_id is not None:
            saved = session.scalar(
                update(ConversationMessage)
                .where(*_questions(conversation_id), ConversationMessage.message_id == message_id)
                .values(question_bookmarked=bookmarked, update_time=ConversationMessage.update_time)
                .returning(ConversationMessage.message_id)
            )
            if saved is None:
                raise ConversationNotFoundError("Question not found")
        return list(session.scalars(
            select(ConversationMessage.message_id)
            .where(*_questions(conversation_id), ConversationMessage.question_bookmarked.is_(True))
            .order_by(ConversationMessage.message_id)
        ))
