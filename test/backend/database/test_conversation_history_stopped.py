# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

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
    module = importlib.import_module("management.db.conversation.repository")
    engine = create_engine("sqlite://", poolclass=StaticPool)
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS nexent")
        connection.exec_driver_sql("CREATE TABLE nexent.conversation_record_t (conversation_id INTEGER PRIMARY KEY, created_by TEXT, delete_flag TEXT)")
        connection.exec_driver_sql("CREATE TABLE nexent.conversation_message_t (message_id INTEGER PRIMARY KEY, conversation_id INTEGER, message_index INTEGER, message_role TEXT, message_content TEXT, minio_files TEXT, status TEXT, delete_flag TEXT)")
        connection.exec_driver_sql("CREATE TABLE nexent.conversation_message_unit_t (unit_id INTEGER PRIMARY KEY, message_id INTEGER, conversation_id INTEGER, unit_index INTEGER, unit_type TEXT, unit_content TEXT, unit_status TEXT, delete_flag TEXT, tool_call_id TEXT, invocation_id TEXT)")
        connection.exec_driver_sql("INSERT INTO nexent.conversation_record_t VALUES (1, 'owner', 'N')")

    @contextmanager
    def session():
        with Session(engine) as current:
            yield current

    monkeypatch.setattr(module, "get_db_session", session)
    monkeypatch.setattr(module, "_get_user_tenant", lambda _: {"tenant_id": "tenant"})

    def message(mid, role, content, status="completed", files=None, deleted="N", index=None):
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO nexent.conversation_message_t VALUES (:id, 1, :idx, :role, :body, :files, :status, :deleted)"),
                               {"id": mid, "idx": mid if index is None else index, "role": role, "body": content, "files": json.dumps(files) if files else None, "status": status, "deleted": deleted})

    def unit(uid, mid, kind, content, status="completed", deleted="N", tool_call_id=None):
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO nexent.conversation_message_unit_t (unit_id, message_id, conversation_id, unit_index, unit_type, unit_content, unit_status, delete_flag, tool_call_id) VALUES (:id, :mid, 1, :id, :kind, :body, :status, :deleted, :tool_call_id)"),
                               {"id": uid, "mid": mid, "kind": kind, "body": content, "status": status, "deleted": deleted, "tool_call_id": tool_call_id})

    yield module, message, unit
    engine.dispose()


def test_followup_uses_latest_retry_once_and_preserves_same_text_turn(history_db):
    module, message, _ = history_db
    message(1, "user", "Same", index=0)
    message(2, "assistant", "First answer", index=1)
    message(10, "assistant", "Third answer", index=1)
    message(7, "assistant", "Second answer", index=1)
    message(20, "user", "Same", index=2)
    message(21, "assistant", "Independent repeated question answer", index=3)
    message(22, "user", "Next", index=4)
    turns = module.get_historical_context(1, 22, "owner", "tenant")["conversation_turns"]
    assert [turn["user_message_id"] for turn in turns] == [1, 20]
    assert [turn["assistant_final_answer"] for turn in turns] == ["Third answer", "Independent repeated question answer"]


@pytest.mark.parametrize("use_saved_message", [False, True], ids=["before-index", "saved-message"])
def test_historical_context_returns_the_exclusive_message_boundary(history_db, use_saved_message):
    module, message, _ = history_db
    message(10, "user", "Original request", index=0)
    message(20, "assistant", "What date should I use?", index=1)
    if use_saved_message:
        message(30, "user", "Friday", index=2)
        history = module.get_historical_context(1, 30, "owner", "tenant")
    else:
        history = module.get_historical_context(1, None, "owner", "tenant", before_message_index=2)
        message(30, "user", "Friday", index=2)
        assert module.get_historical_context(1, None, "owner", "tenant", before_message_index=2) == history

    assert history["current_user_message_index"] == 2
    assert [turn["assistant_final_answer"] for turn in history["conversation_turns"]] == ["What date should I use?"]


def test_historical_context_before_first_message_and_without_ownership(history_db):
    module, _, _ = history_db

    assert module.get_historical_context(1, None, "owner", "tenant", before_message_index=0) == {
        "history_summary": None, "conversation_turns": [], "current_user_message_index": 0,
    }
    assert module.get_historical_context(1, None, "different-owner", "tenant", before_message_index=0) is None


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
@pytest.mark.parametrize("by_index", [False, True], ids=["message-id", "index"])
def test_history_keeps_owner_and_tenant_boundaries(history_db, owner, tenant, by_index):
    module, message, _ = history_db
    message(1, "user", "Private task")
    message(2, "assistant", "Private output", "stopped")
    message(3, "user", "Next")
    if by_index:
        assert module.get_historical_context(1, None, owner, tenant, before_message_index=3) is None
    else:
        assert module.get_historical_context(1, 3, owner, tenant) is None


