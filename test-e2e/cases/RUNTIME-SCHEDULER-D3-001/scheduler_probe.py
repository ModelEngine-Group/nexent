# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Seed and observe a disposable scheduled occurrence using the real PostgreSQL store."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import json
import sys
from time import monotonic, sleep
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import UUID, uuid5

from sqlalchemy import func, or_, select, text, update

from contracts.automation import ScheduleTrigger
from contracts.constants.environment import (
    AGENT_AUTOMATION_LEASE_SECONDS, AGENT_AUTOMATION_MAX_CONCURRENT_RUNS, POSTGRES_HOST, RUNTIME_STATE_REDIS_URL,
)
from infrastructure.rdb.client import get_db_session
from infrastructure.rdb.orm import as_dict
from infrastructure.redis.run_state import runtime_state_service
from management.db.agent.models import AgentInfo
from management.db.automation.models import AgentAutomationRun, AgentAutomationTask
from management.db.automation.repository import (
    claim_due_tasks, create_run, create_task, get_task, list_runs, release_task_lock, renew_task_lock,
    update_task_if_lock_owner,
)
from management.db.conversation.models import ConversationMessage, ConversationRecord
from management.db.execution.models import ExecutionReservation


def seed_occurrence(session, identifier, tenant, owner, instruction, agent_id, model_id, fixture_lock, max_fires):
    agent, = session.scalars(select(AgentInfo).where(
        AgentInfo.agent_id == int(agent_id), AgentInfo.version_no == 1, AgentInfo.tenant_id == tenant,
        AgentInfo.created_by == owner, AgentInfo.delete_flag == "N",
    ))
    assert int(model_id) in agent.model_ids
    scheduled = session.scalar(select(func.now())) - timedelta(seconds=1)
    trigger = ScheduleTrigger(mode="RECURRING", rule_type="INTERVAL", timezone="UTC", start_at=scheduled,
                              interval_seconds=60, max_fire_count=max_fires)
    fields = {
        "tenant_id": tenant, "user_id": owner, "conversation_id": identifier, "agent_id": agent.agent_id,
        "agent_version_no": agent.version_no, "title": "Disposable Runtime schedule", "instruction": instruction,
        "status": "ACTIVE", "source": "CHAT_INTENT", "schedule_mode": trigger.mode,
        "schedule_rule_type": trigger.rule_type, "schedule_config": trigger.model_dump(mode="json"),
        "capability_bindings": [], "runtime_snapshot": {"model_id": int(model_id)}, "timezone": trigger.timezone,
        "next_fire_at": scheduled, "timeout_seconds": 240, "overlap_policy": "SKIP", "misfire_policy": "SKIP",
    }
    if fixture_lock:
        fields.update(lock_owner=fixture_lock, lock_until=scheduled + timedelta(minutes=5))
    task = create_task(fields, owner)
    return {"task_id": task["task_id"], "scheduled": task["next_fire_at"], "fixture_lock": fixture_lock}


def snapshot(session, identifier, tenant, owner):
    task = session.scalar(select(AgentAutomationTask).where(
        AgentAutomationTask.conversation_id == identifier, AgentAutomationTask.tenant_id == tenant,
        AgentAutomationTask.user_id == owner, AgentAutomationTask.delete_flag == "N",
    ))
    runs = list(session.scalars(select(AgentAutomationRun).where(
        AgentAutomationRun.conversation_id == identifier, AgentAutomationRun.tenant_id == tenant,
        AgentAutomationRun.user_id == owner, AgentAutomationRun.delete_flag == "N",
    ).order_by(AgentAutomationRun.run_id)))
    reservations = list(session.scalars(select(ExecutionReservation).where(
        ExecutionReservation.execution_key == f"conversation:{identifier}", ExecutionReservation.tenant_id == tenant,
        ExecutionReservation.user_id == owner, ExecutionReservation.execution_kind == "agent",
        ExecutionReservation.delete_flag == "N",
    ).order_by(ExecutionReservation.execution_id)))
    messages = list(session.scalars(select(ConversationMessage).where(
        ConversationMessage.conversation_id == identifier, ConversationMessage.delete_flag == "N",
    ).order_by(ConversationMessage.message_index)))
    return {
        "task": as_dict(task) if task else None, "runs": [as_dict(row) for row in runs],
        "reservations": [as_dict(row) for row in reservations], "messages": [as_dict(row) for row in messages],
        "scheduler_capacity": AGENT_AUTOMATION_MAX_CONCURRENT_RUNS,
    }


def fixture_owner(token, actor):
    return f"runtime-scheduler-fixture:{token}:{actor}"


