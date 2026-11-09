# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Validation boundary for authenticated personal question bookmarks."""

from contracts.errors.exceptions import UnauthorizedError, ValidationError
from management.db.conversation.bookmarks import question_bookmarks


def _validate(conversation_id: int, user_id: str, tenant_id: str) -> None:
    if not user_id or not tenant_id:
        raise UnauthorizedError("Please login first")
    if len(user_id) > 100 or len(tenant_id) > 100:
        raise ValidationError("Invalid bookmark identity")
    if type(conversation_id) is not int or not 0 < conversation_id <= 2147483647:
        raise ValidationError("Invalid conversation id")


def list_question_bookmarks(conversation_id: int, user_id: str, tenant_id: str) -> dict:
    _validate(conversation_id, user_id, tenant_id)
    return {"message_ids": question_bookmarks(conversation_id, user_id)}


def set_question_bookmark(conversation_id: int, message_id: int, bookmarked: bool, user_id: str, tenant_id: str) -> dict:
    _validate(conversation_id, user_id, tenant_id)
    if type(message_id) is not int or not 0 < message_id <= 2147483647 or type(bookmarked) is not bool:
        raise ValidationError("Invalid question bookmark")
    return {"message_ids": question_bookmarks(conversation_id, user_id, message_id, bookmarked)}
