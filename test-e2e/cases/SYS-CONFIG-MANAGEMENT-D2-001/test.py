# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""D2 proof for the actual ops configuration HTTP application."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from management.services.permission.identity.session import authenticate
from management.configuration.catalog import (
    DEFAULT_CATALOG,
    ConfigurationValidationError,
)
from ops.api.application import create_app
from permissions.models import CurrentUser


def _items():
    return [
        {
            "key": definition.key,
            "value": definition.default,
            "default_value": definition.default,
            "kind": definition.kind,
            "group": definition.group,
            "label_key": definition.label_key,
            "description_key": definition.description_key,
            "unit_key": definition.unit_key,
            "effect_key": definition.effect_key,
            "recommendation_available": False,
        }
        for definition in DEFAULT_CATALOG.definitions
    ]


def _request(method, path, role=None, **kwargs):
    app = create_app()
    if role is not None:
        user = CurrentUser(f"{role.lower()}-user", "tenant", role, roles=(role,))
        app.dependency_overrides[authenticate] = lambda: user
    with TestClient(app) as client:
        return client.request(method, path, **kwargs)


@pytest.mark.case_id("SYS-CONFIG-MANAGEMENT-D2-001")
@pytest.mark.stage("D2")
@pytest.mark.api_it
def test_catalog_and_authorization_contract():
    assert _request("GET", "/system_configurations").status_code == 401

    for role in ("OPS", "SU"):
        with (
            patch("permissions.operations.has_permission", return_value=True),
            patch(
                "ops.api.system_configurations.list_system_configurations",
                return_value=_items(),
            ) as list_configurations,
        ):
            response = _request("GET", "/system_configurations", role)
        assert response.status_code == 200
        assert response.json()["total"] == 19
        assert {item["key"] for item in response.json()["items"]} == set(
            DEFAULT_CATALOG.defaults
        )
        list_configurations.assert_called_once_with()

    for role in ("ADMIN", "USER"):
        with (
            patch("permissions.operations.has_permission", return_value=False),
            patch("ops.api.system_configurations.list_system_configurations") as query,
        ):
            denied = _request("GET", "/system_configurations", role)
        assert denied.status_code == 403
        query.assert_not_called()

    with (
        patch(
            "ops.api.system_configurations.authorize_operations",
            return_value="ops-user",
        ),
        patch(
            "ops.api.system_configurations.list_system_configurations",
            side_effect=RuntimeError("postgres://user:secret@example.invalid"),
        ),
    ):
        failure = _request("GET",
            "/system_configurations",
            "OPS",
            headers={"Authorization": "Bearer authorized"},
        )
    assert failure.status_code == 503
    assert "secret" not in failure.text


@pytest.mark.case_id("SYS-CONFIG-MANAGEMENT-D2-001")
@pytest.mark.stage("D2")
@pytest.mark.api_it
def test_atomic_save_and_notification_degradation_contract():
    with (
        patch(
            "ops.api.system_configurations.authorize_configuration_write",
            return_value="su-user",
        ),
        patch(
            "ops.api.system_configurations.save_system_configurations",
            return_value={"items": [_items()[0]], "notification": "degraded"},
        ) as save,
    ):
        response = _request(
            "PATCH",
            "/system_configurations",
            "SU",
            headers={"Authorization": "Bearer authorized"},
            json={"changes": {"MAX_TENANT_COUNT": 5}},
        )
    assert response.status_code == 200
    assert response.json() == {
        "saved": True,
        "items": [_items()[0]],
        "notification": "degraded",
    }
    save.assert_called_once_with({"MAX_TENANT_COUNT": 5}, actor="su-user")

    for changes in (
        {"UNKNOWN_SETTING": 1},
        {"MAX_TENANT_COUNT": "5"},
        {"MAX_TENANT_COUNT": 0},
    ):
        with (
            patch(
                "ops.api.system_configurations.authorize_configuration_write",
                return_value="su-user",
            ),
            patch(
                "ops.api.system_configurations.save_system_configurations",
                side_effect=ConfigurationValidationError("invalid batch"),
            ) as save,
        ):
            invalid = _request(
                "PATCH",
                "/system_configurations",
                "SU",
                headers={"Authorization": "Bearer authorized"},
                json={"changes": changes},
            )
        assert invalid.status_code == 400
        save.assert_called_once_with(changes, actor="su-user")

    with patch(
        "ops.api.system_configurations.authorize_configuration_write",
        return_value="su-user",
    ):
        malformed = _request(
            "PATCH",
            "/system_configurations",
            "SU",
            headers={"Authorization": "Bearer authorized"},
            json={"changes": {}},
        )
    assert malformed.status_code == 422


@pytest.mark.case_id("SYS-CONFIG-MANAGEMENT-D2-001")
@pytest.mark.stage("D2")
@pytest.mark.api_it
def test_explicit_ops_and_su_can_save_platform_configuration():
    for role in ("OPS", "SU"):
        with (
            patch("permissions.operations.has_permission", return_value=True),
            patch(
                "ops.api.system_configurations.save_system_configurations",
                return_value={
                    "items": [_items()[0]],
                    "notification": "published",
                },
            ) as save,
        ):
            response = _request(
                "PATCH",
                "/system_configurations",
                role,
                json={"changes": {"MAX_TENANT_COUNT": 5}},
            )
        assert response.status_code == 200
        save.assert_called_once_with(
            {"MAX_TENANT_COUNT": 5}, actor=f"{role.lower()}-user"
        )


@pytest.mark.case_id("SYS-CONFIG-MANAGEMENT-D2-001")
@pytest.mark.stage("D2")
@pytest.mark.api_it
def test_current_recommendations_are_explicitly_unavailable():
    with patch(
        "ops.api.system_configurations.authorize_operations", return_value="ops-user"
    ):
        for key, default in DEFAULT_CATALOG.defaults.items():
            if isinstance(default, bool):
                continue
            response = _request(
                "POST",
                "/system_configurations/recommendations",
                "OPS",
                headers={"Authorization": "Bearer authorized"},
                json={"key": key},
            )
            assert response.status_code == 400
            detail = response.json()["detail"]
            assert detail["code"] == "RECOMMENDATION_UNAVAILABLE"
            assert "value" not in detail

        unknown = _request(
            "POST",
            "/system_configurations/recommendations",
            "OPS",
            headers={"Authorization": "Bearer authorized"},
            json={"key": "UNKNOWN_SETTING"},
        )
        assert unknown.status_code == 400
        assert unknown.json()["detail"]["code"] == "INVALID_CONFIGURATION_KEY"
