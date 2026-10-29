# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Conversation parameter HTTP contracts and authenticated resource scoping."""

import sys
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from test.backend.app import test_conversation_management_app as legacy_tests


@pytest.fixture
def model_preference_client(monkeypatch):
    from unittest.mock import Mock
    app_module = sys.modules[legacy_tests.create_new_conversation_endpoint.__module__]
    from nexent.core import concurrency

    service = types.ModuleType("management.services.conversation.model_preferences")
    service.read_model_preferences = Mock(return_value={"version": 2, "model_parameter_preferences": {}})
    service.read_model_preference_view = Mock(return_value={"version": 2, "parameter_values": {"temperature": 0}})
    service.patch_model_selection = Mock(return_value={"version": 3, "selected_model_id": 42})
    service.patch_model_preferences = Mock(return_value={"version": 3, "model_parameter_preferences": {"42": {"temperature": 0}}})
    monkeypatch.setitem(sys.modules, service.__name__, service)

    async def invoke(_name, operation, *args, **kwargs):
        return operation(*args, **kwargs)

    monkeypatch.setattr(concurrency, "run_blocking", invoke)
    monkeypatch.setattr(app_module, "get_current_user_id", Mock(return_value=("owner", "tenant")))
    app = FastAPI()
    app.include_router(app_module.router)
    return TestClient(app), service, app_module


def test_model_preference_routes_forward_owned_conversation_and_explicit_zero(model_preference_client):
    client, service, _ = model_preference_client
    assert client.get("/conversation/11/model_preferences").json()["data"]["version"] == 2
    service.read_model_preferences.assert_called_once_with(11, "owner")
    assert client.get("/conversation/11/model_preferences/42").json()["data"]["parameter_values"] == {"temperature": 0}
    service.read_model_preference_view.assert_called_once_with(11, 42, "owner", "tenant")
    response = client.patch("/conversation/11/model_preferences/42", json={
        "expected_version": 2, "parameter_values": {"temperature": 0}, "delete_parameters": [],
    })
    assert response.status_code == 200 and response.json()["data"]["version"] == 3
    args = service.patch_model_preferences.call_args.args
    assert args[:2] == (11, 42) and args[3:] == ("owner", "tenant")
    assert args[2].parameter_values == {"temperature": 0}


@pytest.mark.parametrize("kind,status,code", [("missing", 404, "CONVERSATION_NOT_FOUND"),
    ("conflict", 409, "MODEL_PREFERENCE_VERSION_CONFLICT"), ("invalid", 422, "PARAMETER_UNKNOWN")])
def test_model_preference_failure_status_and_no_second_write(model_preference_client, kind, status, code):
    client, service, module = model_preference_client
    errors = {"missing": module.ConversationNotFoundError("missing"),
              "conflict": module.ModelOutletConflictError(),
              "invalid": module.ModelOutletValidationError("PARAMETER_UNKNOWN", "/retired")}
    service.patch_model_preferences.side_effect = errors[kind]
    response = client.patch("/conversation/11/model_preferences/42", json={"expected_version": 2})
    assert response.status_code == status
    detail = response.json()["detail"]
    assert (detail if isinstance(detail, str) else detail["code"]) == code
    service.patch_model_preferences.assert_called_once()


@pytest.mark.parametrize("version", [-1, True, "2", 2147483647])
def test_model_preference_rejects_invalid_version_before_service(model_preference_client, version):
    client, service, _ = model_preference_client
    response = client.patch("/conversation/11/model_preferences/42", json={"expected_version": version})
    assert response.status_code == 422
    service.patch_model_preferences.assert_not_called()


def test_su_ac_01_selection_endpoint_uses_shared_owner_tenant_and_cas(model_preference_client):
    client, service, _ = model_preference_client
    response = client.patch("/conversation/11/model_preferences", json={"expected_version": 2, "selected_model_id": 42})
    assert response.status_code == 200 and response.json()["data"]["selected_model_id"] == 42
    args = service.patch_model_selection.call_args.args
    assert args[0] == 11 and args[2:] == ("owner", "tenant")
    assert args[1].expected_version == 2 and args[1].selected_model_id == 42


@pytest.mark.parametrize("model_id", [0, -1, True, "42", 1.5, None])
def test_su_ac_05_invalid_selection_does_not_reach_service(model_preference_client, model_id):
    client, service, _ = model_preference_client
    response = client.patch("/conversation/11/model_preferences", json={"expected_version": 2, "selected_model_id": model_id})
    assert response.status_code == 422
    service.patch_model_selection.assert_not_called()
