# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Persist a creation-mode choice without invoking an Agent or changing its mode."""

from contracts.clarification import ClarificationResponse
from contracts.errors.exceptions import ConversationNotFoundError, ValidationError
from management.db.conversation.creation_mode import save_creation_response
from management.db.conversation.repository import get_conversation


def confirm_creation_mode(conversation_id: int, response: ClarificationResponse, user_id: str, tenant_id: str) -> dict:
    questions = response.form["questions"]
    mode = response.answers[0].value
    if (len(questions) != 1 or questions[0]["id"] != "workbench_creation_mode"
            or mode not in ("agent_create", "skill_create")):
        raise ValidationError("Expected a creation-mode confirmation")
    if get_conversation(conversation_id, user_id=user_id, tenant_id=tenant_id) is None:
        raise ConversationNotFoundError("Workbench conversation not found")
    question = questions[0]
    label = next(option["label"] for option in question["options"] if option["id"] == mode)
    readable = f"{question['title']}\n{label}"
    return {**save_creation_response(conversation_id, response, readable, user_id), "mode": mode}
