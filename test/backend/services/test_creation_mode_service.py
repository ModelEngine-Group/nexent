# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Creation confirmation validates intent and owned scope before persistence."""

from unittest.mock import Mock

import pytest

from contracts.clarification import ClarificationResponse
from contracts.errors.exceptions import ConversationNotFoundError, ValidationError
from management.services.conversation import creation_mode as service


def response(mode="agent_create"):
    return ClarificationResponse.model_validate({
        "form": {"schema_version": 1, "questions": [{
            "id": "workbench_creation_mode", "type": "single_choice", "title": "Choose creation",
            "creation_request": "An assistant that summarizes articles with citations.",
            "options": [{"id": "agent_create", "label": "Create Agent"},
                        {"id": "skill_create", "label": "Create Skill"},
                        {"id": "continue_chat", "label": "Continue chatting"}],
        }]},
        "answers": [{"questionId": "workbench_creation_mode", "value": mode}],
    })


@pytest.fixture
def persistence(monkeypatch):
    lookup = Mock(return_value={"conversation_id": 42})
    save = Mock(return_value={"message_id": 20, "clarification_response": {"source_message_id": 10}})
    monkeypatch.setattr(service, "get_conversation", lookup)
    monkeypatch.setattr(service, "save_creation_response", save)
    return lookup, save


@pytest.mark.parametrize("mode,label", [("agent_create", "Create Agent"), ("skill_create", "Create Skill")])
def test_allowed_confirmation_passes_owned_scope_and_readable_choice(persistence, mode, label):
    lookup, save = persistence
    request = response(mode)

    result = service.confirm_creation_mode(42, request, "owner", "tenant")

    lookup.assert_called_once_with(42, user_id="owner", tenant_id="tenant")
    save.assert_called_once_with(42, request, f"Choose creation\n{label}", "owner")
    assert result == {**save.return_value, "mode": mode}
    assert "mode" not in save.return_value


@pytest.mark.parametrize("variant", ["ordinary_question", "multiple_questions", "continue_chat"])
def test_valid_but_non_creation_answers_are_rejected_before_any_storage(persistence, variant):
    lookup, save = persistence
    if variant == "continue_chat":
        request = response("continue_chat")
    else:
        questions = [{"id": "goal", "type": "text", "title": "Goal?"}]
        if variant == "multiple_questions":
            questions.append({"id": "format", "type": "text", "title": "Format?"})
        request = ClarificationResponse.model_validate({
            "form": {"schema_version": 1, "questions": questions},
            "answers": [{"questionId": question["id"], "value": "A valid ordinary answer"}
                        for question in questions],
        })

    with pytest.raises(ValidationError, match="Expected a creation-mode confirmation"):
        service.confirm_creation_mode(42, request, "owner", "tenant")

    lookup.assert_not_called()
    save.assert_not_called()


def test_missing_owned_conversation_never_saves(persistence):
    lookup, save = persistence
    lookup.return_value = None

    with pytest.raises(ConversationNotFoundError, match="Workbench conversation not found"):
        service.confirm_creation_mode(42, response(), "other-owner", "other-tenant")

    lookup.assert_called_once_with(42, user_id="other-owner", tenant_id="other-tenant")
    save.assert_not_called()


@pytest.mark.parametrize("failing_boundary", ["lookup", "save"])
def test_storage_failures_propagate_without_retry_or_false_receipt(persistence, failing_boundary):
    lookup, save = persistence
    error = RuntimeError("Controlled storage failure")
    (lookup if failing_boundary == "lookup" else save).side_effect = error

    with pytest.raises(RuntimeError) as caught:
        service.confirm_creation_mode(42, response(), "owner", "tenant")

    assert caught.value is error
    lookup.assert_called_once()
    if failing_boundary == "lookup":
        save.assert_not_called()
    else:
        save.assert_called_once()