@pytest.mark.parametrize("by_index", [False, True], ids=["message-id", "index"])
def test_projection_is_bounded_and_excludes_deleted_or_future_rows(history_db, by_index):
    module, message, unit = history_db
    message(1, "user", "Task")
    message(2, "assistant", "", "stopped")
    if not by_index:
        message(30, "user", "Next", index=3)
    message(4, "assistant", "Future answer")
    message(5, "user", "Deleted", deleted="Y")
    unit(1, 2, "execution_logs", "x" * 20000)
    if by_index:
        result = module.get_historical_context(1, None, "owner", "tenant", before_message_index=3)
    else:
        result = module.get_historical_context(1, 30, "owner", "tenant")
    assert result["current_user_message_index"] == 3
    turns = result["conversation_turns"]
    assert len(turns) == 1
    assert len(turns[0]["assistant_final_answer"]) < 16100


def test_completed_history_keeps_only_persisted_execution_evidence(history_db):
    module, message, unit = history_db
    message(1, "user", "Use the old file", files=[{"name": "old.txt", "url": "s3://files/old.txt"}])
    message(2, "assistant", "Completed")
    message(3, "user", "Current task")
    unit(1, 2, "tool", '{"tool_name":"old_tool","tool_arguments":{"a":1}}')
    unit(2, 2, "execution_logs", "Saved result")
    unit(3, 2, "error", "Saved failure")
    unit(4, 2, "parse", "Never replay code")
    unit(5, 2, "execution_logs", "Not committed", status="streaming")
    unit(6, 2, "error", "Deleted error", deleted="Y")
    projected = module.get_historical_context(1, 3, "owner", "tenant")["conversation_turns"][0]
    records = projected["execution_records"]
    assert [record["record_type"] for record in records] == ["tool", "execution_logs", "error"]
    assert "Saved result" in str(records) and "Saved failure" in str(records)
    assert all(text not in str(records) for text in ["Never replay", "Not committed", "Deleted error"])
    assert "s3://files/old.txt" in projected["attachments"]


@pytest.mark.parametrize("boundary", ["message_id", "message_index"])
def test_history_returns_resolved_boundary_and_excludes_current_and_future_rows(history_db, boundary):
    module, message, _ = history_db
    message(11, "user", "Prior task", index=0)
    message(12, "assistant", "Prior answer", index=1)
    message(23, "user", "Current task", index=2)
    message(24, "assistant", "Future answer", index=3)
    args = {"current_user_message_id": 23 if boundary == "message_id" else None}
    if boundary == "message_index":
        args["before_message_index"] = 2

    result = module.get_historical_context(1, user_id="owner", tenant_id="tenant", **args)

    assert result["current_user_message_index"] == 2
    assert [turn["user_message"] for turn in result["conversation_turns"]] == ["Prior task"]
    assert [turn["assistant_final_answer"] for turn in result["conversation_turns"]] == ["Prior answer"]
    assert module.get_historical_context(1, user_id="other-owner", tenant_id="tenant", **args) is None



def test_native_history_facts_survive_authorized_database_and_prepared_roundtrip(history_db):
    from contracts.agentos import PreparedHistoryTurn
    from nexent.core.agents.context import ContextItem, ContextItemInput, ContextManager

    module, message, unit = history_db
    message(1, "user", "old request")
    message(2, "assistant", "finished")
    message(3, "user", "current")
    common = {"schema_version": 1, "runtime_mode": "native_agent", "agent_core": "jiuwen",
              "turn_id": "run-a", "local_call_id": "local", "tool_call_id": "local",
              "provider_call_id": "provider", "invocation_id": None}
    call = {**common, "type": "tool", "source_protocol": "model_native_fc", "call_group_id": "step-a",
            "call_index": 0, "call_count": 1, "tool_name": "lookup", "tool_arguments": {"id": 1}}
    result = {**common, "type": "tool_result", "result": "real error", "is_error": True}
    unit(1, 2, "tool", json.dumps(call), tool_call_id="local")
    unit(2, 2, "tool_result", json.dumps(result), tool_call_id="local")
    # A lookalike business result cannot satisfy the row identity binding.
    unit(3, 2, "tool_result", json.dumps(result), tool_call_id="another-local")
    turn = module.get_historical_context(1, 3, "owner", "tenant")["conversation_turns"][0]
    assert turn["execution_records"][0]["execution_event"]["name"] == "lookup"
    assert "execution_event" not in turn["execution_records"][2]
    prepared = PreparedHistoryTurn.model_validate({k: v for k, v in turn.items() if k != "attachments"})
    item = ContextItem.from_input(ContextItemInput(id="turn:1:2", type="conversation_turn",
                                                content=prepared.model_dump(exclude={"attachment_refs"})))
    messages = ContextManager(message_format="openai_chat_completions").build_context_messages([item])
    assert messages[1]["tool_calls"][0]["function"]["name"] == "lookup"
    assert messages[2] == {"role": "tool", "tool_call_id": "provider", "content": "real error"}
    assert "read_only" in str(messages[3])


