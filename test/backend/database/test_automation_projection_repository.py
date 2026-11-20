# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Persist the terminal run and its schedule under one lease-checked transaction."""

from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest
from sqlalchemy import JSON, MetaData, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from management.db.automation import repository
from management.db.automation.models import AgentAutomationRun, AgentAutomationTask

NOW = datetime(2026, 11, 19, 1)
RUN_ID = "a" * 32


@pytest.fixture
def database(mocker):
    engine = create_engine("sqlite://", execution_options={
        "schema_translate_map": {AgentAutomationRun.__table__.schema: None},
    })
    metadata = MetaData()
    for model in (AgentAutomationTask, AgentAutomationRun):
        table = model.__table__.to_metadata(metadata, schema=None)
        for column in table.c:
            if isinstance(column.type, JSONB):
                column.type = JSON()
    metadata.create_all(engine)

    @contextmanager
    def sessions():
        with Session(engine) as session, session.begin():
            yield session

    mocker.patch.object(repository, "get_db_session", sessions)
    mocker.patch.object(repository, "_utcnow", return_value=NOW)
    with sessions() as session:
        session.add(AgentAutomationTask(
            task_id=6, tenant_id="tenant", user_id="actor", conversation_id=42, agent_id=7,
            title="Task", instruction="Run", status="ACTIVE", source="MANUAL", schedule_mode="ONCE",
            schedule_rule_type="AT", schedule_config={}, timezone="UTC", timeout_seconds=120,
            overlap_policy="SKIP", misfire_policy="SKIP", fire_count=1, created_by="actor",
            updated_by="actor", delete_flag="N",
        ))
        session.add(AgentAutomationRun(
            run_id=9, task_id=6, tenant_id="tenant", user_id="actor", conversation_id=42,
            scheduled_fire_at=NOW, trigger_type="MANUAL", status="RUNNING", runtime_run_id=RUN_ID,
            projection_message_index=3, created_by="actor", updated_by="actor", delete_flag="N",
        ))
    yield sessions
    engine.dispose()


def test_pending_and_active_queries_observe_the_same_owned_projection(database):
    assert repository.list_active_runtime_run_ids(42, "actor", "tenant") == [RUN_ID]
    assert repository.list_active_runtime_run_ids(42, "actor", "other") == []
    rows = repository.list_pending_projections(0, 4)
    assert [(row["run_id"], row["runtime_run_id"], row["projection_message_index"]) for row in rows] == [(9, RUN_ID, 3)]
    assert repository.list_pending_projections(9, 4) == []
    with database() as session:
        session.get(AgentAutomationTask, 6).tenant_id = "another-tenant"
    assert repository.list_pending_projections(0, 4) == []


@pytest.mark.parametrize("case", ["manual", "scheduled", "stale-lease", "stale-run", "foreign-task"])
def test_finishing_projection_respects_task_lease_and_manual_schedule(database, case):
    manual = case == "manual"
    owner = "worker" if case != "stale-lease" else "previous-worker"
    with database() as session:
        task = session.get(AgentAutomationTask, 6)
        task.status = "PAUSED"
        run = session.get(AgentAutomationRun, 9)
        run.trigger_type = "MANUAL" if manual else "SCHEDULED"
        if case in {"scheduled", "stale-lease"}:
            task.lock_owner, task.lock_until = "worker", NOW + timedelta(minutes=5)
        elif case == "stale-run":
            run.status = "CANCELED"
        elif case == "foreign-task":
            task.tenant_id = "another-tenant"
    staged = {
        "run_id": 9, "task_id": 6, "tenant_id": "tenant", "user_id": "actor", "conversation_id": 42,
        "trigger_type": "MANUAL" if manual else "SCHEDULED", "status": "RUNNING", "_lease_owner": owner,
    }
    result = repository.finish_prepared_run(
        staged, {"status": "SUCCEEDED", "projection_message_index": None, "assistant_message_id": 61},
        {"status": "FINISHED", "fire_count": 2, "last_fire_at": NOW, "last_run_status": "SUCCEEDED", "last_error": None},
    )
    with database() as session:
        task = session.get(AgentAutomationTask, 6)
        run = session.get(AgentAutomationRun, 9)
        assert task.status == "PAUSED"
        if case in {"manual", "scheduled"}:
            assert (result["run_id"], result["assistant_message_id"]) == (9, 61)
            assert (run.status, run.projection_message_index) == ("SUCCEEDED", None)
            assert task.last_run_status == "SUCCEEDED"
            assert task.fire_count == (1 if manual else 2)
        else:
            assert result is None
            assert run.projection_message_index == 3
            assert task.last_run_status is None
