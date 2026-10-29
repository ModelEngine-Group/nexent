# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Preference HTTP failures retain ownership, conflict and validation semantics."""

import pytest
from contracts.errors.exceptions import ForbiddenError, RunModelControlsError
from test.backend.app.test_conversation_model_preferences_app import model_preference_client  # noqa: F401


@pytest.mark.parametrize("kind,status,code", [
    ("missing", 404, "CONVERSATION_NOT_FOUND"), ("conflict", 409, "MODEL_PREFERENCE_VERSION_CONFLICT"),
    ("forbidden", 403, "MODEL_SELECTION_FORBIDDEN"), ("model_not_available", 404, "model_not_available"),
    ("model_unavailable", 409, "model_unavailable"), ("model_type_invalid", 400, "model_type_invalid"),
    ("model_controls_invalid", 422, "model_controls_invalid"),
])
def test_selection_error_routes_do_not_retry_writes(model_preference_client, kind, status, code):
    client, service, module = model_preference_client
    errors = {"missing": module.ConversationNotFoundError("missing"),
              "conflict": module.ModelOutletConflictError(), "forbidden": ForbiddenError("denied")}
    service.patch_model_selection.side_effect = errors.get(kind) or RunModelControlsError(kind)
    result = client.patch("/conversation/11/model_preferences", json={"expected_version": 2, "selected_model_id": 42})
    assert result.status_code == status
    detail = result.json()["detail"]
    assert (detail if isinstance(detail, str) else detail["code"]) == code
    service.patch_model_selection.assert_called_once()


@pytest.mark.parametrize("view", [False, True])
def test_missing_preference_read_preserves_not_found_status(model_preference_client, view):
    client, service, module = model_preference_client
    operation = service.read_model_preference_view if view else service.read_model_preferences
    operation.side_effect = module.ConversationNotFoundError("missing")
    result = client.get("/conversation/11/model_preferences" + ("/42" if view else ""))
    assert result.status_code == 404 and result.json()["detail"] == "CONVERSATION_NOT_FOUND"
    operation.assert_called_once()


def test_invalid_saved_view_reports_safe_field_and_category(model_preference_client):
    client, service, module = model_preference_client
    service.read_model_preference_view.side_effect = module.ModelOutletValidationError("PARAMETER_UNKNOWN", "/retired")
    result = client.get("/conversation/11/model_preferences/42")
    assert result.status_code == 422 and result.json()["detail"] == {"code": "PARAMETER_UNKNOWN", "field": "/retired"}
