# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Regression coverage for Agent discovery error classification."""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from management.api.agent.agent import agent_config_router
from contracts.errors.exceptions import AgentNotFoundError


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(agent_config_router)
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize("lookup", ["detail", "name"])
@pytest.mark.parametrize(
    "error, status",
    [
        (AgentNotFoundError("private agent in tenant-a"), 404),
        (RuntimeError("database unavailable"), 500),
        (ValueError("invalid internal configuration"), 500),
    ],
)
def test_discovery_classifies_errors_without_disclosure(mocker, client, lookup, error, status):
    mocker.patch(
        "management.api.agent.agent.get_current_user_id", return_value=("user-b", "tenant-b")
    )
    if lookup == "detail":
        service = mocker.patch(
            "management.api.agent.agent.get_agent_info_impl",
            new_callable=AsyncMock,
            side_effect=error,
        )
        response = client.post(
            "/agent/search_info", json={"agent_id": 42, "version_no": 0}
        )
        service.assert_awaited_once_with(42, "tenant-b", 0, "user-b")
    else:
        service = mocker.patch("management.api.agent.agent.get_agent_by_name_impl", side_effect=error)
        response = client.get("/agent/by-name/missing")
        service.assert_called_once_with("missing", "tenant-b")

    assert response.status_code == status
    expected_message = (
        "Agent not found." if status == 404 else
        "Agent search info error." if lookup == "detail" else
        "Agent by name lookup error."
    )
    assert response.json() == {"detail": expected_message}
    assert str(error) not in response.text
