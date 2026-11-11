# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""HTTP and authorization contracts for ops system configuration."""

from unittest.mock import Mock

import jwt
import pytest
from configuration.catalog import DEFAULT_CATALOG, ConfigurationValidationError
from fastapi.testclient import TestClient
from ops.api.application import create_app

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


def _client():
    return TestClient(create_app())


def test_anonymous_request_is_rejected_before_configuration_lookup(mocker):
    lookup = mocker.patch(
        "ops.api.system_configurations.list_system_configurations",
        create=True,
    )

    response = _client().get("/system_configurations")

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
    authorize.assert_called_once_with("Bearer token")


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
    from ops.services.authorization import (
        OperationsForbiddenError,
        authorize_operations,
    )

    mocker.patch("ops.services.authorization._decode_user_id", return_value="su-user")
    mocker.patch(
        "ops.services.authorization.configuration_database.session",
        return_value=_authorization_session("SU", None),
    )

    with pytest.raises(OperationsForbiddenError):
        authorize_operations("Bearer su-token")


def test_authorizer_returns_user_for_operations_role(mocker):
    from ops.services.authorization import authorize_operations

    decode = mocker.patch(
        "ops.services.authorization._decode_user_id", return_value="ops-user"
    )
    mocker.patch(
        "ops.services.authorization.configuration_database.session",
        return_value=_authorization_session("OPS_ADMIN", "/system-config"),
    )

    assert authorize_operations("Bearer ops-token") == "ops-user"
    decode.assert_called_once_with("Bearer ops-token")


def test_invalid_jwt_is_unauthorized(mocker):
    from ops.services.authorization import (
        OperationsUnauthorizedError,
        authorize_operations,
    )

    mocker.patch(
        "ops.services.authorization.jwt.decode",
        side_effect=jwt.InvalidTokenError("bad token"),
    )

    with pytest.raises(OperationsUnauthorizedError):
        authorize_operations("Bearer invalid")


def _scalar(value):
    result = Mock()
    result.scalar.return_value = value
    return result


def _session_context(session):
    context = Mock()
    context.__enter__ = Mock(return_value=session)
    context.__exit__ = Mock(return_value=False)
    return context


def _authorization_session(role, permission):
    session = Mock()

    def execute(statement, _params):
        sql = str(statement)
        if "FROM nexent.user_tenant_t" in sql:
            raise RuntimeError('column "user_role" does not exist')
        if "FROM nexent.user_account_t" in sql:
            return _scalar(role)
        if "FROM nexent.role_permission_t" in sql:
            return _scalar(permission)
        raise AssertionError("Unexpected authorization query")

    session.execute.side_effect = execute
    return _session_context(session)
