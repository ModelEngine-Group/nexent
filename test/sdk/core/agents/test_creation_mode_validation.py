# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Creation context cannot escape its explicit single-question confirmation."""

import pytest
from pydantic import ValidationError

from nexent.core.agents.contracts.clarification import ClarificationForm


def question(options=None):
    return {
        "id": "workbench_creation_mode", "type": "single_choice", "title": "Enter creation?",
        "creation_request": "An assistant that summarizes articles with citations.",
        "options": options if options is not None else [
            {"id": "agent_create", "label": "Create Agent"},
            {"id": "continue_chat", "label": "Continue chatting"},
        ],
    }


def test_ordinary_question_cannot_smuggle_a_creation_request():
    with pytest.raises(ValidationError, match="Creation context requires a Workbench creation confirmation"):
        ClarificationForm.model_validate({"questions": [{
            "id": "goal", "type": "text", "title": "Goal?", "creation_request": "Unapproved context",
        }]})


def test_creation_confirmation_cannot_be_mixed_with_other_questions():
    with pytest.raises(ValidationError, match="Ask the creation-mode confirmation separately"):
        ClarificationForm.model_validate({"questions": [
            question(), {"id": "goal", "type": "text", "title": "Goal?"},
        ]})


@pytest.mark.parametrize("options", [
    [{"id": "agent_create", "label": "Agent"}, {"id": "skill_create", "label": "Skill"}],
    [{"id": "continue_chat", "label": "Continue chatting"}],
])
def test_confirmation_requires_both_a_creation_choice_and_a_way_to_continue(options):
    with pytest.raises(ValidationError, match="Invalid Workbench creation confirmation"):
        ClarificationForm.model_validate({"questions": [question(options)]})


def test_creation_request_accepts_its_exact_length_boundary():
    value = question()
    value["creation_request"] = "x" * 8000
    assert ClarificationForm.model_validate({"questions": [value]}).questions[0].creation_request == "x" * 8000
