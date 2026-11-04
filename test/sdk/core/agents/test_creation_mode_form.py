# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Creation confirmation is literal model data, not an executable creation tool."""

import pytest
from pydantic import ValidationError

from nexent.core.agents.clarification import ClarificationForm
from nexent.core.agents.output_protocol import extract_clarification_form


def question(**overrides):
    return {"id": "workbench_creation_mode", "type": "single_choice", "title": "进入创建模式？",
            "required": True, "allow_other": False, "creation_request": "整理长文并保留出处。",
            "options": [{"id": "agent_create", "label": "智能体创建"},
                        {"id": "continue_chat", "label": "继续普通对话"}], **overrides}


def test_model_creation_confirmation_retains_request_without_executing_code():
    form = extract_clarification_form(f"ask_user(questions=[{question()!r}])", "ask_user")
    assert form.questions[0].creation_request == "整理长文并保留出处。"
    assert [item.id for item in form.questions[0].options] == ["agent_create", "continue_chat"]


@pytest.mark.parametrize("change", [
    {"creation_request": ""}, {"creation_request": "x" * 8001}, {"type": "text"},
    {"allow_other": True}, {"required": False},
    {"options": [{"id": "delete_agent", "label": "Delete"}, {"id": "continue_chat", "label": "Chat"}]},
])
def test_invalid_creation_forms_are_rejected(change):
    with pytest.raises(ValidationError):
        ClarificationForm.model_validate({"questions": [question(**change)]})


def test_generic_clarifications_remain_compatible():
    form = ClarificationForm.model_validate({"questions": [{"id": "topic", "type": "text", "title": "Topic?"}]})
    assert "creation_request" not in form.model_dump(exclude_none=True)["questions"][0]