def claim_race_keys(token, task_id):
    return tuple(f"runtime-scheduler-case:{token}:{task_id}:ready:{actor}" for actor in ("first", "second"))


def race_coordination_store():
    host = urlsplit(RUNTIME_STATE_REDIS_URL).hostname
    if host not in {"nexent-redis", "nexent-redis.nexent", "nexent-redis.nexent.svc", "nexent-redis.nexent.svc.cluster.local"}:
        raise ValueError("The scheduler race requires the case-owned Redis service")
    return runtime_state_service.client


def contend_for_occurrence(token, task, actor):
    keys = claim_race_keys(token, task["task_id"])
    own_key = keys[0 if actor == "first" else 1]
    redis = race_coordination_store()
    assert redis.set(own_key, actor, ex=120, nx=True), "The contender has already joined this race"
    deadline = monotonic() + 40
    while redis.mget(keys) != ["first", "second"]:
        assert monotonic() < deadline, "Both scheduler-side claim workers did not reach the barrier"
        sleep(0.025)
    owner = fixture_owner(token, actor)
    claimed = claim_due_tasks(owner, 1, 120)
    assert len(claimed) <= 1 and all(row["task_id"] == task["task_id"] for row in claimed)
    return {"actor": actor, "owner": owner, "claimed": bool(claimed), "released_from_barrier": True}


def assert_only_race_row_due(session, task_id):
    rows = session.scalars(select(AgentAutomationTask.task_id).where(
        AgentAutomationTask.task_id != task_id, AgentAutomationTask.delete_flag == "N",
        AgentAutomationTask.status == "ACTIVE", AgentAutomationTask.next_fire_at <= func.now(),
        or_(AgentAutomationTask.lock_until.is_(None), AgentAutomationTask.lock_until < func.now()),
    ))
    assert not list(rows), "Refusing to poll an unrelated due scheduler task"


def assert_waiting_lease_updates_are_fenced(task):
    task_id, tenant, owner, lease_owner = (
        task[name] for name in ("task_id", "tenant_id", "user_id", "lock_owner")
    )
    task_row = update(AgentAutomationTask).where(
        AgentAutomationTask.task_id == task_id, AgentAutomationTask.tenant_id == tenant,
        AgentAutomationTask.user_id == owner, AgentAutomationTask.delete_flag == "N",
    )
    attempts = {
        "renewal": (renew_task_lock, (task_id, lease_owner, 120), False),
        "missed_fire": (update_task_if_lock_owner, (task_id, tenant, owner, lease_owner, {
            "next_fire_at": datetime.fromisoformat(task["next_fire_at"]) + timedelta(hours=1),
            "lock_owner": None, "lock_until": None,
        }), None),
    }
    rejected = {}
    with ThreadPoolExecutor(max_workers=1) as workers:
        for action, (operation, arguments, expected) in attempts.items():
            with get_db_session() as session:
                expiry = session.scalar(select(func.clock_timestamp())) + timedelta(seconds=4)
                session.execute(task_row.values(next_fire_at=None, lock_owner=lease_owner, lock_until=expiry))
            before = get_task(task_id, tenant, owner)
            with get_db_session() as blocker:
                blocker.execute(select(AgentAutomationTask.task_id).where(
                    AgentAutomationTask.task_id == task_id,
                ).with_for_update()).scalar_one()
                attempt = workers.submit(operation, *arguments)
                while blocker.scalar(select(func.clock_timestamp())) < expiry:
                    assert not attempt.done(), f"{action} did not wait for the held task row"
                    blocker.scalar(select(func.pg_stat_clear_snapshot()))
                    if blocker.scalar(text("""
                        SELECT EXISTS (
                            SELECT FROM pg_stat_activity
                            WHERE datname = current_database() AND xact_start < :expiry
                              AND pg_backend_pid() = ANY(pg_blocking_pids(pid))
                        )
                    """), {"expiry": expiry}):
                        break
                    sleep(0.02)
                else:
                    raise AssertionError(f"{action} did not reach PostgreSQL before lease expiry")
                while blocker.scalar(select(func.clock_timestamp())) <= expiry:
                    sleep(0.02)
            result = attempt.result(timeout=10)
            rejected[action] = result is expected and get_task(task_id, tenant, owner) == before

    assert all(rejected.values()), f"Expired row wait changed the task: {rejected}"
    with get_db_session() as session:
        session.execute(task_row.values(next_fire_at=task["next_fire_at"], lock_until=task["lock_until"]))
    return rejected


