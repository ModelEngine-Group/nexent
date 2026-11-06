# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Unit proof of creation-confirmation identity and HTTP error translation."""

import logging
import sys
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from contracts.clarification import ClarificationResponse
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import (
    AppException,
    ConversationNotFoundError,
    TokenExpiredError,
    UnauthorizedError,
    ValidationError,
)
from test.backend.app import test_conversation_management_app as legacy


api = sys.modules[legacy.create_new_conversation_endpoint.__module__]


@pytest.fixture
def boundary(monkeypatch):
    identity = Mock(return_value=("owner", "tenant"))
    save = Mock()
    monkeypatch.setattr(api, "get_current_user_id", identity)
    monkeypatch.setattr(api, "confirm_creation_mode", save)
    return identity, save


def creation_response(mode="agent_create"):
    return ClarificationResponse.model_validate({
        "schema_version": 1,
        "form": {"schema_version": 1, "questions": [{
            "id": "workbench_creation_mode", "type": "single_choice", "title": "Enter creation?",
            "creation_request": "Summarize documents with citations.",
            "options": [{"id": mode, "label": "Create"}, {"id": "continue_chat", "label": "Continue"}],
        }]},
        "answers": [{"questionId": "workbench_creation_mode", "value": mode}],
    })


@pytest.mark.parametrize("mode", ["agent_create", "skill_create"])
def test_creation_receipt_preserves_response_and_authenticated_identity(boundary, mode):
    identity, save = boundary
    request = creation_response(mode)
    receipt = {"message_id": 20, "mode": mode, "clarification_response": request.model_dump()}
    save.return_value = receipt

    result = api.confirm_creation_mode_endpoint(42, request, "Bearer controlled-token")

    assert result.code == 0 and result.message == "success" and result.data == receipt
    identity.assert_called_once_with("Bearer controlled-token")
    save.assert_called_once_with(42, request, "owner", "tenant")


@pytest.mark.parametrize("error_type", [TokenExpiredError, UnauthorizedError])
def test_failed_authentication_never_reaches_confirmation_persistence(boundary, error_type):
    identity, save = boundary
    error = error_type("Controlled identity failure")
    identity.side_effect = error

    with pytest.raises(HTTPException) as caught:
        api.confirm_creation_mode_endpoint(42, creation_response(), "invalid-token")

    assert caught.value.status_code == 401
    assert caught.value.detail == "Please login first"
    assert caught.value.__cause__ is error
    save.assert_not_called()


@pytest.mark.parametrize("error,status,detail", [
    (ConversationNotFoundError("Inaccessible owner"), 404, "Workbench conversation not found"),
    (ValidationError("Invalid action"), 422, "Creation confirmation is invalid or no longer available"),
    (AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Stale form"), 422,
     "Creation confirmation is invalid or no longer available"),
])
def test_domain_rejections_preserve_public_error_contract(boundary, error, status, detail):
    _, save = boundary
    save.side_effect = error

    with pytest.raises(HTTPException) as caught:
        api.confirm_creation_mode_endpoint(42, creation_response(), "controlled-token")

    assert caught.value.status_code == status and caught.value.detail == detail
    assert caught.value.__cause__ is error
    save.assert_called_once()


def test_unexpected_failure_is_logged_without_exposing_internal_detail(boundary, caplog):
    _, save = boundary
    error = RuntimeError("Controlled internal persistence diagnostic")
    save.side_effect = error

    with caplog.at_level(logging.ERROR), pytest.raises(HTTPException) as caught:
        api.confirm_creation_mode_endpoint(42, creation_response(), "controlled-token")

    assert caught.value.status_code == 500
    assert caught.value.detail == "Failed to record creation confirmation"
    assert str(error) not in caught.value.detail
    assert caught.value.__cause__ is error
    assert any(record.getMessage() == "Failed to record creation confirmation"
               and record.exc_info[1] is error for record in caplog.records)
