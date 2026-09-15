"""Real PostgreSQL regression tests for HITL schema, locks and audit contracts.

Use the standalone test schema snapshot and opt-in hitl_test fixture.
These tests validate the persistence contract, not versioned deployment SQL.
Never point the fixture at a business database.
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from sqlalchemy import inspect, select, text

from database.db_models import (
    HumanEvent,
    HumanExecution,
    HumanRequest,
    HumanRun,
    TableBase,
)
from services.human_interaction.models import InteractionError
from test.backend.services import test_human_interaction as hitl_support
from test.backend.services.test_human_interaction import (
    create_run,
    decide_pending,
    port_for,
)

service = hitl_support.service


MODELS = (HumanRun, HumanRequest, HumanExecution, HumanEvent)


def test_real_schema_matches_models_and_all_columns_have_comments(service):
    with service.repository.session_factory() as session:
        schema = inspect(session.connection())
        for model in MODELS:
            assert issubclass(model, TableBase)
            table = model.__table__
            columns = {item["name"]: item for item in schema.get_columns(table.name, schema="nexent")}
            assert set(columns) == set(table.columns.keys())
            pk = schema.get_pk_constraint(table.name, schema="nexent")["constrained_columns"]
            assert len(pk) == 1
            assert str(columns[pk[0]]["type"]) == "INTEGER"
            assert not schema.get_foreign_keys(table.name, schema="nexent")
            assert not schema.get_check_constraints(table.name, schema="nexent")
            assert not schema.get_unique_constraints(table.name, schema="nexent")
            indexes = schema.get_indexes(table.name, schema="nexent")
            assert {item["name"] for item in indexes} == {item.name for item in table.indexes}
            assert all(not item["unique"] for item in indexes)
            for name, column in columns.items():
                assert column["comment"] == table.c[name].comment
                assert column["comment"]
                assert column["nullable"] == table.c[name].nullable
                assert column["type"].compile(dialect=session.bind.dialect) == table.c[name].type.compile(
                    dialect=session.bind.dialect)


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


def test_pending_request_uniqueness_survives_removal_of_unique_index(service):
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


def test_audit_tracks_user_scheduler_receipt_and_raw_sql_updates(service):
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
    with service.repository.session_factory() as session:
        session.execute(text("UPDATE nexent.human_run_t SET lock_owner = 'raw-worker', updated_by = 'system:raw', "
                             "create_time = '2000-01-01', created_by = 'bad-creator' WHERE run_id = :run"), {"run": run_id})
    with service.repository.transaction(run_id) as tx:
        assert tx.run.created_by == "owner" and tx.run.create_time == created_at
        assert tx.run.updated_by == "system:raw"


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
        session.execute(text("INSERT INTO nexent.conversation_record_t VALUES "
                             "(8, 'owner', 'N'), (9, 'owner', 'N'), (10, 'owner', 'N')"))
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


def test_new_model_metadata_emits_comments_and_jsonb_without_legacy_base_changes():
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.schema import SetColumnComment

    assert isinstance(HumanEvent.payload.type, JSONB)
    assert TableBase.create_time.comment is None
    for model in MODELS:
        for column in model.__table__.columns:
            ddl = str(SetColumnComment(column).compile(dialect=postgresql.dialect()))
            assert "COMMENT ON COLUMN nexent.human_" in ddl
            assert column.comment and column.comment.replace("'", "''") in ddl


def test_representative_query_plans_use_non_unique_indexes(service):
    with service.repository.session_factory() as session:
        session.execute(text("""
            INSERT INTO nexent.human_run_t (run_id, tenant_id, user_id, conversation_id, status,
                request_payload, created_by, updated_by)
            SELECT '00000000-0000-0000-0000-' || lpad(i::text, 12, '0'), 'tenant-a', 'owner', i,
                   CASE WHEN i = 5000 THEN 'READY' ELSE 'COMPLETED' END, 'opaque-test', 'owner', 'owner'
            FROM generate_series(1, 5000) i;
            INSERT INTO nexent.human_event_t (run_record_id, seq, payload, created_by, updated_by)
            SELECT run_record_id, n, '{"type":"test","content":{}}'::jsonb, 'owner', 'owner'
            FROM nexent.human_run_t CROSS JOIN generate_series(1, 10) n;
            ANALYZE nexent.human_run_t;
            ANALYZE nexent.human_event_t;
        """))
        queries = [
            (("SELECT run_id FROM nexent.human_run_t WHERE tenant_id='tenant-a' AND user_id='owner' "
             "AND conversation_id=5000 AND delete_flag='N' ORDER BY create_time DESC, run_record_id DESC LIMIT 1"),
             {"human_run_conversation_idx"}),
            (("SELECT run_id FROM nexent.human_run_t WHERE delete_flag='N' AND "
             "(status='READY' OR (status='RUNNING' AND lock_until < now())) AND "
             "(lock_until IS NULL OR lock_until < now()) ORDER BY create_time LIMIT 10 FOR UPDATE SKIP LOCKED"),
             {"human_run_claim_idx"}),
            (("SELECT e.seq FROM nexent.human_event_t e JOIN nexent.human_run_t r "
             "ON e.run_record_id=r.run_record_id WHERE r.run_id='00000000-0000-0000-0000-000000005000' "
             "AND r.delete_flag='N' AND e.delete_flag='N' AND e.seq>5 ORDER BY e.seq LIMIT 200"),
             {"human_event_replay_idx", "human_run_public_id_idx"}),
        ]
        for query, expected in queries:
            plan = session.execute(text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query)).scalar_one()[0]
            nodes = [plan["Plan"]]
            indexes = set()
            while nodes:
                node = nodes.pop()
                indexes.add(node.get("Index Name"))
                nodes.extend(node.get("Plans", []))
            assert expected <= indexes


def test_raw_insert_audit_defaults_are_utc_even_in_a_non_utc_session(service):
    from datetime import datetime, timezone

    with service.repository.session_factory() as session:
        session.execute(text("SET LOCAL TIME ZONE 'Asia/Shanghai'"))
        created = session.execute(text("""
            INSERT INTO nexent.human_run_t (run_id, tenant_id, user_id, conversation_id, status,
                request_payload, created_by, updated_by)
            VALUES ('timezone-test', 'tenant-a', 'owner', 7, 'READY', 'opaque', 'owner', 'owner')
            RETURNING create_time
        """)).scalar_one()
        assert abs((datetime.now(timezone.utc).replace(tzinfo=None) - created).total_seconds()) < 5


def test_bigint_event_cursors_remain_compatible_with_int4_record_keys(service):
    run_id = create_run(service)
    with service.repository.transaction(run_id) as tx:
        tx.run.event_seq = 2**31
        tx.emit({"type": "test", "content": {}})
    events = service.repository.events(run_id, after=2**31)
    assert [event["seq"] for event in events] == [2**31 + 1]
    with service.repository.session_factory() as session:
        event = session.scalar(select(HumanEvent))
        assert 0 < event.event_id < 2**31


def test_invalid_execution_state_is_rejected_without_losing_started_receipt(service):
    run_id = create_run(service)
    port = port_for(service, run_id, allowed={"send"})
    port.dispatch("slot", "send", {})
    with pytest.raises(InteractionError, match="execution state"), service.repository.transaction(run_id) as tx:
        tx.execution("slot").status = "INVALID"
    with service.repository.transaction(run_id) as tx:
        assert tx.execution("slot").status == "STARTED"


def test_repeated_schema_creation_preserves_existing_objects_and_rows(service):
    run_id = create_run(service)
    schema_sql = (Path(__file__).parent / "fixtures/human_interaction_schema.sql").read_text()
    catalog_queries = [
        "SELECT oid, relname, relkind FROM pg_class WHERE relnamespace = 'nexent'::regnamespace ORDER BY oid",
        ("SELECT oid, prosrc FROM pg_proc WHERE oid = to_regprocedure('nexent.human_interaction_audit_timestamp()')"),
        (
            "SELECT oid, tgrelid, tgname, tgenabled, pg_get_triggerdef(oid) FROM pg_trigger "
            "WHERE tgrelid IN (SELECT oid FROM pg_class WHERE relnamespace = 'nexent'::regnamespace) ORDER BY oid"
        ),
        "SELECT last_value, is_called FROM nexent.human_run_t_run_record_id_seq",
        "SELECT * FROM nexent.human_run_t ORDER BY run_record_id",
    ]
    with service.repository.session_factory() as session:
        # An existing function body and trigger state must survive a repeated run.
        session.execute(
            text("""
            CREATE OR REPLACE FUNCTION nexent.human_interaction_audit_timestamp()
            RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                -- Existing function definition must be preserved.
                RETURN NEW;
            END;
            $$;
            ALTER TABLE nexent.human_run_t DISABLE TRIGGER human_audit_timestamp;
        """)
        )
        before = [session.execute(text(query)).all() for query in catalog_queries]
        session.execute(text(schema_sql))
        session.execute(text(schema_sql))
        after = [session.execute(text(query)).all() for query in catalog_queries]
        assert after == before
    assert service.snapshot(run_id, "tenant-a", "owner")["status"] == "READY"
