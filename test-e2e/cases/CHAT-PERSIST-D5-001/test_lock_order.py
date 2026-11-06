# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Real PostgreSQL finalization/deletion contention in disposable schemas."""

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
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra/automation"))
from shared.postgres import apply_product_postgres_env, postgres_url

apply_product_postgres_env()

# Object storage is outside this database-locking boundary.
with patch(
    "nexent.storage.storage_client_factory.create_storage_client_from_config",
    return_value=MagicMock(),
), patch("nexent.storage.minio_config.MinIOStorageConfig.validate", lambda self: None):
    from management.db.conversation import repository as db
    from management.db.models import ConversationMessage, ConversationMessageUnit, ConversationRecord, ConversationSourceImage, ConversationSourceSearch

MODELS = (ConversationRecord, ConversationMessage, ConversationMessageUnit,
          ConversationSourceSearch, ConversationSourceImage)
pytestmark = [pytest.mark.case_id("CHAT-PERSIST-D5-001"), pytest.mark.stage("D5")]


class Contention:
    def __init__(self, engine):
        self.engine = engine
        self.actor = threading.local()
        self.pids = {}
        self.trace = []
        self.after_lock = None
        self.original_activity = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)

    @contextmanager
    def session(self):
        actor = getattr(self.actor, "name", "inspect")
        with Session(self.engine.execution_options(lock_actor=actor)) as session, session.begin():
            session.execute(text("SET LOCAL lock_timeout = '5s'"))
            session.execute(text("SET LOCAL statement_timeout = '10s'"))
            session.execute(text("SET LOCAL deadlock_timeout = '100ms'"))
            self.pids[actor] = session.scalar(text("SELECT pg_backend_pid()"))
            yield session

    def after_execute(self, connection, cursor, statement, parameters, context, many):
        actor = context.execution_options.get("lock_actor")
        sql = " ".join(statement.lower().split())
        if actor and ("for update" in sql or sql.startswith(("update ", "insert "))):
            self.trace.append((actor, sql))
            if self.after_lock:
                self.after_lock(actor, sql)

    def run(self, actor, function):
        self.actor.name = actor
        return function()

    def wait_for_blocking(self, waiter, blocker):
        deadline = monotonic() + 5
        while monotonic() < deadline:
            if waiter in self.pids and blocker in self.pids:
                with self.engine.connect() as connection:
                    blocking = connection.scalar(
                        text("SELECT pg_blocking_pids(:pid)"), {"pid": self.pids[waiter]},
                    )
                if self.pids[blocker] in blocking:
                    return
            threading.Event().wait(0.01)
        raise AssertionError(f"Expected {waiter} to wait for {blocker}'s database lock")

    @contextmanager
    def overlap(self, first, first_call, second, second_call, first_lock):
        acquired, release = threading.Event(), threading.Event()

        def gate(actor, sql):
            if actor == first and first_lock(sql) and not acquired.is_set():
                acquired.set()
                if not release.wait(5):
                    raise AssertionError("The diagnostic lock gate was not released")

        self.after_lock = gate
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                first_future = executor.submit(self.run, first, first_call)
                try:
                    assert acquired.wait(5), "First transaction did not acquire the expected conversation lock"
                    second_future = executor.submit(self.run, second, second_call)
                    self.wait_for_blocking(second, first)
                finally:
                    release.set()
                released_at = monotonic()
                yield first_future, second_future
                assert monotonic() - released_at < 15, "Concurrent transactions exceeded the completion bound"
        finally:
            release.set()
            self.after_lock = None

    def finalize(self, conversation_id=1, terminal="completed"):
        return db.persist_assistant_run_batch(
            message_id=conversation_id, conversation_id=conversation_id,
            message_content="Final answer", terminal_status=terminal,
            message_units=[{"unit_index": 0, "unit_type": "final_answer", "unit_content": "Final answer"}],
            search_records=[], image_urls=[], skill_files=[], automation_proposals=[],
            user_id="owner", tenant_id="tenant",
        )

    def delete(self, mode):
        return db.delete_conversation(1, "owner") if mode == "single" else db.delete_conversations_batch([1], "owner")

    def snapshot(self, identity):
        with self.session() as session:
            conversation = session.get(ConversationRecord, identity)
            message = session.get(ConversationMessage, identity)
            return {
                "conversation_deleted": conversation.delete_flag,
                "activity": conversation.last_activity_time,
                "message_deleted": message.delete_flag,
                "status": message.status,
                "content": message.message_content,
                "children": {
                    model.__tablename__: list(session.execute(select(model.delete_flag).where(
                        model.conversation_id == identity,
                    )).scalars())
                    for model in MODELS[2:]
                },
            }


