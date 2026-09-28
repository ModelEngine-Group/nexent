"""Execute the history projection against isolated relational rows."""
import importlib
import json
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


@pytest.fixture
def history_db(monkeypatch):
    monkeypatch.setattr("nexent.storage.storage_client_factory.create_storage_client_from_config", lambda *_: MagicMock())
    module = importlib.import_module("database.conversation_db")
    engine = create_engine("sqlite://", poolclass=StaticPool)
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS nexent")
        connection.exec_driver_sql("CREATE TABLE nexent.conversation_record_t (conversation_id INTEGER PRIMARY KEY, created_by TEXT, delete_flag TEXT)")
        connection.exec_driver_sql("CREATE TABLE nexent.conversation_message_t (message_id INTEGER PRIMARY KEY, conversation_id INTEGER, message_index INTEGER, message_role TEXT, message_content TEXT, minio_files TEXT, status TEXT, delete_flag TEXT)")
        connection.exec_driver_sql("CREATE TABLE nexent.conversation_message_unit_t (unit_id INTEGER PRIMARY KEY, message_id INTEGER, conversation_id INTEGER, unit_index INTEGER, unit_type TEXT, unit_content TEXT, unit_status TEXT, delete_flag TEXT)")
        connection.exec_driver_sql("INSERT INTO nexent.conversation_record_t VALUES (1, 'owner', 'N')")

    @contextmanager
    def session():
        with Session(engine) as current:
            yield current

    monkeypatch.setattr(module, "get_db_session", session)
    monkeypatch.setattr(module, "_get_user_tenant", lambda _: {"tenant_id": "tenant"})

    def message(mid, role, content, status="completed", files=None, deleted="N"):
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO nexent.conversation_message_t VALUES (:id, 1, :id, :role, :body, :files, :status, :deleted)"),
                               {"id": mid, "role": role, "body": content, "files": json.dumps(files) if files else None, "status": status, "deleted": deleted})

    def unit(uid, mid, kind, content, status="completed", deleted="N"):
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO nexent.conversation_message_unit_t VALUES (:id, :mid, 1, :id, :kind, :body, :status, :deleted)"),
                               {"id": uid, "mid": mid, "kind": kind, "body": content, "status": status, "deleted": deleted})

    yield module, message, unit
    engine.dispose()


def test_stop_followup_keeps_original_task_and_saved_results(history_db):
    module, message, _ = history_db
    message(1, "user", "Analyze all sales")
    message(2, "assistant", "Fetched 23 rows", "stopped")
    message(3, "user", "Only East China")
    turns = module.get_historical_context(1, 3, "owner", "tenant")["conversation_turns"]
    assert len(turns) == 1
    assert turns[0]["user_message"] == "Analyze all sales"
    assert turns[0]["assistant_final_answer"] == "上一轮已由用户停止，以下内容为已保存的部分结果。\nFetched 23 rows"


def test_empty_stopped_body_uses_only_saved_logs_and_file_references(history_db):
    module, message, unit = history_db
    message(1, "user", "Analyze sales")
    message(2, "assistant", "<user_break>", "stopped", files=[{"url": "/nexent/result.csv"}])
    message(3, "user", "Continue")
    unit(1, 2, "tool", "unconfirmed tool started")
    unit(2, 2, "parse", "delete_everything()")
    unit(3, 2, "execution_logs", "Collected 23 rows")
    unit(4, 2, "execution_logs", "uncommitted", "streaming")
    unit(5, 2, "execution_logs", "deleted log", deleted="Y")
    answer = module.get_historical_context(1, 3, "owner", "tenant")["conversation_turns"][0]["assistant_final_answer"]
    assert "Collected 23 rows" in answer and "/nexent/result.csv" in answer
    assert all(value not in answer for value in ["unconfirmed", "delete_everything", "uncommitted", "deleted log", "<user_break>"])


def test_orphan_user_is_preserved_and_can_enter_context(history_db):
    from nexent.core.agents.context import ContextItemInput
    module, message, _ = history_db
    message(1, "user", "Original task")
    message(2, "user", "Follow-up task")
    message(3, "assistant", "Done")
    message(4, "user", "Next query")
    turns = module.get_historical_context(1, 4, "owner", "tenant")["conversation_turns"]
    assert [turn["user_message"] for turn in turns] == ["Original task", "Follow-up task"]
    assert turns[0]["assistant_final_answer"] == "该轮未生成有效回复。"
    assert turns[0]["assistant_message_id"] == -1
    assert ContextItemInput(id="turn:1", type="conversation_turn", content=turns[0])


@pytest.mark.parametrize("owner,tenant", [("different-owner", "tenant"), ("owner", "other-tenant")])
def test_history_keeps_owner_and_tenant_boundaries(history_db, owner, tenant):
    module, message, _ = history_db
    message(1, "user", "Private task")
    message(2, "assistant", "Private output", "stopped")
    message(3, "user", "Next")
    assert module.get_historical_context(1, 3, owner, tenant) is None


def test_projection_is_bounded_and_excludes_deleted_or_future_rows(history_db):
    module, message, unit = history_db
    message(1, "user", "Task")
    message(2, "assistant", "", "stopped")
    message(3, "user", "Next")
    message(4, "assistant", "Future answer")
    message(5, "user", "Deleted", deleted="Y")
    unit(1, 2, "execution_logs", "x" * 20000)
    turns = module.get_historical_context(1, 3, "owner", "tenant")["conversation_turns"]
    assert len(turns) == 1
    assert len(turns[0]["assistant_final_answer"]) < 16100
