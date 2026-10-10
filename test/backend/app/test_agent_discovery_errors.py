"""Regression coverage for Agent discovery error classification."""

from unittest.mock import AsyncMock

import pytest

from test.backend.app import test_agent_app as legacy
from consts.exceptions import AgentNotFoundError


@pytest.mark.parametrize("lookup", ["detail", "name"])
@pytest.mark.parametrize(
    "error, status",
    [
        (AgentNotFoundError("private agent in tenant-a"), 404),
        (RuntimeError("database unavailable"), 500),
        (ValueError("invalid internal configuration"), 500),
    ],
)
def test_discovery_classifies_errors_without_disclosure(mocker, lookup, error, status):
    mocker.patch(
        "apps.agent_app.get_current_user_id", return_value=("user-b", "tenant-b")
    )
    if lookup == "detail":
        service = mocker.patch(
            "apps.agent_app.get_agent_info_impl",
            new_callable=AsyncMock,
            side_effect=error,
        )
        response = legacy.config_client.post(
            "/agent/search_info", json={"agent_id": 42, "version_no": 0}
        )
        service.assert_awaited_once_with(42, "tenant-b", 0, "user-b")
    else:
        service = mocker.patch("apps.agent_app.get_agent_by_name_impl", side_effect=error)
        response = legacy.config_client.get("/agent/by-name/missing")
        service.assert_called_once_with("missing", "tenant-b")

    assert response.status_code == status
    expected_message = (
        "Agent not found." if status == 404 else
        "Agent search info error." if lookup == "detail" else
        "Agent by name lookup error."
    )
    assert response.json() == {"detail": expected_message}
    assert str(error) not in response.text
