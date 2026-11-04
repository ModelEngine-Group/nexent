# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""HTTP contract; domain and database behavior have separate traditional UT."""

from copy import deepcopy
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from contracts.errors.exceptions import AppException, ConversationNotFoundError, TokenExpiredError
from contracts.errors.codes import ErrorCode
from management.api.conversation import conversation_management as api

pytestmark = [pytest.mark.case_id("WB-CREATION-CONFIRM-D2-001"), pytest.mark.stage("D2")]

BODY = {"schema_version": 1, "unit_index": 7, "form": {"schema_version": 1, "questions": [{
    "id": "workbench_creation_mode", "type": "single_choice", "title": "Enter creation?",
    "creation_request": "Summarize documents with citations.",
    "options": [{"id": "agent_create", "label": "Agent"}, {"id": "continue_chat", "label": "Continue"}],
}]}, "answers": [{"questionId": "workbench_creation_mode", "value": "agent_create", "otherText": None}]}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(api, "get_current_user_id", lambda authorization: ("owner", "tenant"))
    app = FastAPI()
    app.include_router(api.router)
    with TestClient(app) as client:
        yield client


def test_creation_confirmation_http_receipt(client, monkeypatch):
    save = Mock(return_value={"message_id": 20, "mode": "agent_create"})
    monkeypatch.setattr(api, "confirm_creation_mode", save)
    result = client.post("/conversation/42/creation_mode_responses", json=BODY)
    assert result.status_code == 200
    assert result.json()["data"] == {"message_id": 20, "mode": "agent_create"}
    assert save.call_args.args[0] == 42
    assert save.call_args.args[2:] == ("owner", "tenant")
    assert save.call_args.args[1].answers[0].value == "agent_create"


@pytest.mark.parametrize("variant", ["action", "context", "question", "id"])
def test_creation_confirmation_rejects_malformed_requests(client, monkeypatch, variant):
    save = Mock()
    monkeypatch.setattr(api, "confirm_creation_mode", save)
    body = deepcopy(BODY)
    conversation_id = 42
    if variant == "action": body["answers"][0]["value"] = "delete_agent"
    if variant == "context": body["form"]["questions"][0]["creation_request"] = ""
    if variant == "question": body["form"]["questions"][0]["id"] = "forged"
    if variant == "id": conversation_id = 0
    assert client.post(f"/conversation/{conversation_id}/creation_mode_responses", json=body).status_code == 422
    save.assert_not_called()


@pytest.mark.parametrize("error,status", [
    (ConversationNotFoundError("private"), 404),
    (AppException(ErrorCode.COMMON_VALIDATION_ERROR, "stale"), 422),
])
def test_creation_confirmation_maps_domain_rejection(client, monkeypatch, error, status):
    monkeypatch.setattr(api, "confirm_creation_mode", Mock(side_effect=error))
    assert client.post("/conversation/42/creation_mode_responses", json=BODY).status_code == status


def test_creation_confirmation_expired_identity(client, monkeypatch):
    monkeypatch.setattr(api, "get_current_user_id", Mock(side_effect=TokenExpiredError("expired")))
    save = Mock()
    monkeypatch.setattr(api, "confirm_creation_mode", save)
    assert client.post("/conversation/42/creation_mode_responses", json=BODY).status_code == 401
    save.assert_not_called()
