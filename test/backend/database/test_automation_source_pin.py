# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Fence old source recovery by its original values and automation owner."""

from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import Session

from management.db.automation import repository
from management.db.automation.models import AgentAutomationRun


@pytest.fixture
def database(mocker):
    engine = create_engine("sqlite://", execution_options={"schema_translate_map": {AgentAutomationRun.__table__.schema: None}})
    metadata = MetaData()
    AgentAutomationRun.__table__.to_metadata(metadata, schema=None)
    metadata.create_all(engine)

    @contextmanager
    def sessions():
        with Session(engine) as session, session.begin():
            yield session

    mocker.patch.object(repository, "get_db_session", sessions)
    with sessions() as session:
        session.add(AgentAutomationRun(
            run_id=5, task_id=1, conversation_id=42, user_id="actor", tenant_id="tenant", status="RUNNING",
            scheduled_fire_at=datetime.now(timezone.utc), trigger_type="MANUAL", runtime_run_id="a" * 32,
            generated_prompt=None, user_message_id=None, created_by="actor", updated_by="actor", delete_flag="N",
        ))
    yield sessions
    engine.dispose()


def pin():
    return repository.update_run(5, {"generated_prompt": "hello", "user_message_id": 23}, "actor",
                                 expected_statuses=["RUNNING"], tenant_id="tenant",
                                 expected_source={"generated_prompt": None, "user_message_id": None})


def test_source_pin_updates_only_the_original_owned_running_record(database):
    saved = pin()
    assert saved["generated_prompt"] == "hello" and saved["user_message_id"] == 23
    assert saved["runtime_run_id"] == "a" * 32 and saved["updated_by"] == "actor"
    assert pin() is None


@pytest.mark.parametrize("field,value", [
    ("generated_prompt", "newer"), ("user_message_id", 24), ("status", "CANCELED"),
    ("user_id", "other"), ("tenant_id", "other"), ("delete_flag", "Y"),
])
def test_changed_source_status_or_owner_cannot_be_overwritten(database, field, value):
    with database() as session:
        setattr(session.get(AgentAutomationRun, 5), field, value)
    assert pin() is None
    with database() as session:
        run = session.get(AgentAutomationRun, 5)
        assert getattr(run, field) == value
        assert run.projection_message_index is None