def reclaim_and_submit_stale_result(session, token, task, previous_actor):
    from management.services.automation.runner import agent_automation_runner

    task_id, tenant, owner = (task[name] for name in ("task_id", "tenant_id", "user_id"))
    stale_owner = fixture_owner(token, previous_actor)
    replacement = fixture_owner(token, "first" if previous_actor == "second" else "second")
    assert task["lock_owner"] == stale_owner and task["fire_count"] == 0
    assert not list_runs(task_id, tenant, owner)
    now = session.scalar(select(func.now()))
    previous_run = create_run({
        "task_id": task_id, "tenant_id": tenant, "user_id": owner, "conversation_id": task["conversation_id"],
        "scheduled_fire_at": task["next_fire_at"], "actual_fire_at": now, "started_at": now,
        "trigger_type": "SCHEDULED", "status": "RUNNING",
    }, owner)
    expired = update_task_if_lock_owner(task_id, tenant, owner, stale_owner,
                                        {"lock_until": now - timedelta(seconds=1)})
    assert expired is not None and not renew_task_lock(task_id, stale_owner, 120)
    before_reclaim = get_task(task_id, tenant, owner)
    with patch("management.services.automation.runner._utcnow", return_value=now - timedelta(minutes=2)):
        rejected = agent_automation_runner._finish_run({**previous_run, "_lease_owner": stale_owner},
                                                       task, "SUCCEEDED", {})
    assert rejected == previous_run, "Expired worker submitted a result before a peer could reclaim the lease"
    assert get_task(task_id, tenant, owner) == before_reclaim and list_runs(task_id, tenant, owner) == [previous_run]
    reclaimed, = claim_due_tasks(replacement, 1, 120)
    assert reclaimed["task_id"] == task_id and reclaimed["lock_owner"] == replacement
    before = get_task(task_id, tenant, owner)
    lost_run, = list_runs(task_id, tenant, owner)
    assert lost_run["run_id"] == previous_run["run_id"] and lost_run["status"] == "TIMEOUT"
    assert lost_run["error_code"] == "AUTOMATION_LEASE_EXPIRED"
    assert (before["next_fire_at"], before["fire_count"]) == (task["next_fire_at"], 0)
    late = agent_automation_runner._finish_run({**previous_run, "_lease_owner": stale_owner},
                                              task, "SUCCEEDED", {})
    assert late == lost_run
    assert update_task_if_lock_owner(task_id, tenant, owner, stale_owner,
                                     {"last_run_status": "SUCCEEDED", "fire_count": 1}) is None
    assert not renew_task_lock(task_id, stale_owner, 120) and not release_task_lock(task_id, stale_owner)
    assert get_task(task_id, tenant, owner) == before and list_runs(task_id, tenant, owner) == [lost_run]
    assert race_coordination_store().delete(*claim_race_keys(token, task_id)) == 2
    assert release_task_lock(task_id, replacement)
    return {"expired_run_id": lost_run["run_id"], "stale_completion_rejected": True}


def expire_live_occurrence(identifier, tenant, owner, token, run_id, execution_id):
    renewal_interval = AGENT_AUTOMATION_LEASE_SECONDS / 3
    deadline = monotonic() + renewal_interval + 5
    previous_expiry = None
    while monotonic() < deadline:
        with get_db_session() as session:
            state = snapshot(session, identifier, tenant, owner)
            task = state["task"]
            run, = state["runs"]
            reservation, = state["reservations"]
            assert task["instruction"] == f"runtime-stream:{token}:auto"
            assert task["status"] == "ACTIVE" and task["fire_count"] == 0 and task["lock_owner"]
            assert run["run_id"] == run_id and run["status"] == "RUNNING"
            assert reservation["execution_id"] == execution_id and reservation["status"] == "RUNNING"
            assert task["lock_owner"].rsplit("-", 5)[0] == reservation["owner_instance_id"].split(":")[0]
            current_expiry = datetime.fromisoformat(task["lock_until"])
            if previous_expiry is not None and current_expiry > previous_expiry:
                assert_only_race_row_due(session, task["task_id"])
                now = session.scalar(select(func.clock_timestamp()))
                claim_before = current_expiry - timedelta(seconds=AGENT_AUTOMATION_LEASE_SECONDS - renewal_interval)
                assert (claim_before - now).total_seconds() >= renewal_interval / 2
                expired = update_task_if_lock_owner(task["task_id"], tenant, owner, task["lock_owner"],
                                                    {"lock_until": now - timedelta(seconds=1)})
                assert expired is not None and expired["fire_count"] == 0
                return {"expired_at": now.isoformat(), "claim_before": claim_before.isoformat(),
                        "owner": task["lock_owner"]}
            previous_expiry = current_expiry
        sleep(0.1)
    raise AssertionError("The live scheduled worker did not renew its original lease")


