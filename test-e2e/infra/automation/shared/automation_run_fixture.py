# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Disposable PostgreSQL collaboration fixture shared by automation D3/D5."""

from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from shared.postgres import apply_product_postgres_env

apply_product_postgres_env()

from management.db.automation import messages, repository as runs
from management.db.client import db_client
from management.db.conversation import repository as conversations
from management.db.models import (
    AgentAutomationRun, AgentAutomationTask, ConversationMessage, ConversationMessageUnit,
    ConversationRecord, ConversationSourceImage, ConversationSourceSearch,
)


@pytest.fixture
def run_store(monkeypatch):
    schema = "auto_outcome_" + uuid4().hex
    engine = db_client.engine.execution_options(schema_translate_map={"nexent": schema})
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
        for model in (ConversationRecord, ConversationMessage, ConversationMessageUnit,
                      ConversationSourceSearch, ConversationSourceImage, AgentAutomationTask, AgentAutomationRun):
            model.__table__.create(connection)

    @contextmanager
    def sessions(db_session=None):
        if db_session is not None:
            yield db_session
            return
        with Session(engine) as session, session.begin():
            session.execute(text("SET LOCAL lock_timeout = '3s'"))
            session.execute(text("SET LOCAL statement_timeout = '5s'"))
            yield session

    for module in (messages, runs, conversations):
        monkeypatch.setattr(module, "get_db_session", sessions)
    now = datetime.now(timezone.utc)
    task_data = dict(
        tenant_id="tenant", user_id="owner", conversation_id=1, agent_id=7,
        title="Controlled automation", instruction="Controlled prompt", status="ACTIVE",
        source="MANUAL", schedule_mode="RECURRING", schedule_rule_type="INTERVAL",
        timezone="UTC", schedule_config={"mode": "RECURRING", "rule_type": "INTERVAL",
                                         "timezone": "UTC", "start_at": now.isoformat(), "interval_seconds": 3600},
        runtime_snapshot={"agent_id": 7}, capability_bindings=[], timeout_seconds=1,
        overlap_policy="SKIP", misfire_policy="FIRE_ONCE", next_fire_at=now,
        fire_count=0, consecutive_failures=0,
    )
    try:
        with sessions() as session:
            session.add(ConversationRecord(conversation_id=1, conversation_title="Fixture",
                                           created_by="owner", updated_by="owner", delete_flag="N"))
        task = runs.create_task(task_data, "owner")

        def new_run():
            return runs.create_run(dict(task_id=task["task_id"], tenant_id="tenant", user_id="owner",
                conversation_id=1, scheduled_fire_at=now, trigger_type="MANUAL",
                status="RUNNING", started_at=now), "owner")

        def rows(model):
            with sessions() as session:
                return [dict(row) for row in session.execute(select(model.__table__)).mappings()]

        yield SimpleNamespace(sessions=sessions, task=task, new_run=new_run, rows=rows, schema=schema)
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        with db_client.engine.connect() as connection:
            assert connection.scalar(text("SELECT to_regnamespace(:schema)"), {"schema": schema}) is None
