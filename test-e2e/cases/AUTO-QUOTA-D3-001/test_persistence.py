# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Real automation message persistence, quota and activity API in PostgreSQL."""

import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra" / "automation"))
from shared.postgres import apply_product_postgres_env

apply_product_postgres_env()

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from management.api.conversation import conversation_management as routes
from contracts.errors.exceptions import AppException
from contracts.conversation import MessageRequest, MessageUnit
from contracts.conversation import MessageSource, encode_activity_cursor
from management.db.conversation import repository as db
from management.db.conversation import pins as pins
from management.db.client import db_client
from management.db.models import ConversationMessage, ConversationMessageUnit, ConversationRecord, ConversationSourceImage, ConversationSourceSearch
from management.services.automation.conversation import AutomationConversationAdapter
from management.services.conversation.service import save_message


@pytest.fixture(params=["UTC", "Asia/Shanghai", "America/New_York"])
def persistence(monkeypatch, request):
    schema = "auto_activity_" + uuid4().hex
    engine = db_client.engine.execution_options(schema_translate_map={"nexent": schema})
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
        for model in (ConversationRecord, ConversationMessage, ConversationMessageUnit,
                      ConversationSourceSearch, ConversationSourceImage):
            model.__table__.create(connection)
    try:
        @contextmanager
        def sessions():
            with Session(engine) as session, session.begin():
                session.execute(text("SELECT set_config('TimeZone', :zone, true)"), {"zone": request.param})
                yield session

        monkeypatch.setattr(db, "get_db_session", sessions)
        monkeypatch.setattr(pins, "get_db_session", sessions)
        monkeypatch.setattr(db, "MAX_CONVERSATION_TURNS", 100)
        monkeypatch.setattr(routes, "get_current_user_id", lambda token: ("owner", "tenant"))
        now = datetime.now(timezone.utc)
        with sessions() as session:
            for identity, owner in [(1, "owner"), (2, "owner"), (3, "other")]:
                created = now - timedelta(days=40 - identity)
                session.add(ConversationRecord(
                    conversation_id=identity, conversation_title=f"History {identity}",
                    workbench_config={}, created_by=owner, updated_by=owner, delete_flag="N",
                    create_time=created.replace(tzinfo=None), update_time=now.replace(tzinfo=None),
                    last_activity_time=None if identity == 2 else created.replace(tzinfo=None),
                ))
        app = FastAPI()
        app.include_router(routes.router, prefix="/api")
        yield engine, sessions, TestClient(app), now
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))