def gate_settled_occurrence(session, identifier, tenant, owner, token, *, arm):
    state = snapshot(session, identifier, tenant, owner)
    task = state["task"]
    run, = state["runs"]
    reservation, = state["reservations"]
    assert task["instruction"] == f"runtime-stream:{token}:settled"
    assert task["fire_count"] == 0 and task["next_fire_at"] == run["scheduled_fire_at"]
    assert run["status"] == "RUNNING" and run["user_message_id"] is not None
    if not arm:
        assert task["status"] == "ACTIVE" and task["lock_owner"] and reservation["status"] == "RUNNING"
        now = session.scalar(select(func.clock_timestamp()))
        parked = update_task_if_lock_owner(task["task_id"], tenant, owner, task["lock_owner"],
                                          {"status": "PAUSED", "lock_until": now - timedelta(seconds=1)})
        assert parked and parked["next_fire_at"] == run["scheduled_fire_at"]
        return {"parked": True}
    assert task["status"] == "PAUSED" and task["lock_owner"] is None
    assert reservation["status"] in {"COMPLETED", "FAILED", "STOPPED"}
    rearmed = session.execute(update(AgentAutomationTask).where(
        AgentAutomationTask.task_id == task["task_id"], AgentAutomationTask.tenant_id == tenant,
        AgentAutomationTask.user_id == owner, AgentAutomationTask.delete_flag == "N",
        AgentAutomationTask.status == "PAUSED", AgentAutomationTask.lock_owner.is_(None),
        AgentAutomationTask.next_fire_at == datetime.fromisoformat(task["next_fire_at"]),
    ).values(status="ACTIVE"))
    assert rearmed.rowcount == 1
    return {"rearmed": True}


def observe_schedule(raw_token, action, raw_identifier, *arguments):
    token = UUID(hex=raw_token)
    identifier = int(raw_identifier)
    if token.hex != raw_token or identifier < 1 or POSTGRES_HOST not in {
        "nexent-postgresql", "nexent-postgresql.nexent", "nexent-postgresql.nexent.svc",
        "nexent-postgresql.nexent.svc.cluster.local",
    }:
        raise ValueError("The scheduler fixture requires a case-owned database and conversation")
    owner, tenant = str(uuid5(token, "owner:user")), str(uuid5(token, "owner:tenant"))
    with get_db_session() as session:
        session.execute(select(ConversationRecord.conversation_id).where(
            ConversationRecord.conversation_id == identifier, ConversationRecord.created_by == owner,
            ConversationRecord.delete_flag == "N",
        )).scalar_one()
        if action == "seed" and len(arguments) == 3 and arguments[0] in {"auto", "busy", "pending", "race", "settled"}:
            tag, agent_id, model_id = arguments
            fixture_lock = f"runtime-scheduler-fixture:{raw_token}" if tag == "pending" else None
            return seed_occurrence(session, identifier, tenant, owner, f"runtime-stream:{raw_token}:{tag}",
                                   agent_id, model_id, fixture_lock, 2 if tag in {"auto", "settled"} else 1)
        if action == "snapshot" and not arguments:
            return snapshot(session, identifier, tenant, owner)
        if action == "expire-live" and len(arguments) == 2:
            return expire_live_occurrence(identifier, tenant, owner, raw_token, *(int(value) for value in arguments))
        if action in {"park-settled", "rearm-settled"} and not arguments:
            return gate_settled_occurrence(session, identifier, tenant, owner, raw_token, arm=action == "rearm-settled")
        if action in {"compete", "reclaim"} and len(arguments) == 1 and arguments[0] in {"first", "second"}:
            task = snapshot(session, identifier, tenant, owner)["task"]
            assert task["instruction"] == f"runtime-stream:{raw_token}:race" and task["status"] == "ACTIVE"
            assert_only_race_row_due(session, task["task_id"])
            if action == "compete":
                return contend_for_occurrence(raw_token, task, arguments[0])
            return reclaim_and_submit_stale_result(session, raw_token, task, arguments[0])
        if action in {"wait-expiry", "unblock"} and not arguments:
            task = snapshot(session, identifier, tenant, owner)["task"]
            fixture_lock = f"runtime-scheduler-fixture:{raw_token}"
            assert task["instruction"] == f"runtime-stream:{raw_token}:pending" and task["lock_owner"] == fixture_lock
            if action == "wait-expiry":
                return assert_waiting_lease_updates_are_fenced(task)
            unlocked = update_task_if_lock_owner(task["task_id"], tenant, owner, fixture_lock,
                                                 {"lock_owner": None, "lock_until": None})
            return {"unblocked": unlocked is not None}
    raise ValueError("Unknown scheduler fixture operation")


if __name__ == "__main__":
    print("SCALING_SCHEDULER " + json.dumps(observe_schedule(*sys.argv[1:])))
