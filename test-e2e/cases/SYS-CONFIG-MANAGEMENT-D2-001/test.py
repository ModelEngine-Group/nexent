# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""D2 proof for the actual ops configuration HTTP application."""

from unittest.mock import Mock, patch

import pytest
from configuration.catalog import DEFAULT_CATALOG, ConfigurationValidationError
from fastapi.testclient import TestClient
from ops.api.application import create_app


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


def _scalar(value):
    result = Mock()
    result.scalar.return_value = value
    return result


def _authorization_session(role):
    session = Mock()
    session.execute.side_effect = [
        _scalar(role),
        _scalar("/system-config" if role == "OPS_ADMIN" else None),
    ]
    context = Mock()
    context.__enter__ = Mock(return_value=session)
    context.__exit__ = Mock(return_value=False)
    return context


@pytest.mark.case_id("SYS-CONFIG-MANAGEMENT-D2-001")
@pytest.mark.stage("D2")
@pytest.mark.api_it
def test_catalog_and_authorization_contract():
    client = TestClient(create_app())
    assert client.get("/system_configurations").status_code == 401

    with (
        patch(
            "ops.services.authorization._decode_user_id",
            side_effect=lambda authorization: authorization.split()[-1],
        ),
        patch(
            "ops.services.authorization.configuration_database.session",
            side_effect=lambda: _authorization_session("OPS_ADMIN"),
        ),
        patch(
            "ops.api.system_configurations.list_system_configurations",
            return_value=_items(),
        ) as list_configurations,
    ):
        response = client.get(
            "/system_configurations", headers={"Authorization": "Bearer authorized"}
        )
    assert response.status_code == 200
    assert response.json()["total"] == 19
    assert {item["key"] for item in response.json()["items"]} == set(
        DEFAULT_CATALOG.defaults
    )
    list_configurations.assert_called_once_with()

    for role in ("SU", "ADMIN", "USER"):
        with (
            patch(
                "ops.services.authorization._decode_user_id",
                return_value=f"{role.lower()}-user",
            ),
            patch(
                "ops.services.authorization.configuration_database.session",
                side_effect=lambda role=role: _authorization_session(role),
            ),
            patch("ops.api.system_configurations.list_system_configurations") as query,
        ):
            denied = client.get(
                "/system_configurations",
                headers={"Authorization": f"Bearer {role.lower()}-token"},
            )
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
        failure = client.get(
            "/system_configurations", headers={"Authorization": "Bearer authorized"}
        )
    assert failure.status_code == 503
    assert "secret" not in failure.text


@pytest.mark.case_id("SYS-CONFIG-MANAGEMENT-D2-001")
@pytest.mark.stage("D2")
@pytest.mark.api_it
def test_atomic_save_and_notification_degradation_contract():
    client = TestClient(create_app())
    with (
        patch(
            "ops.api.system_configurations.authorize_operations",
            return_value="ops-user",
        ),
        patch(
            "ops.api.system_configurations.save_system_configurations",
            return_value={"items": [_items()[0]], "notification": "degraded"},
        ) as save,
    ):
        response = client.patch(
            "/system_configurations",
            headers={"Authorization": "Bearer authorized"},
            json={"changes": {"MAX_TENANT_COUNT": 5}},
        )
    assert response.status_code == 200
    assert response.json() == {
        "saved": True,
        "items": [_items()[0]],
        "notification": "degraded",
    }
    save.assert_called_once_with({"MAX_TENANT_COUNT": 5}, actor="ops-user")

    for changes in (
        {"UNKNOWN_SETTING": 1},
        {"MAX_TENANT_COUNT": "5"},
        {"MAX_TENANT_COUNT": 0},
    ):
        with (
            patch(
                "ops.api.system_configurations.authorize_operations",
                return_value="ops-user",
            ),
            patch(
                "ops.api.system_configurations.save_system_configurations",
                side_effect=ConfigurationValidationError("invalid batch"),
            ) as save,
        ):
            invalid = client.patch(
                "/system_configurations",
                headers={"Authorization": "Bearer authorized"},
                json={"changes": changes},
            )
        assert invalid.status_code == 400
        save.assert_called_once_with(changes, actor="ops-user")

    with patch(
        "ops.api.system_configurations.authorize_operations", return_value="ops-user"
    ):
        malformed = client.patch(
            "/system_configurations",
            headers={"Authorization": "Bearer authorized"},
            json={"changes": {}},
        )
    assert malformed.status_code == 422


@pytest.mark.case_id("SYS-CONFIG-MANAGEMENT-D2-001")
@pytest.mark.stage("D2")
@pytest.mark.api_it
def test_current_recommendations_are_explicitly_unavailable():
    client = TestClient(create_app())
    with patch(
        "ops.api.system_configurations.authorize_operations", return_value="ops-user"
    ):
        for key, default in DEFAULT_CATALOG.defaults.items():
            if isinstance(default, bool):
                continue
            response = client.post(
                "/system_configurations/recommendations",
                headers={"Authorization": "Bearer authorized"},
                json={"key": key},
            )
            assert response.status_code == 400
            detail = response.json()["detail"]
            assert detail["code"] == "RECOMMENDATION_UNAVAILABLE"
            assert "value" not in detail

        unknown = client.post(
            "/system_configurations/recommendations",
            headers={"Authorization": "Bearer authorized"},
            json={"key": "UNKNOWN_SETTING"},
        )
        assert unknown.status_code == 400
        assert unknown.json()["detail"]["code"] == "INVALID_CONFIGURATION_KEY"
