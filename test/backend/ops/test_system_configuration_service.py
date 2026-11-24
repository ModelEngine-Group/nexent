# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Service-level persistence and notification boundaries for system configuration."""

from unittest.mock import Mock

from infrastructure.system_configuration.catalog import DEFAULT_CATALOG

from test.backend.configuration.helpers import system_config_snapshot


def _session_context(session):
    context = Mock()
    context.__enter__ = Mock(return_value=session)
    context.__exit__ = Mock(return_value=False)
    return context


def test_list_returns_shared_catalog_and_saved_database_values(mocker):
    from ops.services import system_configuration

    session = Mock()
    mocker.patch.object(
        system_configuration.configuration_database,
        "session",
        return_value=_session_context(session),
    )
    mocker.patch.object(
        system_configuration.repository,
        "load_snapshot",
        return_value=system_config_snapshot(MAX_TENANT_COUNT=5),
    )

    items = system_configuration.list_system_configurations()

    assert len(items) == len(DEFAULT_CATALOG.definitions) == 20
    assert items[0]["value"] == 5
    assert items[0]["default_value"] == 100
    assert all(item["recommendation_available"] is False for item in items)


def test_save_returns_degraded_after_commit_when_notification_fails(mocker):
    from ops.services import system_configuration

    session = Mock()
    mocker.patch.object(
        system_configuration.configuration_database,
        "session",
        return_value=_session_context(session),
    )
    save = mocker.patch.object(
        system_configuration.repository,
        "save_changes",
        return_value=system_config_snapshot(MAX_TENANT_COUNT=5),
    )
    mocker.patch.object(
        system_configuration,
        "publish_configuration_change",
        side_effect=ConnectionError("redis unavailable"),
    )

    result = system_configuration.save_system_configurations(
        {"MAX_TENANT_COUNT": 5, "MAX_USERS_PER_TENANT": 10000},
        actor="ops-user",
    )

    assert result["notification"] == "degraded"
    assert [item["key"] for item in result["items"]] == [
        "MAX_TENANT_COUNT",
        "MAX_USERS_PER_TENANT",
    ]
    save.assert_called_once_with(
        session,
        {"MAX_TENANT_COUNT": 5, "MAX_USERS_PER_TENANT": 10000},
        actor="ops-user",
    )
