# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Real PostgreSQL title races and additive revision deployment integrity."""

import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import monotonic
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text, update
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra/automation"))
from shared.postgres import apply_product_postgres_env, postgres_url

apply_product_postgres_env()

from fastapi import FastAPI
from fastapi.testclient import TestClient

with patch(
    "nexent.storage.storage_client_factory.create_storage_client_from_config",
    return_value=MagicMock(),
), patch("nexent.storage.minio_config.MinIOStorageConfig.validate", lambda self: None):
    from apps import conversation_management_app as routes
    from database import conversation_db as db
    from database import user_tenant_db
    from database.db_models import (
        ConversationMessage, ConversationMessageUnit, ConversationRecord,
        ConversationSourceImage, ConversationSourceSearch, UserTenant,
    )
    from management.services.conversation import service

pytestmark = [pytest.mark.case_id("CHAT-TITLE-D5-001"), pytest.mark.stage("D5")]


class TitleProbe:
    def __init__(self, engine, schema, monkeypatch):
        self.engine, self.schema, self.monkeypatch = engine, schema, monkeypatch

    @contextmanager
    def sessions(self):
        with Session(self.engine) as session, session.begin():
            session.execute(text("SET LOCAL statement_timeout = '10s'"))
            yield session

    def state(self, identity=1):
        with self.sessions() as session:
            record = session.get(ConversationRecord, identity)
            message = session.get(ConversationMessage, 100)
            return {
                "title": record.conversation_title, "version": record.title_version,
                "activity": record.last_activity_time, "audit": record.update_time,
                "delete_flag": record.delete_flag,
                "content": message.message_content, "status": message.status,
            }

    def during_model(self, action):
        started, release = threading.Event(), threading.Event()

        def model(*_args):
            started.set()
            assert release.wait(10), "The title model gate was not released"
            return "Generated title"

        self.monkeypatch.setattr(service, "call_llm_for_title", model)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(self.client.post, "/api/conversation/generate_title", json={
                "conversation_id": 1, "question": "Question",
            })
            try:
                assert started.wait(10), "The real title endpoint did not reach the model boundary"
                action()
                committed = self.state()
            finally:
                released = monotonic()
                release.set()
            response = pending.result(timeout=15)
            assert monotonic() - released < 15
        return response, committed

    def complete(self, status):
        db.persist_assistant_run_batch(
            100, 1, "Assistant answer", status, [], [], [], [], [], "owner", "tenant",
        )


@pytest.fixture
def probe(monkeypatch):
    schema = "title_revision_" + uuid4().hex
    engine = create_engine(postgres_url()).execution_options(schema_translate_map={"nexent": schema})
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    try:
        with engine.begin() as connection:
            for model in (ConversationRecord, ConversationMessage, ConversationMessageUnit,
                          ConversationSourceSearch, ConversationSourceImage, UserTenant):
                model.__table__.create(connection)
        value = TitleProbe(engine, schema, monkeypatch)
        monkeypatch.setattr(db, "get_db_session", value.sessions)
        monkeypatch.setattr(user_tenant_db, "get_db_session", value.sessions)
        monkeypatch.setattr(routes, "get_current_user_info", lambda **_k: ("owner", "tenant", "en"))
        with value.sessions() as session:
            previous = datetime.now(timezone.utc) - timedelta(days=1)
            for identity, owner in ((1, "owner"), (2, "other")):
                session.add(ConversationRecord(
                    conversation_id=identity, conversation_title="New Conversation",
                    created_by=owner, updated_by=owner, delete_flag="N", workbench_config={},
                    last_activity_time=previous, update_time=previous.replace(tzinfo=None),
                ))
            session.add(ConversationMessage(
                message_id=100, conversation_id=1, message_index=1, message_role="assistant",
                message_content="", status="streaming", message_source="CHAT",
                created_by="owner", updated_by="owner", delete_flag="N",
            ))
            session.add(UserTenant(
                user_tenant_id=1, user_id="owner", tenant_id="tenant", user_role="USER",
                created_by="owner", updated_by="owner", delete_flag="N",
            ))
        app = FastAPI()
        app.include_router(routes.router, prefix="/api")
        with TestClient(app) as value.client:
            yield value
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        with engine.connect() as connection:
            assert connection.scalar(text(
                "SELECT count(*) FROM pg_namespace WHERE nspname = :schema"
            ), {"schema": schema}) == 0
        engine.dispose()


