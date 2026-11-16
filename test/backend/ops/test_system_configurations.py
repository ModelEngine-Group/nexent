# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""HTTP and authorization contracts for ops system configuration."""

import pytest
from configuration.catalog import DEFAULT_CATALOG, ConfigurationValidationError
from fastapi.testclient import TestClient
from gateway.authentication.auth import authenticate
from ops.api.application import create_app
from permissions.models import CurrentUser

from test.backend.configuration.test_catalog import EXPECTED_DEFAULTS


def _snapshot(**changes):
    return DEFAULT_CATALOG.build_snapshot({**EXPECTED_DEFAULTS, **changes})


def _items():
    return [
        {
            "key": item.key,
            "value": item.default,
            "default_value": item.default,
            "kind": item.kind,
            "group": item.group,
            "label_key": item.label_key,
            "description_key": item.description_key,
            "unit_key": item.unit_key,
            "effect_key": item.effect_key,
            "recommendation_available": False,
        }
        for item in DEFAULT_CATALOG.definitions
    ]


OPS_USER = CurrentUser("ops-user", "ops-tenant", "OPS", roles=("OPS",))


def _client(user=OPS_USER):
    app = create_app()
    if user is not None:
        app.dependency_overrides[authenticate] = lambda: user
    return TestClient(app)


def test_anonymous_request_is_rejected_before_configuration_lookup(mocker):
    lookup = mocker.patch(
        "ops.api.system_configurations.list_system_configurations",
        create=True,
    )

    response = _client(None).get("/system_configurations")

    assert response.status_code == 401
    lookup.assert_not_called()


def test_explicit_operations_permission_returns_exact_catalog(mocker):
    mocker.patch(
        "ops.api.system_configurations.authorize_operations",
        return_value="ops-user",
        create=True,
    )
    mocker.patch(
        "ops.api.system_configurations.list_system_configurations",
        return_value=_items(),
        create=True,
    )

    response = _client().get(
        "/system_configurations", headers={"Authorization": "Bearer token"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 19
    assert len(payload["items"]) == 19
    assert {item["key"] for item in payload["items"]} == set(EXPECTED_DEFAULTS)
    assert all(item["recommendation_available"] is False for item in payload["items"])


def test_database_failure_is_a_safe_503(mocker):
    mocker.patch(
        "ops.api.system_configurations.authorize_operations",
        return_value="ops-user",
        create=True,
    )
    mocker.patch(
        "ops.api.system_configurations.list_system_configurations",
        side_effect=RuntimeError("postgres://user:secret@example.invalid"),
        create=True,
    )

    response = _client().get(
        "/system_configurations", headers={"Authorization": "Bearer token"}
    )

    assert response.status_code == 503
    assert "secret" not in response.text
    assert "example.invalid" not in response.text


def test_patch_only_returns_saved_values_and_notification_degradation(mocker):
    authorize = mocker.patch(
        "ops.api.system_configurations.authorize_operations",
        return_value="ops-user",
        create=True,
    )
    save = mocker.patch(
        "ops.api.system_configurations.save_system_configurations",
        return_value={
            "items": [_items()[0]],
            "notification": "degraded",
        },
        create=True,
    )

    response = _client().patch(
        "/system_configurations",
        headers={"Authorization": "Bearer token"},
        json={"changes": {"MAX_TENANT_COUNT": 5}},
    )

    assert response.status_code == 200
    assert response.json()["saved"] is True
    assert response.json()["notification"] == "degraded"
    assert "revision" not in response.text
    assert "consumer" not in response.text
    save.assert_called_once_with({"MAX_TENANT_COUNT": 5}, actor="ops-user")
    authorize.assert_called_once_with(OPS_USER, "ops.configuration:update")


@pytest.mark.parametrize(
    "role,expected_status",
    [("OPS", 200), ("SU", 200), ("ADMIN", 403), ("USER", 403)],
)
def test_standard_operations_scope_controls_catalog_access(mocker, role, expected_status):
    user = CurrentUser("actor", "tenant", role, roles=(role,))
    mocker.patch(
        "permissions.operations.has_permission",
        side_effect=lambda roles, _permission: bool(set(roles) & {"OPS", "SU"}),
    )
    query = mocker.patch(
        "ops.api.system_configurations.list_system_configurations",
        return_value=_items(),
    )

    response = _client(user).get("/system_configurations")

    assert response.status_code == expected_status
    if expected_status == 200:
        query.assert_called_once_with()
    else:
        query.assert_not_called()


def test_invalid_business_batch_maps_to_400(mocker):
    mocker.patch(
        "ops.api.system_configurations.authorize_operations",
        return_value="ops-user",
        create=True,
    )
    mocker.patch(
        "ops.api.system_configurations.save_system_configurations",
        side_effect=ConfigurationValidationError("MAX_TENANT_COUNT must be positive"),
        create=True,
    )

    response = _client().patch(
        "/system_configurations",
        headers={"Authorization": "Bearer token"},
        json={"changes": {"MAX_TENANT_COUNT": 0}},
    )

    assert response.status_code == 400
    assert "MAX_TENANT_COUNT" in response.text


def test_malformed_request_maps_to_422(mocker):
    mocker.patch(
        "ops.api.system_configurations.authorize_operations",
        return_value="ops-user",
        create=True,
    )

    response = _client().patch(
        "/system_configurations",
        headers={"Authorization": "Bearer token"},
        json={"changes": {}},
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "key", [key for key in EXPECTED_DEFAULTS if key != "LLM_INCLUDE_LOGPROBS"]
)
def test_current_numeric_parameters_have_no_recommendation(mocker, key):
    mocker.patch(
        "ops.api.system_configurations.authorize_operations",
        return_value="ops-user",
        create=True,
    )

    response = _client().post(
        "/system_configurations/recommendations",
        headers={"Authorization": "Bearer token"},
        json={"key": key},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "RECOMMENDATION_UNAVAILABLE"
    assert "value" not in response.json()["detail"]


def test_authorizer_requires_explicit_route_permission(mocker):
    from fastapi import HTTPException
    from ops.services.authorization import (
        authorize_operations,
    )

    user = CurrentUser("user", "tenant", "USER", roles=("USER",))
    scope = mocker.patch(
        "ops.services.authorization.operations_scope",
        side_effect=HTTPException(status_code=403, detail="Operations permission required"),
    )

    with pytest.raises(HTTPException):
        authorize_operations(user)
    scope.assert_called_once_with(user, None, "ops.configuration:read")


def test_authorizer_returns_user_for_operations_role(mocker):
    from ops.services.authorization import authorize_operations

    scope = mocker.patch(
        "ops.services.authorization.operations_scope",
        return_value=None,
    )

    assert authorize_operations(OPS_USER, "ops.configuration:update") == "ops-user"
    scope.assert_called_once_with(OPS_USER, None, "ops.configuration:update")
