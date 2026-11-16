# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Public creator history query validation and identity forwarding."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from management.api.conversation import conversation_management as routes
from management.services.conversation import creator_histories as service


@pytest.fixture
def client(mocker):
    mocker.patch.object(routes, "get_current_user_id", return_value=("user-a", "tenant-a"))
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app)


def test_creator_history_endpoint_uses_authenticated_owner_and_target(client, mocker):
    page = {"items": [], "total": 0}
    query = mocker.patch.object(service, "list_creator_histories", return_value=page)
    response = client.get("/conversation/creator_histories?kind=agent&target_id=201&offset=20")
    assert response.status_code == 200 and response.json()["data"] == page
    query.assert_called_once_with(kind="agent", target_id=201, offset=20, limit=20, user_id="user-a", tenant_id="tenant-a")


@pytest.mark.parametrize("query", ["kind=file&target_id=1", "kind=agent&target_id=0", "kind=agent&target_id=2147483648", "kind=agent&target_id=1&offset=-1", "kind=skill&target_id=1&limit=101"])
def test_invalid_query_fails_before_service(client, mocker, query):
    call = mocker.patch.object(service, "list_creator_histories")
    assert client.get("/conversation/creator_histories?" + query).status_code == 422
    call.assert_not_called()


def test_foreign_target_is_forbidden(client, mocker):
    mocker.patch.object(service, "list_creator_histories", side_effect=PermissionError("unavailable"))
    assert client.get("/conversation/creator_histories?kind=agent&target_id=201").status_code == 403
