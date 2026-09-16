"""HITL persistence behavior tests using an isolated PostgreSQL database.

The opt-in hitl_test fixture prepares tables from application ORM models.
Never point the fixture at a business database.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import insert, select

from database.db_models import (
    ConversationRecord,
    HumanEvent,
    HumanExecution,
    HumanRequest,
    HumanRun,
)
from services.human_interaction.models import InteractionError
from test.backend.services import test_human_interaction as hitl_support
from test.backend.services.test_human_interaction import (
    create_run,
    decide_pending,
    port_for,
)

service = hitl_support.service


def test_concurrent_run_creation_serializes_before_checking_uniqueness(service):
    barrier = Barrier(8)

    def create():
        barrier.wait(timeout=10)
        try:
            return create_run(service)
        except InteractionError as exc:
            assert "active human interaction run" in str(exc)
            return None

    with ThreadPoolExecutor(max_workers=8) as workers:
        results = list(workers.map(lambda _: create(), range(8)))
    assert len([value for value in results if value]) == 1
    with service.repository.session_factory() as session:
        assert len(list(session.scalars(select(HumanRun)))) == 1


@pytest.mark.parametrize("conversation_id,user_id", [(999, "owner"), (7, "other")])
def test_missing_or_unowned_conversation_cannot_create_a_run(service, conversation_id, user_id):
    with pytest.raises(InteractionError) as exc:
        service.create("tenant-a", user_id, conversation_id, {})
    assert exc.value.status_code == 404
    assert service.repository.latest("tenant-a", user_id, conversation_id) is None


def test_public_run_identity_collision_is_rejected_even_after_completion(service, monkeypatch):
    run_id = create_run(service)
    service.control(run_id, "tenant-a", "owner", "terminate")
    monkeypatch.setattr("services.human_interaction.service.uuid4", lambda: run_id)
    with pytest.raises(InteractionError, match="identity already exists"):
        create_run(service)


def test_concurrent_requests_leave_only_one_pending_request(service):
    run_id = create_run(service)
    barrier = Barrier(2)

    def request(slot):
        barrier.wait(timeout=10)
        try:
            with service.repository.transaction(run_id, "tenant-a", "owner") as tx:
                service.request(tx, kind="CLARIFICATION", slot=slot, action_digest="0" * 64,
                                payload={"question": "Continue?"})
            return True
        except InteractionError as exc:
            assert "pending human request" in str(exc)
            return False

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(request, ["a", "b"])) == [False, True]
    assert len(service.snapshot(run_id, "tenant-a", "owner")["requests"]) == 1


def test_duplicate_execution_and_foreign_run_reference_are_rejected(service):
    run_id = create_run(service)
    port = port_for(service, run_id, allowed={"send"})
    assert port.dispatch("slot", "send", {})["status"] == "execute"
    for foreign in (False, True):
        with pytest.raises(InteractionError, match="locked run" if foreign else "execution at this slot"), service.repository.transaction(run_id) as tx:
            tx.add(HumanExecution(
                run_record_id=tx.run.run_record_id + int(foreign), slot="slot", tool="send",
                digest="0" * 64, arguments=service.cipher.seal({}), status="PREPARED",
            ))
    with service.repository.transaction(run_id) as tx:
        assert len(tx.executions()) == 1
        assert tx.execution("slot").status == "STARTED"


@pytest.mark.parametrize("field,value", [("status", "INVALID"), ("pause_requested", 2),
                                         ("fence", 2**31), ("lock_owner", "x" * 201)])
def test_invalid_run_update_rolls_back_before_persistence(service, field, value):
    run_id = create_run(service)
    with pytest.raises(InteractionError) as exc, service.repository.transaction(run_id) as tx:
        setattr(tx.run, field, value)
    assert exc.value.status_code == 422
    with service.repository.transaction(run_id) as tx:
        assert tx.run.status == "READY"
        assert getattr(tx.run, field) != value


@pytest.mark.parametrize("kind,status", [("INVALID", "PENDING"), ("CLARIFICATION", "INVALID")])
def test_request_enums_are_validated_in_service(service, kind, status):
    from database.human_interaction_db import utcnow

    run_id = create_run(service)
    with pytest.raises(InteractionError, match="request state"), service.repository.transaction(run_id) as tx:
        tx.add(HumanRequest(run_record_id=tx.run.run_record_id, request_id="test-request", kind=kind,
                            status=status, version=1, slot="slot", digest="0" * 64,
                            payload=service.cipher.seal({}), expires_at=utcnow()))
    assert service.snapshot(run_id, "tenant-a", "owner")["requests"] == []


@pytest.mark.parametrize("payload", [[], {}, {"chunk_cipher": 1}, {"type": "event", "content": []},
                                    {"type": "event", "content": {"number": float("nan")}}])
def test_invalid_event_json_does_not_advance_cursor(service, payload):
    run_id = create_run(service)
    with pytest.raises(InteractionError), service.repository.transaction(run_id) as tx:
        tx.emit(payload)
    assert service.snapshot(run_id, "tenant-a", "owner")["event_seq"] == 0
    assert service.repository.events(run_id) == []


def test_parallel_event_batches_have_no_duplicate_or_missing_sequences(service):
    run_id = create_run(service)
    barrier = Barrier(4)

    def emit_batch(worker):
        barrier.wait(timeout=10)
        with service.repository.transaction(run_id) as tx:
            for index in range(8):
                tx.emit({"type": "test", "content": {"worker": worker, "index": index}})

    with ThreadPoolExecutor(max_workers=4) as workers:
        list(workers.map(emit_batch, range(4)))
    assert [item["seq"] for item in service.repository.events(run_id)] == list(range(1, 33))
    assert [item["seq"] for item in service.repository.events(run_id, after=30)] == [31, 32]


def test_audit_tracks_user_scheduler_and_receipt_updates(service):
    from nexent.core.human_interaction.contracts import AttemptSuspended

    run_id = create_run(service)
    with service.repository.transaction(run_id) as tx:
        created_at = tx.run.create_time
        assert tx.run.created_by == tx.run.updated_by == "owner"
    port = port_for(service, run_id)
    with pytest.raises(AttemptSuspended):
        port.dispatch("slot", "send", {})
    with service.repository.transaction(run_id) as tx:
        request = tx.requests()[0]
        request_time = request.create_time
        assert request.created_by == request.updated_by == "owner"
    decide_pending(service, run_id)
    assert port.dispatch("slot", "send", {})["status"] == "execute"
    port.receipt("slot", "ok")
    assert service.repository.renew(run_id, "worker", 120)
    with service.repository.transaction(run_id) as tx:
        assert tx.run.created_by == "owner"
        assert tx.run.updated_by == "system:hitl"
        assert tx.run.create_time == created_at
        assert tx.run.update_time > created_at
        request = tx.requests()[0]
        assert request.create_time == request_time and request.update_time > request_time
        for row in [tx.run, request, tx.execution("slot")]:
            assert row.delete_flag == "N" and row.created_by and row.updated_by


def test_deleted_rows_are_excluded_from_history_dispatch_and_claims(service):
    run_id = create_run(service)
    port = port_for(service, run_id, allowed={"send"})
    port.dispatch("slot", "send", {})
    with service.repository.transaction(run_id) as tx:
        tx.execution("slot").delete_flag = "Y"
    with service.repository.transaction(run_id) as tx:
        assert tx.execution("slot") is None and tx.executions() == []
    with service.repository.transaction(run_id) as tx:
        tx.run.delete_flag = "Y"
    assert service.repository.latest("tenant-a", "owner", 7) is None
    assert service.repository.events(run_id) == []
    assert service.repository.claim("other-worker", 10, 120) == []
    assert service.repository.waiting_ids() == []
    with service.repository.session_factory() as session:
        assert all(row.delete_flag == "Y" for row in session.scalars(select(HumanEvent)))
        assert all(row.delete_flag == "Y" for row in session.scalars(select(HumanExecution)))
    with service.repository.transaction(run_id) as tx:
        assert tx is None
    assert create_run(service) != run_id


def test_scheduler_audits_multiple_abandoned_and_claimed_runs(service, monkeypatch):
    from datetime import timedelta

    from database import human_interaction_db

    with service.repository.session_factory() as session:
        session.execute(insert(ConversationRecord), [
            {"conversation_id": number, "created_by": "owner", "updated_by": "owner", "delete_flag": "N"}
            for number in (8, 9, 10)
        ])
    abandoned = [service.create("tenant-a", "owner", number, {}, ready=False) for number in (7, 8)]
    ready = [service.create("tenant-a", "owner", number, {}) for number in (9, 10)]
    future = human_interaction_db.utcnow() + timedelta(seconds=121)
    monkeypatch.setattr(human_interaction_db, "utcnow", lambda: future)
    assert {item["run_id"] for item in service.repository.claim("worker", 10, 120)} == set(ready)
    for run_id in abandoned:
        with service.repository.transaction(run_id) as tx:
            assert tx.run.status == "FAILED" and tx.run.updated_by == "system:hitl"
        events = service.repository.events(run_id)
        assert len(events) == 1 and events[0]["payload"]["content"]["run_id"] == run_id


@pytest.mark.parametrize("length,accepted", [(200, True), (201, False)])
def test_tool_name_boundary_accepts_limit_and_rejects_overflow(service, length, accepted):
    run_id = create_run(service)
    tool = "x" * length
    port = port_for(service, run_id, allowed={tool})
    if accepted:
        assert port.dispatch("slot", tool, {})["status"] == "execute"
    else:
        with pytest.raises(InteractionError, match="tool exceeds"):
            port.dispatch("slot", tool, {})
        with service.repository.transaction(run_id) as tx:
            assert tx.executions() == []


def test_deleted_pending_requests_and_events_are_not_replayed(service):
    run_id = create_run(service)
    with service.repository.transaction(run_id, "tenant-a", "owner") as tx:
        request = service.request(tx, kind="CLARIFICATION", slot="slot", action_digest="0" * 64,
                                  payload={"question": "Continue?"})
        request.delete_flag = "Y"
    with service.repository.session_factory() as session:
        event = session.scalar(select(HumanEvent))
        event.delete_flag = "Y"
        event.updated_by = "system:cleanup"
    assert service.snapshot(run_id, "tenant-a", "owner")["requests"] == []
    assert service.repository.events(run_id) == []


def test_large_event_cursors_are_replayed(service):
    run_id = create_run(service)
    with service.repository.transaction(run_id) as tx:
        tx.run.event_seq = 2**31
        tx.emit({"type": "test", "content": {}})
    events = service.repository.events(run_id, after=2**31)
    assert [event["seq"] for event in events] == [2**31 + 1]


def test_invalid_execution_state_is_rejected_without_losing_started_receipt(service):
    run_id = create_run(service)
    port = port_for(service, run_id, allowed={"send"})
    port.dispatch("slot", "send", {})
    with pytest.raises(InteractionError, match="execution state"), service.repository.transaction(run_id) as tx:
        tx.execution("slot").status = "INVALID"
    with service.repository.transaction(run_id) as tx:
        assert tx.execution("slot").status == "STARTED"