@pytest.fixture
def contention(monkeypatch):
    schema = "test_persist_lock_" + uuid4().hex
    engine = create_engine(postgres_url()).execution_options(schema_translate_map={"nexent": schema})
    state = Contention(engine)
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
        for model in MODELS:
            model.__table__.create(connection)
    try:
        with state.session() as session:
            for identity, owner in ((1, "owner"), (2, "owner"), (3, "other")):
                audit = {"created_by": owner, "updated_by": owner, "delete_flag": "N"}
                session.add(ConversationRecord(
                    conversation_id=identity, conversation_title=f"Isolated history {identity}",
                    last_activity_time=state.original_activity, **audit,
                ))
                session.add(ConversationMessage(
                    message_id=identity, conversation_id=identity, message_index=1,
                    message_role="assistant", message_content="", status="streaming", **audit,
                ))
                session.add(ConversationMessageUnit(
                    unit_id=identity + 10, conversation_id=identity, message_id=identity,
                    unit_index=10, unit_type="tool_response", unit_content="existing", **audit,
                ))
                session.add(ConversationSourceSearch(
                    search_id=identity, conversation_id=identity, message_id=identity,
                    unit_id=identity + 10, source_title="existing", **audit,
                ))
                session.add(ConversationSourceImage(
                    image_id=identity, conversation_id=identity, message_id=identity,
                    image_url="https://example.com/existing.png", **audit,
                ))
        monkeypatch.setattr(db, "get_db_session", state.session)
        event.listen(engine, "after_cursor_execute", state.after_execute)
        yield state
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()


def conversation_lock(sql):
    return "conversation_record_t" in sql and "for update" in sql


@pytest.mark.parametrize("mode", ["single", "batch"])
@pytest.mark.parametrize("terminal", ["completed", "stopped"])
def test_finalization_first_serializes_with_delete(contention, mode, terminal):
    other = contention.snapshot(3)
    with contention.overlap(
        "persist", lambda: contention.finalize(terminal=terminal),
        "delete", lambda: contention.delete(mode), conversation_lock,
    ) as (persistence, deletion):
        assert 0 in persistence.result(timeout=15)
        assert deletion.result(timeout=15) == (True if mode == "single" else [1])

    result = contention.snapshot(1)
    assert result["conversation_deleted"] == result["message_deleted"] == "Y"
    assert result["status"] == terminal and result["content"] == "Final answer"
    assert result["activity"] > contention.original_activity
    assert result["children"]["conversation_message_unit_t"] == ["Y", "Y"]
    assert all(flags and set(flags) == {"Y"} for flags in result["children"].values())
    assert contention.snapshot(3) == other


@pytest.mark.parametrize("mode", ["single", "batch"])
def test_delete_first_rejects_finalization_without_post_delete_writes(contention, mode):
    with contention.overlap(
        "delete", lambda: contention.delete(mode), "persist", contention.finalize,
        lambda sql: sql.startswith("update ") and "conversation_record_t" in sql,
    ) as (deletion, persistence):
        assert deletion.result(timeout=15) == (True if mode == "single" else [1])
        with pytest.raises(ValueError, match="Conversation does not exist or is not accessible"):
            persistence.result(timeout=15)

    result = contention.snapshot(1)
    assert result["conversation_deleted"] == result["message_deleted"] == "Y"
    assert result["status"] == "streaming" and result["content"] == ""
    assert result["activity"] == contention.original_activity
    assert all(flags == ["Y"] for flags in result["children"].values())
    assert not any(actor == "persist" and sql.startswith(("update ", "insert ")) for actor, sql in contention.trace)


def test_foreign_conversation_rejects_finalization_without_mutation(contention):
    before = contention.snapshot(3)
    with pytest.raises(ValueError, match="Conversation does not exist or is not accessible"):
        contention.finalize(3)
    assert contention.snapshot(3) == before


def test_reversed_overlapping_batches_lock_owned_histories_in_ascending_order(contention):
    foreign = contention.snapshot(3)
    with contention.overlap(
        "delete-a", lambda: db.delete_conversations_batch([2, 1, 3], "owner"),
        "delete-b", lambda: db.delete_conversations_batch([1, 2, 3], "owner"),
        conversation_lock,
    ) as (first, second):
        assert first.result(timeout=15) == [1, 2]
        assert second.result(timeout=15) == []

    locks = [sql for actor, sql in contention.trace if conversation_lock(sql)]
    assert len(locks) == 2
    assert all("order by" in sql and "conversation_id asc for update" in sql for sql in locks)
    for identity in (1, 2):
        result = contention.snapshot(identity)
        assert result["conversation_deleted"] == result["message_deleted"] == "Y"
        assert all(flags == ["Y"] for flags in result["children"].values())
    assert contention.snapshot(3) == foreign
