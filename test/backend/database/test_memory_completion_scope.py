# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Recover Memory inputs only from the leased assistant and its original prompt."""

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import JSON, MetaData
from sqlalchemy.dialects import postgresql

from infrastructure.rdb.agent_execution import AgentExecution
from infrastructure.rdb.conversation_record import ConversationMessage
from management.db.conversation import memory_completion as queue
from test.backend.database.test_prepared_saved_user import database
from test.backend.database.test_prepared_turn_resume import add_assistant, add_receipt, receipt_table

RUN_ID = "a" * 32
TOKEN = "b" * 32


@pytest.fixture
def leased(database, receipt_table, mocker):
    metadata = MetaData()
    table = queue.MemoryCompletion.__table__.to_metadata(metadata, schema=None)
    table.c.selected_items.type = JSON()
    with database.sessions() as session:
        metadata.create_all(session.get_bind())
        add_assistant(session)
        add_receipt(session, RUN_ID)
        session.add(AgentExecution(
            run_id=RUN_ID, conversation_id=42, tenant_id="tenant", status="completed",
            resource_versions={"agent_id": 7, "agent_version_no": 1},
            created_by="actor", updated_by="actor", delete_flag="N",
        ))
        session.add(queue.MemoryCompletion(
            job_id=f"{RUN_ID}:{queue.TURN_COMPLETED}", run_id=RUN_ID, job_type=queue.TURN_COMPLETED, agent_id=7,
            lease_token=TOKEN, next_attempt_at=datetime.now(timezone.utc) + timedelta(hours=1),
            created_by="actor", updated_by="actor", delete_flag="N",
        ))
    mocker.patch.object(queue, "get_db_session", database.sessions)
    mocker.patch.object(queue, "tenant_membership_matches", return_value=True)
    return database.sessions


@pytest.mark.parametrize("case", ["chat", "automation", "wrong-prompt", "missing-prompt", "unfinished", "revoked", "lease-lost"])
def test_owned_completion_uses_original_input_only(leased, case):
    message_id = None
    if case == "revoked":
        queue.tenant_membership_matches.return_value = False
    with leased() as session:
        assistant = session.get(ConversationMessage, 61)
        if case in {"automation", "wrong-prompt", "missing-prompt"}:
            assistant.message_source = "AUTOMATION"
            session.get(ConversationMessage, 23).message_source = "AUTOMATION"
            message_id = {"automation": 23, "wrong-prompt": 31, "missing-prompt": None}[case]
        elif case == "unfinished":
            assistant.status = "failed"
    job = queue.MemoryJob(
        RUN_ID, queue.TURN_COMPLETED, 7, TOKEN if case != "lease-lost" else "c" * 32, 1, None, message_id,
    )
    source = queue.read_source(job)
    if case in {"chat", "automation"}:
        assert source == queue.MemorySource("tenant", "actor", 42, 61, "finished", "hello", 1)
    else:
        assert source is None


def test_checkpoint_requires_current_lease_and_settles_only_its_job(leased):
    expired = queue.MemoryJob(RUN_ID, queue.TURN_COMPLETED, 7, "c" * 32, 1, None)
    active = queue.MemoryJob(RUN_ID, queue.TURN_COMPLETED, 7, TOKEN, 1, None)
    assert queue.checkpoint(expired, ["old"]) is False
    assert queue.checkpoint(active, ["retained"]) is True
    assert queue.settle(expired, retry=False) is False
    assert queue.settle(active, retry=False) is True
    assert queue.read_source(active) is None
    with leased() as session:
        row = session.get(queue.MemoryCompletion, f"{RUN_ID}:{queue.TURN_COMPLETED}")
        assert row.finished_at is not None
        assert row.lease_token is None
        assert row.selected_items is None


@pytest.mark.parametrize("status,answer,jobs", [
    ("completed", "answer", [queue.TURN_COMPLETED, queue.FINAL_ANSWER]),
    ("completed", " ", [queue.TURN_COMPLETED]),
    ("stopped", "partial", [queue.FINAL_ANSWER]),
    ("failed", "", []),
])
def test_enqueue_creates_only_applicable_deduplicated_jobs(mocker, status, answer, jobs):
    session = mocker.Mock()
    queue.enqueue(session, RUN_ID, 7, "actor", status, answer, source_message_id=23)
    if not jobs:
        session.execute.assert_not_called()
        return
    statement = session.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    assert "ON CONFLICT (job_id) DO NOTHING" in str(statement)
    for index, name in enumerate(jobs):
        assert statement.params[f"job_id_m{index}"] == f"{RUN_ID}:{name}"
        assert statement.params[f"source_message_id_m{index}"] == 23
        assert statement.params[f"agent_id_m{index}"] == 7


@pytest.mark.parametrize("attempts", [None, 1, queue._MAX_ATTEMPTS])
def test_claim_resets_exhausted_job_and_issues_a_fresh_lease(mocker, attempts):
    session = mocker.Mock()
    row = SimpleNamespace(
        run_id=RUN_ID, job_type=queue.TURN_COMPLETED, agent_id=7, attempts=attempts, lease_token="expired",
        selected_items=["previous"], source_message_id=23, finished_at=None, next_attempt_at=None,
    )
    session.scalar.return_value = None if attempts is None else row
    mocker.patch.object(queue, "get_db_session", return_value=nullcontext(session))
    token = mocker.patch.object(queue, "uuid4", return_value=SimpleNamespace(hex=TOKEN))
    job = queue.claim()
    assert "FOR UPDATE SKIP LOCKED" in str(session.scalar.call_args.args[0].compile(dialect=postgresql.dialect()))
    if attempts is None or attempts == queue._MAX_ATTEMPTS:
        assert job is None
        token.assert_not_called()
        if attempts is not None:
            assert row.finished_at is not None
            assert row.lease_token is None and row.selected_items is None
    else:
        assert job == queue.MemoryJob(RUN_ID, queue.TURN_COMPLETED, 7, TOKEN, 2, ["previous"], 23)
        assert row.next_attempt_at is not None
        assert row.finished_at is None


@pytest.mark.parametrize("version", [0, 1])
@pytest.mark.parametrize("change", [None, "tenant", "user", "conversation", "agent", "deleted"])
def test_source_version_is_bound_to_the_owned_execution(leased, version, change):
    with leased() as session:
        row = session.get(AgentExecution, RUN_ID)
        row.resource_versions = {"agent_id": 8 if change == "agent" else 7, "agent_version_no": version}
        if change == "tenant":
            row.tenant_id = "other"
        elif change == "user":
            row.created_by = "other"
        elif change == "conversation":
            row.conversation_id = 43
        elif change == "deleted":
            row.delete_flag = "Y"
    job = queue.MemoryJob(RUN_ID, queue.TURN_COMPLETED, 7, TOKEN, 1, None)
    source = queue.read_source(job)
    if change is None:
        assert source.agent_version_no == version
    else:
        assert source is None
