"""Classify relationship business rejections without masking internal failures."""

from unittest.mock import AsyncMock

import pytest

from test.backend.app import test_agent_app as legacy
from consts.exceptions import AgentNotFoundError, AgentRelationValidationError


@pytest.mark.parametrize("error, status, message", [
    (AgentRelationValidationError("Agent cannot be related to itself"), 400, "Agent cannot be related to itself"),
    (AgentNotFoundError("private target"), 404, "Agent not found."),
    (RuntimeError("database unavailable"), 500, "Agent update error."),
    (ValueError("internal configuration failure"), 500, "Agent update error."),
])
def test_update_maps_only_business_errors_to_4xx(mocker, error, status, message):
    mocker.patch("apps.agent_app.get_current_user_id", return_value=("user", "tenant"))
    update = mocker.patch("apps.agent_app.update_agent_info_impl", new_callable=AsyncMock, side_effect=error)
    response = legacy.config_client.post("/agent/update", json={"agent_id": 1, "related_agent_ids": [1, 999]})
    assert response.status_code == status
    assert response.json() == {"detail": message}
    update.assert_awaited_once()
