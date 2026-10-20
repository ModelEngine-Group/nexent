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

from apps import conversation_management_app as routes
from consts.exceptions import AppException
from consts.model import MessageRequest, MessageUnit
from contracts.conversation import MessageSource, encode_activity_cursor
from database import conversation_db as db
from database.client import db_client
from database.db_models import (
    ConversationMessage, ConversationMessageUnit, ConversationRecord,
    ConversationSourceImage, ConversationSourceSearch,
)
from management.services.automation.conversation import AutomationConversationAdapter
from management.services.conversation.service import save_message


@pytest.fixture
def persistence(monkeypatch):
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
                yield session

        monkeypatch.setattr(db, "get_db_session", sessions)
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
                    last_activity_time=created,
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
        assert current > now
    placeholder = db.create_conversation_message(
        {"conversation_id": 1, "message_idx": 207, "role": "assistant", "content": ""},
        "owner", status="streaming", message_source=MessageSource.AUTOMATION,
    )
    assert db.get_conversation(1, "owner")["last_activity_time"] == current.isoformat()
    db.persist_assistant_run_batch(
        placeholder, 1, "completed answer", "completed", [], [], [], [], [], "owner", "tenant",
    )
    with sessions() as session:
        answered = session.get(ConversationRecord, 1).last_activity_time
        assert answered > current
        session.execute(update(ConversationRecord).where(ConversationRecord.conversation_id == 2).values(
            conversation_title="administrative rename", update_time=func.now(),
        ))
    assert db.get_conversation(1, "owner")["last_activity_time"] == answered.isoformat()
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
