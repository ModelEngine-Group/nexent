# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Bookmark validation, owner-scoped SQL and HTTP contracts with isolated I/O."""

import importlib.util
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from contracts.errors.exceptions import ConversationNotFoundError, UnauthorizedError, ValidationError


@pytest.fixture
def boundary(monkeypatch):
    session = MagicMock()

    @contextmanager
    def get_session():
        yield session

    client_module = types.ModuleType("management.db.client")
    client_module.get_db_session = get_session
    auth_module = types.ModuleType("gateway.authentication.auth")
    auth_module.get_current_user_id = MagicMock(return_value=("user", "tenant"))
    monkeypatch.setitem(sys.modules, "management.db.client", client_module)
    monkeypatch.setitem(sys.modules, "gateway.authentication.auth", auth_module)
    root = Path(__file__).resolve().parents[3] / "backend"

    def load(name, relative):
        spec = importlib.util.spec_from_file_location(name, root / relative)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        return module

    db = load("management.db.conversation.bookmarks", "management/db/conversation/bookmarks.py")
    service = load("management.services.conversation.bookmarks", "management/services/conversation/bookmarks.py")
    routes = load("management.api.conversation.question_bookmarks", "management/api/conversation/question_bookmarks.py")
    app = FastAPI()
    app.include_router(routes.router)
    return types.SimpleNamespace(db=db, service=service, routes=routes, session=session,
                                 auth=auth_module.get_current_user_id, client=TestClient(app))


def sql(statement):
    return str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


@pytest.mark.parametrize("marked", [True, False])
def test_write_and_restore_are_owner_scoped_without_activity_updates(boundary, marked):
    b = boundary
    b.session.scalar.side_effect = [42, 17, 42]
    b.session.scalars.return_value = [17] if marked else []
    expected = {"message_ids": [17] if marked else []}
    response = b.client.put("/conversation/42/question_bookmarks/17", json={"bookmarked": marked})
    assert response.status_code == 200
    assert response.json()["data"] == expected
    ownership, write = [sql(call.args[0]) for call in b.session.scalar.call_args_list]
    assert "created_by = 'user'" in ownership and "delete_flag = 'N'" in ownership
    assert "FOR UPDATE" in ownership
    assert "conversation_id = 42" in write and "message_id = 17" in write
    assert "message_role = 'user'" in write and "delete_flag = 'N'" in write
    assert "update_time=nexent.conversation_message_t.update_time" in write
    assert "message_content=" not in write
    assert b.client.get("/conversation/42/question_bookmarks").json()["data"] == expected


@pytest.mark.parametrize("scalars", [[None], [42, None]])
def test_foreign_conversation_or_invalid_question_cannot_be_updated(boundary, scalars):
    boundary.session.scalar.side_effect = scalars
    response = boundary.client.put("/conversation/42/question_bookmarks/17", json={"bookmarked": True})
    assert response.status_code == 404
    boundary.session.scalars.assert_not_called()


@pytest.mark.parametrize("path,body", [
    ("0/17", {"bookmarked": True}), ("42/0", {"bookmarked": True}),
    ("42/2147483648", {"bookmarked": True}), ("42/17", {}),
    ("42/17", {"bookmarked": 1}), ("42/17", {"bookmarked": "true"}),
    ("42/17", {"bookmarked": None}),
])
def test_invalid_http_input_has_no_database_side_effect(boundary, path, body):
    conversation, message = path.split("/")
    assert boundary.client.put(
        f"/conversation/{conversation}/question_bookmarks/{message}", json=body
    ).status_code == 422
    boundary.session.scalar.assert_not_called()


@pytest.mark.parametrize("conversation,message,marked", [(True, 17, True), (42, -1, True), (42, 17, 1)])
def test_service_rejects_invalid_internal_callers(boundary, conversation, message, marked):
    with pytest.raises(ValidationError):
        boundary.service.set_question_bookmark(conversation, message, marked, "user", "tenant")
    boundary.session.scalar.assert_not_called()


def test_unauthenticated_requests_do_not_access_storage(boundary):
    boundary.auth.side_effect = UnauthorizedError("expired")
    assert boundary.client.get("/conversation/42/question_bookmarks").status_code == 401
    boundary.session.scalar.assert_not_called()


def test_storage_failure_is_sanitized(boundary):
    boundary.session.scalar.side_effect = RuntimeError("secret connection string")
    response = boundary.client.get("/conversation/42/question_bookmarks")
    assert response.status_code == 500
    assert "secret" not in response.text


def test_list_is_read_only_and_identity_required(boundary):
    boundary.session.scalar.return_value = 42
    boundary.session.scalars.return_value = []
    assert boundary.service.list_question_bookmarks(42, "user", "tenant") == {"message_ids": []}
    assert "FOR UPDATE" not in sql(boundary.session.scalar.call_args.args[0])
    with pytest.raises(UnauthorizedError):
        boundary.service.list_question_bookmarks(42, "", "tenant")