@pytest.mark.parametrize("mutation", ["none", "completed", "stopped", "user", "audit"])
def test_activity_does_not_invalidate_pending_title(probe, mutation):
    before = probe.state()

    def action():
        if mutation in {"completed", "stopped"}:
            probe.complete(mutation)
        elif mutation == "user":
            db.create_conversation_message({
                "conversation_id": 1, "message_idx": 2, "role": "user", "content": "User follow-up",
            }, "owner")
        elif mutation == "audit":
            with probe.sessions() as session:
                session.execute(update(ConversationRecord).where(
                    ConversationRecord.conversation_id == 1,
                ).values(chat_mode="planning", updated_by="owner"))

    response, committed = probe.during_model(action)
    assert response.status_code == 200
    assert response.json() == {"code": 0, "message": "success", "data": "Generated title"}
    after = probe.state()
    assert committed["version"] == 0 and after["version"] == 1
    assert committed["title"] == "New Conversation" and after["title"] == "Generated title"
    assert after["activity"] == committed["activity"]
    if mutation in {"completed", "stopped", "user"}:
        assert committed["activity"] > before["activity"]
        assert committed["audit"] > before["audit"]
    elif mutation == "audit":
        assert committed["audit"] > before["audit"]
        assert committed["activity"] == before["activity"]
    if mutation in {"completed", "stopped"}:
        assert after["content"] == "Assistant answer" and after["status"] == mutation
    elif mutation == "user":
        with probe.sessions() as session:
            message = session.get(ConversationMessage, 1)
            assert message.message_content == "User follow-up" and message.message_role == "user"


@pytest.mark.parametrize("mutation", ["different", "same", "rename_back", "competing"])
def test_title_revision_preserves_prior_rename(probe, mutation):
    def action():
        if mutation == "competing":
            snapshot = db.get_conversation(1, "owner")
            assert db.rename_conversation(1, "Other generated title", "owner", expected_snapshot=snapshot)
        elif mutation == "same":
            assert db.rename_conversation(1, "New Conversation", "owner")
        else:
            assert db.rename_conversation(1, "Manual title", "owner")
            if mutation == "rename_back":
                assert db.rename_conversation(1, "New Conversation", "owner")

    response, committed = probe.during_model(action)
    assert response.status_code == 200
    assert response.json() == {"code": 0, "message": "success", "data": committed["title"]}
    assert committed["version"] == (2 if mutation == "rename_back" else 1)
    assert probe.state() == committed


def test_deleted_or_foreign_history_rejects_title_write(probe, monkeypatch):
    response, deleted = probe.during_model(lambda: db.delete_conversation(1, "owner"))
    assert response.status_code == 500
    assert deleted["delete_flag"] == "Y" and deleted["version"] == 0
    assert probe.state() == deleted
    foreign = probe.state(2)
    model = MagicMock()
    monkeypatch.setattr(service, "call_llm_for_title", model)
    response = probe.client.post("/api/conversation/generate_title", json={
        "conversation_id": 2, "question": "Question",
    })
    assert response.status_code == 500
    model.assert_not_called()
    assert probe.state(2) == foreign


def test_additive_title_revision_migration_preserves_rows_and_replays(probe):
    root = Path(__file__).resolve().parents[3]
    source = (root / "deploy/sql/migrations/v2.7.1_008_conversation_title_version.sql").read_text(encoding="utf-8")
    sql = source.replace("nexent.", probe.schema + ".")
    with probe.engine.begin() as connection:
        connection.exec_driver_sql(f"ALTER TABLE {probe.schema}.conversation_record_t DROP COLUMN title_version")
        snapshot_sql = text(f"SELECT conversation_id, conversation_title, create_time, update_time, "
                            f"created_by, updated_by, delete_flag, last_activity_time "
                            f"FROM {probe.schema}.conversation_record_t ORDER BY conversation_id")
        before = list(connection.execute(snapshot_sql))
        connection.exec_driver_sql(sql)
        assert list(connection.execute(snapshot_sql)) == before
        assert list(connection.execute(text(f"SELECT title_version FROM {probe.schema}.conversation_record_t"))) == [(0,), (0,)]
        column = connection.execute(text(
            "SELECT data_type, is_nullable, column_default FROM information_schema.columns "
            "WHERE table_schema=:schema AND table_name='conversation_record_t' AND column_name='title_version'"
        ), {"schema": probe.schema}).one()
        assert tuple(column) == ("integer", "NO", "0")
    assert db.rename_conversation(1, "Migration rename", "owner")
    renamed = probe.state()
    with probe.engine.begin() as connection:
        connection.exec_driver_sql(sql)
        connection.exec_driver_sql(f"INSERT INTO {probe.schema}.conversation_record_t "
                                   "(conversation_id, conversation_title) VALUES (3, 'New row')")
        assert connection.scalar(text(f"SELECT title_version FROM {probe.schema}.conversation_record_t WHERE conversation_id=3")) == 0
        assert connection.scalar(text("SELECT count(*) FROM pg_tables WHERE schemaname=:schema"), {"schema": probe.schema}) == 6
    assert renamed["version"] == 1 and probe.state() == renamed