def test_fix01_closed_action_preserves_raw_storage_and_authorized_roundtrip(history_db):
    from contracts.agentos import PreparedHistoryTurn
    from nexent.core.agents.context import ContextItem, ContextItemInput, ContextManager

    module, message, unit = history_db
    message(1, 'user', 'prior question')
    message(2, 'assistant', 'actual answer')
    message(3, 'user', 'new question')
    unit(1, 2, 'tool', json.dumps({'tool_name': 'write', 'tool_arguments': {'body': 'EXPANDED' * 12000}}))
    unit(2, 2, 'execution_logs', 'actual result')
    unit(3, 2, 'execution_result', json.dumps({
        'content': '<STDOUT>actual result</STDOUT>', 'covered_unit_indices': [1, 2],
        'model_action': {'schema_version': 1, 'agent_core': 'smolagents', 'dispatch_state': 'dispatched',
                         'step_number': 1, 'tool_calls': [{'id': 'python', 'name': 'python_interpreter',
                                                        'arguments': 'write(body=computed)'}]},
    }))
    turn = module.get_historical_context(1, 3, 'owner', 'tenant')['conversation_turns'][0]
    assert 'EXPANDED' in turn['execution_records'][0]['content']
    prepared = PreparedHistoryTurn.model_validate({k: v for k, v in turn.items() if k != 'attachments'})
    item = ContextItem.from_input(ContextItemInput(id='old', type='conversation_turn',
                                  content=prepared.model_dump(exclude={'attachment_refs'})))
    text = str(ContextManager(message_format='codeagent').build_context_messages([item]))
    assert 'write(body=computed)' in text and 'actual result' in text and 'EXPANDED' not in text
    assert 'message:2/unit-index:3' in text
    assert module.get_historical_context(1, 3, 'other-owner', 'tenant') is None



@pytest.mark.parametrize("body", [
    "ordinary accepted summary",
    "Saved <OUTPUT_REF>message:42/unit-index:12</OUTPUT_REF>",
    "Retired <OUTPUT_REF>message:41/user-message</OUTPUT_REF> structured source sha256:old /rows",
])
def test_legacy_checkpoint_extras_are_ignored_without_rewriting_rows_or_granting_sources(history_db, body):
    from contracts.agentos import PreparedHistoryCheckpoint
    from nexent.core.agents.context import ContextItemInput, ContextManager
    from nexent.core.agents.context.action_history import register_historical_results
    from nexent.core.agents.context.execution_history import ExecutionHistory

    module, message, unit = history_db
    message(41, "user", "covered task", index=0)
    message(42, "assistant", "covered answer", index=1)
    message(43, "user", "current task", index=2)
    raw = json.dumps({"summary": {"markdown": body}, "covered_through_message_id": 42,
        "structured_source_proofs": [{"source_ref": "message:41/user-message"}],
        "execution_sources": [{"message_id": 42, "unit_index": 12, "content": "private"}]})
    unit(11, 42, "history_summary", raw)
    unit(12, 42, "execution_result", json.dumps({"content": "<STDOUT>covered original</STDOUT>"}))
    loaded = module.get_historical_context(1, 43, "owner", "tenant")
    assert loaded['conversation_turns'] == []
    checkpoint = loaded['history_summary']
    assert checkpoint['summary'] == {'markdown': body}
    assert 'execution_sources' not in checkpoint and 'structured_source_proofs' not in checkpoint
    assert PreparedHistoryCheckpoint.model_validate(checkpoint).summary == {'markdown': body}
    store = ExecutionHistory(lambda *_: pytest.fail('No reference-based covered history lookup'))
    items = register_historical_results([ContextItemInput(id='checkpoint', type='history_summary', content=checkpoint)], store, 'new')
    assert body in str(ContextManager().build_context_messages(items))
    with pytest.raises(PermissionError):
        store.read('new', 'message:42/unit-index:12')
    with pytest.raises(ValueError):
        store.read('new', 'message:41/user-message')
    with module.get_db_session() as session:
        assert session.execute(text('SELECT unit_content FROM nexent.conversation_message_unit_t WHERE unit_id=11')).scalar_one() == raw
