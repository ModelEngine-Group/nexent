# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Actual HTTP/service/PostgreSQL pin contract in a disposable schema."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from apps import workbench_pins_app as routes
from database import workbench_pin_db
from database.client import db_client
from database.db_models import ConversationRecord, ConversationWorkbenchPin


@pytest.fixture
def persistence(monkeypatch):
    schema = "wb_pin_test_" + uuid4().hex
    engine = db_client.engine.execution_options(schema_translate_map={"nexent": schema})
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
        ConversationRecord.__table__.create(connection)
        ConversationWorkbenchPin.__table__.create(connection)
    try:
        with Session(engine) as session, session.begin():
            for id, owner, config, deleted in [
                (1, "owner", {}, "N"), (2, "owner", {}, "N"),
                (3, "owner", None, "N"), (4, "other", {}, "N"),
                (5, "owner", {}, "Y"),
            ]:
                session.add(ConversationRecord(
                    conversation_id=id, conversation_title=f"History {id}",
                    created_by=owner, updated_by=owner, workbench_config=config,
                    create_time=datetime(2026, 1, 1), update_time=datetime(2026, 1, 2), delete_flag=deleted,
                ))

        @contextmanager
        def sessions():
            with Session(engine) as session, session.begin():
                yield session

        monkeypatch.setattr(workbench_pin_db, "get_db_session", sessions)
        identities = {"Bearer owner": ("owner", "tenant"), "Bearer other": ("other", "tenant"), "Bearer other-tenant": ("owner", "elsewhere")}
        monkeypatch.setattr(routes, "get_current_user_id", lambda token: identities.get(token, (None, None)))
        app = FastAPI()
        app.include_router(routes.router, prefix="/api")
        yield engine, app
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))


@pytest.mark.case_id("CHAT-SIDEBAR-D3-001")
@pytest.mark.stage("D3")
def test_authenticated_postgres_pin_persistence(persistence):
    engine, app = persistence
    first = TestClient(app, headers={"Authorization": "Bearer owner"})
    second = TestClient(app, headers={"Authorization": "Bearer owner"})

    def save(client, id, pinned=True):
        response = client.put(f"/api/conversation/{id}/workbench_pin", json={"pinned": pinned})
        assert response.status_code == 200, response.text
        return response.json()["data"]["items"]

    def read(client):
        response = client.get("/api/conversation/workbench_pins")
        assert response.status_code == 200, response.text
        return response.json()["data"]["items"]

    def ids(items):
        return [item["conversation_id"] for item in items]

    original = save(first, 1)
    assert save(second, 1) == original
    state = save(first, 2)
    assert ids(state) == [2, 1]
    assert state[0]["pinned_at"] > state[1]["pinned_at"]
    assert read(second) == state
    assert ids(save(second, 1, False)) == [2]
    state = save(first, 1)
    assert ids(state) == [1, 2]
    assert state[0]["pinned_at"] > original[0]["pinned_at"]

    save(first, 1, False)
    save(first, 2, False)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda id: save(TestClient(app, headers={"Authorization": "Bearer owner"}), id), [1, 2, 1, 2]))
    assert all(results)
    state = read(second)
    assert set(ids(state)) == {1, 2}
    assert len(state) == 2
    assert state[0]["pinned_at"] > state[1]["pinned_at"]
    with Session(engine) as session:
        pins = session.scalars(select(ConversationWorkbenchPin)).all()
        assert len(pins) == 2
        assert all(pin.delete_flag == "N" and pin.created_by == "owner" and pin.updated_by == "owner" for pin in pins)
        conversations = session.scalars(select(ConversationRecord)).all()
        assert all(c.conversation_title == f"History {c.conversation_id}" for c in conversations)
        assert all(c.create_time == datetime(2026, 1, 1) and c.update_time == datetime(2026, 1, 2) for c in conversations)

    for token in ["Bearer other", "Bearer other-tenant"]:
        client = TestClient(app, headers={"Authorization": token})
        assert read(client) == []
    for id in [3, 4, 5, 999]:
        assert first.put(f"/api/conversation/{id}/workbench_pin", json={"pinned": True}).status_code == 404
    assert TestClient(app).get("/api/conversation/workbench_pins").status_code == 401
    assert first.put("/api/conversation/1/workbench_pin", json={"pinned": "true"}).status_code == 422
    assert first.put("/api/conversation/0/workbench_pin", json={"pinned": True}).status_code == 422
    assert read(first) == state
    with Session(engine) as session, session.begin():
        conversation = session.get(ConversationRecord, state[0]["conversation_id"])
        conversation.delete_flag = "Y"
    assert ids(read(second)) == [state[1]["conversation_id"]]
