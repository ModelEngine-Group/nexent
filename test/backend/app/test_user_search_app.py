# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Select name matching only from an already authenticated CAS session."""

from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from management.api.identity import user as user_app
from contracts.exceptions import UnauthorizedError


@pytest.mark.parametrize("sid,search,expected_flag", [
    ("cas-session", "Bob", True),
    (None, "Bob", False),
    ("cas-session", "   ", False),
])
def test_session_controls_search_and_payload_cannot_enable_it(monkeypatch, sid, search, expected_flag):
    monkeypatch.setattr(user_app, "get_current_user_context", lambda _: ("admin", "tenant", "ADMIN"))
    monkeypatch.setattr(user_app, "extract_session_id_from_authorization", lambda _: sid)
    service = Mock(return_value={"users": [], "total": 0})
    monkeypatch.setattr(user_app, "get_users_for_requester", service)
    app = FastAPI()
    app.include_router(user_app.router)
    with TestClient(app) as client:
        response = client.post("/users/list", json={
            "tenant_id": "tenant", "search": search, "roles": ["USER"], "group_ids": [7],
            "page": 2, "page_size": 5, "search_cas_username": True,
        })
    assert response.status_code == 200
    kwargs = service.call_args.kwargs
    assert kwargs.get("search_cas_username", False) is expected_flag
    assert kwargs["search"] == search
    assert kwargs["roles"] == ["USER"] and kwargs["group_ids"] == [7]
    assert kwargs["requester_tenant_id"] == "tenant" and kwargs["requester_role"] == "ADMIN"
    assert service.call_args.args == ("tenant", 2, 5, "created_at", "desc")


def test_authentication_failure_precedes_session_selection_and_query(monkeypatch):
    context = Mock(side_effect=UnauthorizedError("controlled invalid session"))
    session = Mock(return_value="cas-session")
    service = Mock()
    monkeypatch.setattr(user_app, "get_current_user_context", context)
    monkeypatch.setattr(user_app, "extract_session_id_from_authorization", session)
    monkeypatch.setattr(user_app, "get_users_for_requester", service)
    app = FastAPI()
    app.include_router(user_app.router)
    with TestClient(app) as client:
        assert client.post("/users/list", json={"tenant_id": "tenant", "search": "Bob"}).status_code == 401
    session.assert_not_called()
    service.assert_not_called()
