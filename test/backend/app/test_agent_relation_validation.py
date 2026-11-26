# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Classify relationship business rejections without masking internal failures."""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from management.api.agent.agent import agent_config_router
from contracts.errors.exceptions import AgentNotFoundError, AgentRelationValidationError


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(agent_config_router)
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize("error, status, message", [
    (AgentRelationValidationError("Agent cannot be related to itself"), 400, "Agent cannot be related to itself"),
    (AgentNotFoundError("private target"), 404, "Agent not found."),
    (RuntimeError("database unavailable"), 500, "Agent update error."),
    (ValueError("internal configuration failure"), 500, "Agent update error."),
])
def test_update_maps_only_business_errors_to_4xx(mocker, client, error, status, message):
    mocker.patch("management.api.agent.agent.get_current_user_id", return_value=("user", "tenant"))
    update = mocker.patch("management.api.agent.agent.update_agent_info_impl", new_callable=AsyncMock, side_effect=error)
    response = client.post("/agent/update", json={"agent_id": 1, "related_agent_ids": [1, 999]})
    assert response.status_code == status
    assert response.json() == {"detail": message}
    update.assert_awaited_once()
