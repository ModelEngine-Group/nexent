# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Real PostgreSQL rollback, idempotency, ownership and cancellation races."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest
from sqlalchemy import event

from shared.automation_run_fixture import run_store
from management.db.automation import messages, repository as runs
from management.db.conversation import repository as conversations
from management.services.automation.runner import AgentAutomationRunner, _parse_dt
from management.db.models import AgentAutomationRun, ConversationMessage, ConversationMessageUnit, ConversationRecord

pytestmark = [pytest.mark.case_id("AUTO-RUN-D5-001"), pytest.mark.stage("D5")]


def create(run_id, role="user", **kwargs):
    return messages.create_run_message(run_id, dict(
        conversation_id=1, message_idx=0, role=role, content="prompt" if role == "user" else "",
    ), kwargs.get("user_id", "owner"), kwargs.get("tenant_id", "tenant"))


@pytest.mark.parametrize("fault", ["unit", "association", "assistant_association"])
def test_message_and_run_reference_rollback_together(run_store, monkeypatch, fault):
    run_id = run_store.new_run()["run_id"]
    if fault == "assistant_association":
        create(run_id)
    before = run_store.rows(ConversationMessage)
    activity = run_store.rows(ConversationRecord)[0]["last_activity_time"]
    if fault == "unit":
        original = conversations.create_message_unit

        def fail(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("injected unit failure")

        monkeypatch.setattr(conversations, "create_message_unit", fail)
    else:
        def fail_association(connection, cursor, statement, parameters, context, many):
            if statement.startswith("UPDATE") and "agent_automation_run_t" in statement:
                raise RuntimeError("injected association failure")

        with run_store.sessions() as session:
            engine = session.bind
        event.listen(engine, "before_cursor_execute", fail_association)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            create(run_id, "assistant" if fault == "assistant_association" else "user")
    finally:
        if fault != "unit":
            event.remove(engine, "before_cursor_execute", fail_association)
    assert run_store.rows(ConversationMessage) == before
    assert run_store.rows(ConversationRecord)[0]["last_activity_time"] == activity
    run = runs.get_run(run_id, "tenant", "owner")
    assert run["assistant_message_id"] is None
    if fault != "assistant_association":
        assert run["user_message_id"] is None
        assert run_store.rows(ConversationMessageUnit) == []
    if fault == "unit":
        monkeypatch.setattr(conversations, "create_message_unit", original)
    role = "assistant" if fault == "assistant_association" else "user"
    identity = create(run_id, role)
    assert create(run_id, role) == identity
    assert runs.get_run(run_id, "tenant", "owner")[
        "assistant_message_id" if role == "assistant" else "user_message_id"
    ] == identity


def test_duplicate_creation_is_idempotent_and_rejects_conflicting_prompt(run_store):
    run_id = run_store.new_run()["run_id"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = [future.result(timeout=8) for future in [pool.submit(create, run_id) for _ in range(2)]]
        assistant_ids = [future.result(timeout=8) for future in [pool.submit(create, run_id, "assistant") for _ in range(2)]]
    assert ids[0] == ids[1] and assistant_ids[0] == assistant_ids[1]
    assert len(run_store.rows(ConversationMessage)) == 2
    assert len(run_store.rows(ConversationMessageUnit)) == 1
    with pytest.raises(ValueError, match="conflicts"):
        messages.create_run_message(run_id, dict(conversation_id=1, message_idx=0,
                                                role="user", content="different"), "owner", "tenant")


@pytest.mark.parametrize("role", ["user", "assistant"])
def test_cancel_races_message_binding_without_orphan_or_late_completion(run_store, role):
    run_id = run_store.new_run()["run_id"]
    if role == "assistant":
        create(run_id)
    gate = Barrier(2)

    def writer():
        gate.wait(timeout=5)
        try:
            return create(run_id, role)
        except ValueError as exc:
            assert "no longer active" in str(exc)
            return None

    def cancel():
        gate.wait(timeout=5)
        return runs.cancel_run(run_id, "tenant", "owner", "controlled cancellation")

    with ThreadPoolExecutor(max_workers=2) as pool:
        written, canceled = pool.submit(writer), pool.submit(cancel)
        identity = written.result(timeout=8)
        assert canceled.result(timeout=8)["status"] == "CANCELED"
    run = runs.get_run(run_id, "tenant", "owner")
    assert run["user_message_id" if role == "user" else "assistant_message_id"] == identity
    assert runs.update_run(run_id, {"status": "SUCCEEDED"}, "owner", expected_statuses=["RUNNING"]) is None
    linked = {run["user_message_id"], run["assistant_message_id"]} - {None}
    assert {row["message_id"] for row in run_store.rows(ConversationMessage)} == linked
    with pytest.raises(ValueError, match="no longer active"):
        create(run_id, role)


def test_cancel_and_projection_commit_keep_links_and_terminal_status(run_store):
    run_id = run_store.new_run()["run_id"]
    prompt_id = create(run_id)
    assistant_id = create(run_id, "assistant")
    gate = Barrier(2)

    def finalize():
        gate.wait(timeout=5)
        conversations.persist_assistant_run_batch(
            assistant_id, 1, "completed output", "completed", [], [], [], [], [], "owner", "tenant",
        )
        return runs.update_run(run_id, {"status": "SUCCEEDED"}, "owner", expected_statuses=["RUNNING"])

    def cancel():
        gate.wait(timeout=5)
        return runs.cancel_run(run_id, "tenant", "owner", "controlled cancellation")

    with ThreadPoolExecutor(max_workers=2) as pool:
        completion, cancellation = pool.submit(finalize), pool.submit(cancel)
        finished, canceled = completion.result(timeout=8), cancellation.result(timeout=8)
    result = runs.get_run(run_id, "tenant", "owner")
    assert result["status"] == ("CANCELED" if canceled else "SUCCEEDED")
    assert bool(finished) != bool(canceled)
    assert (result["user_message_id"], result["assistant_message_id"]) == (prompt_id, assistant_id)
    message = next(row for row in run_store.rows(ConversationMessage) if row["message_id"] == assistant_id)
    assert message["status"] == "completed" and message["message_content"] == "completed output"


@pytest.mark.parametrize("invalid", ["tenant", "owner", "deleted_conversation", "deleted_run"])
def test_binding_rejects_foreign_and_deleted_records(run_store, invalid):
    run_id = run_store.new_run()["run_id"]
    if invalid.startswith("deleted"):
        with run_store.sessions() as session:
            model = ConversationRecord if invalid == "deleted_conversation" else AgentAutomationRun
            session.execute(model.__table__.update().values(delete_flag="Y"))
    with pytest.raises(ValueError, match="unavailable|no longer active"):
        create(run_id, user_id="other" if invalid == "owner" else "owner",
               tenant_id="other" if invalid == "tenant" else "tenant")
    assert run_store.rows(ConversationMessage) == []


def scheduled(store):
    task = store.task
    now = datetime.now(timezone.utc)
    runs.update_task(task["task_id"], "tenant", "owner", {
        "lock_owner": "fixture", "lock_until": now + timedelta(minutes=1),
    })
    run = runs.create_run(dict(task_id=task["task_id"], tenant_id="tenant", user_id="owner",
        conversation_id=1, scheduled_fire_at=task["next_fire_at"], actual_fire_at=now,
        trigger_type="SCHEDULED", status="RUNNING", started_at=now), "owner")
    return {**run, "_lease_owner": "fixture"}


@pytest.mark.parametrize("mode", ["once", "recurring", "paused", "manual"])
def test_cancel_advances_once_and_preserves_manual_and_paused_schedule(run_store, mode):
    task = run_store.task
    if mode == "once":
        runs.update_task(task["task_id"], "tenant", "owner", {"schedule_config": {
            "mode": "ONCE", "rule_type": "AT", "timezone": "UTC",
            "start_at": task["next_fire_at"],
        }})
    run = run_store.new_run() if mode == "manual" else scheduled(run_store)
    if mode == "paused":
        runs.update_task(task["task_id"], "tenant", "owner", {"status": "PAUSED"})
    runner = AgentAutomationRunner()
    result, won = runner.cancel_run_by_user(run, task)
    assert won and result["status"] == "CANCELED"
    after = runs.get_task(task["task_id"], "tenant", "owner")
    assert after["fire_count"] == (0 if mode == "manual" else 1)
    assert after["last_run_status"] == "CANCELED"
    assert after["consecutive_failures"] == 0
    if mode == "once":
        assert after["status"] == "COMPLETED" and after["next_fire_at"] is None
    elif mode == "manual":
        assert after["next_fire_at"] == task["next_fire_at"]
    else:
        assert _parse_dt(after["next_fire_at"]) > datetime.now(timezone.utc)
        assert after["status"] == ("PAUSED" if mode == "paused" else "ACTIVE")
    assert runner.cancel_run_by_user(run, task)[1] is False
    assert runner._finish_run(run, task, "SUCCEEDED", {})["status"] == "CANCELED"
    assert runs.get_task(task["task_id"], "tenant", "owner") == after


def test_finalization_rolls_back_run_and_task_together(run_store):
    run = scheduled(run_store)
    before = runs.get_task(run_store.task["task_id"], "tenant", "owner")
    with run_store.sessions() as session:
        engine = session.bind

    def fail(connection, cursor, statement, parameters, context, many):
        if statement.startswith("UPDATE") and "agent_automation_task_t" in statement:
            raise RuntimeError("injected task finalization failure")

    event.listen(engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            AgentAutomationRunner().cancel_run_by_user(run, run_store.task)
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert runs.get_run(run["run_id"], "tenant", "owner")["status"] == "RUNNING"
    assert runs.get_task(run_store.task["task_id"], "tenant", "owner") == before
    assert AgentAutomationRunner().cancel_run_by_user(run, run_store.task)[1]


def test_concurrent_terminal_winners_advance_one_occurrence(run_store):
    run = scheduled(run_store)
    barrier = Barrier(2)

    def finish(status):
        barrier.wait(timeout=3)
        return AgentAutomationRunner()._finish_run(run, run_store.task, status, {})

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(finish, status) for status in ("CANCELED", "SUCCEEDED")]
        results = [future.result(timeout=8) for future in futures]
    assert results[0]["status"] == results[1]["status"]
    task = runs.get_task(run_store.task["task_id"], "tenant", "owner")
    assert task["fire_count"] == 1 and task["last_run_status"] == results[0]["status"]
    assert _parse_dt(task["next_fire_at"]) > datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_stale_claim_does_not_create_another_run(run_store):
    run = scheduled(run_store)
    runner = AgentAutomationRunner()
    runner.cancel_run_by_user(run, run_store.task)
    assert await runner.execute_task(run_store.task, lease_owner="fixture") == {}
    assert len(runs.list_runs(run_store.task["task_id"], "tenant", "owner")) == 1


def test_history_uses_actual_time_and_deterministic_ties(run_store):
    now = datetime.now(timezone.utc)
    task_id = run_store.task["task_id"]
    ids = []
    for actual, started, planned in ((now-timedelta(minutes=1), now, now+timedelta(days=1)),
                                     (now, now, now), (None, now, now), (None, None, now)):
        ids.append(runs.create_run(dict(task_id=task_id, tenant_id="tenant", user_id="owner",
            conversation_id=1, scheduled_fire_at=planned, actual_fire_at=actual,
            started_at=started, status="SUCCEEDED", trigger_type="MANUAL"), "owner")["run_id"])
    expected = [ids[3], ids[2], ids[1], ids[0]]
    assert [r["run_id"] for r in runs.list_runs(task_id, "tenant", "owner")] == expected
    page = runs.list_runs_paginated(task_id, "tenant", "owner", 1, 2)
    assert page["total"] == 4 and [r["run_id"] for r in page["items"]] == expected[:2]
    assert [r["run_id"] for r in runs.list_runs_paginated(task_id, "tenant", "owner", 2, 2)["items"]] == expected[2:]


@pytest.mark.parametrize("state", ["paused", "lost_lease", "expired_lease"])
def test_terminal_result_preserves_paused_or_reclaimed_task(run_store, state):
    run = scheduled(run_store)
    changes = {"status": "PAUSED"} if state == "paused" else {
        "lock_owner": "replacement" if state == "lost_lease" else "fixture",
        "lock_until": datetime.now(timezone.utc) + timedelta(seconds=-1 if state == "expired_lease" else 60),
    }
    before = runs.update_task(run_store.task["task_id"], "tenant", "owner", changes)
    result = AgentAutomationRunner()._finish_run(run, run_store.task, "SUCCEEDED", {})
    assert result["status"] == "SUCCEEDED"
    after = runs.get_task(run_store.task["task_id"], "tenant", "owner")
    if state == "paused":
        assert after["status"] == "PAUSED" and after["fire_count"] == 1
    else:
        assert after == before
