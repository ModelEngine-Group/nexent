# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Error mapping contracts for the Agent history HTTP boundary."""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from test_conversation_management_app import conversation_mocks, router
from consts.exceptions import TokenExpiredError


@pytest.mark.parametrize("path,service", [
    ("agent_groups", "list_agent_groups"),
    ("agent_groups/agent:7/conversations", "list_agent_group_conversations"),
    ("agent_groups/7/conversation_ids", "list_agent_group_conversation_ids"),
])
@pytest.mark.parametrize("error,status,detail", [
    (ValueError("bad cursor"), 400, "bad cursor"),
    (TokenExpiredError("expired"), 401, "expired"),
    (HTTPException(status_code=403, detail="denied"), 403, "denied"),
    (RuntimeError("private database error"), 500, "Failed to list Agent"),
])
def test_history_service_errors_are_mapped_without_leaking_internals(
    conversation_mocks, path, service, error, status, detail,
):
    conversation_mocks["get_current_user_id"].return_value = ("owner", "tenant")
    conversation_mocks[service].side_effect = error
    app = FastAPI()
    app.include_router(router, prefix="/api")
    response = TestClient(app).get("/api/conversation/" + path)
    assert response.status_code == status
    assert detail in response.json()["detail"]
    assert "private database error" not in response.text


def test_excessive_included_groups_are_rejected_before_service(conversation_mocks):
    conversation_mocks["get_current_user_id"].return_value = ("owner", "tenant")
    app = FastAPI()
    app.include_router(router, prefix="/api")
    query = "&".join("include_agent_id=" + str(n) for n in range(1, 102))
    response = TestClient(app).get("/api/conversation/agent_groups?" + query)
    assert response.status_code == 400
    conversation_mocks["list_agent_groups"].assert_not_called()