@pytest.mark.case_id("AUTO-QUOTA-D3-001")
@pytest.mark.stage("D3")
def test_mixed_source_quota_activity_and_cursor(persistence):
    engine, sessions, client, now = persistence

    def chat(index, **extra):
        return save_message(MessageRequest(
            conversation_id=1, message_idx=index * 2, role="user",
            message=[MessageUnit(type="string", content="ordinary")],
            **extra,
        ), "owner", "tenant")

    for index in range(99):
        chat(index)
    def concurrent_chat(index):
        try:
            return chat(index)
        except AppException as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(concurrent_chat, [99, 100]))
    assert sum(isinstance(value, int) for value in outcomes) == 1
    assert sum(isinstance(value, AppException) for value in outcomes) == 1
    adapter = AutomationConversationAdapter()
    for _ in range(3):
        adapter.append_run_prompt(1, "automated execution", "owner", "tenant")
    with pytest.raises(AppException, match="maximum 100 turns"):
        chat(104, message_source="AUTOMATION")
    with sessions() as session:
        grouped = dict(session.execute(select(
            ConversationMessage.message_source, func.count(),
        ).group_by(ConversationMessage.message_source)).all())
        assert grouped == {"CHAT": 100, "AUTOMATION": 3}
        current = session.get(ConversationRecord, 1).last_activity_time
        assert current.tzinfo is None
        assert now.replace(tzinfo=None) < current <= datetime.now(timezone.utc).replace(tzinfo=None)
    placeholder = db.create_conversation_message(
        {"conversation_id": 1, "message_idx": 207, "role": "assistant", "content": ""},
        "owner", status="streaming", message_source=MessageSource.AUTOMATION,
    )
    assert db.get_conversation(1, "owner")["last_activity_time"] == current.isoformat() + "Z"
    db.persist_assistant_run_batch(
        placeholder, 1, "completed answer", "completed", [], [], [], [], [], "owner", "tenant",
    )
    with sessions() as session:
        answered = session.get(ConversationRecord, 1).last_activity_time
        assert answered > current
        session.execute(update(ConversationRecord).where(ConversationRecord.conversation_id == 2).values(
            conversation_title="administrative rename", update_time=func.now(),
        ))
    assert db.get_conversation(1, "owner")["last_activity_time"] == answered.isoformat() + "Z"
    params = {"today_start_ms": int((now - timedelta(hours=1)).timestamp() * 1000),
              "week_start_ms": int((now - timedelta(days=7)).timestamp() * 1000),
              "conversation_type": "workbench", "limit": 1}
    first = client.get("/api/conversation/list", params=params)
    assert first.status_code == 200, first.text
    page = first.json()["data"]
    assert [row["conversation_id"] for row in page["items"]] == [1]
    assert page["metadata"] == {"total": 2, "today": 1, "last_7_days": 0, "older": 1}
    assert page["next_cursor"]
    second = client.get("/api/conversation/list", params={**params, "cursor": page["next_cursor"]})
    assert second.status_code == 200, second.text
    tail = second.json()["data"]
    assert [row["conversation_id"] for row in tail["items"]] == [2]
    assert tail["metadata"] == page["metadata"] and tail["next_cursor"] is None
    exhausted = client.get("/api/conversation/list", params={
        **params, "cursor": encode_activity_cursor(now - timedelta(days=100), 1),
    }).json()["data"]
    assert exhausted["items"] == [] and exhausted["metadata"] == page["metadata"]
    assert client.get("/api/conversation/list", params={**params, "cursor": "invalid"}).status_code == 400

    @contextmanager
    def rolled_back():
        with Session(engine) as session:
            try:
                yield session
                raise RuntimeError("rollback fixture")
            finally:
                session.rollback()

    from unittest.mock import patch
    with patch.object(db, "get_db_session", rolled_back), pytest.raises(RuntimeError, match="rollback fixture"):
        db.create_conversation_message(
            {"conversation_id": 1, "message_idx": 210, "role": "user", "content": "rolled back"},
            "owner", message_source=MessageSource.AUTOMATION,
        )
    with sessions() as session:
        assert session.get(ConversationRecord, 1).last_activity_time == answered
        assert session.scalar(select(func.count()).select_from(ConversationMessage)) == 104


    # An explicit activity and a NULL fallback share the same UTC tie boundary.
    with sessions() as session:
        fallback = session.get(ConversationRecord, 2).create_time
        session.add(ConversationRecord(
            conversation_id=4, conversation_title="Tied history", workbench_config={},
            created_by="owner", updated_by="owner", delete_flag="N",
            create_time=fallback, update_time=fallback, last_activity_time=fallback,
        ))
        session.get(ConversationRecord, 1).workbench_pinned_at = now.replace(tzinfo=None)
        session.get(ConversationRecord, 2).workbench_pinned_at = now.replace(tzinfo=None) - timedelta(seconds=1)
    pinned = {row["conversation_id"]: row for row in pins.list_workbench_pins("owner", "tenant")}
    assert pinned[1]["last_activity_time"] == int(answered.replace(tzinfo=timezone.utc).timestamp() * 1000)
    assert pinned[2]["last_activity_time"] == int(fallback.replace(tzinfo=timezone.utc).timestamp() * 1000)
    identities = []
    cursor = None
    for _ in range(3):
        page_params = {**params, **({"cursor": cursor} if cursor else {})}
        response = client.get("/api/conversation/list", params=page_params)
        assert response.status_code == 200, response.text
        page = response.json()["data"]
        assert page["metadata"] == {"total": 3, "today": 1, "last_7_days": 0, "older": 2}
        identities.extend(row["conversation_id"] for row in page["items"])
        cursor = page["next_cursor"]
    assert identities == [1, 4, 2] and cursor is None
    assert [row["conversation_id"] for row in db.get_conversation_list("owner")] == identities
    legacy_cursor = encode_activity_cursor(fallback.replace(tzinfo=timezone.utc), 4)
    tail = client.get("/api/conversation/list", params={**params, "cursor": legacy_cursor}).json()["data"]
    assert [row["conversation_id"] for row in tail["items"]] == [2]
    assert tail["items"][0]["last_activity_time"] == pinned[2]["last_activity_time"]
