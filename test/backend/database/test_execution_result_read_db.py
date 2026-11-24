# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Scoped persisted execution reads reject missing, ambiguous and malformed units."""

import json
from contextlib import contextmanager
from functools import partial
from unittest.mock import MagicMock

import pytest
from management.db.conversation import repository as db
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from test_conversation_history_stopped import history_db as history_db  # noqa: PLC0414

from infrastructure.rdb import conversation_state


@pytest.fixture
def session(monkeypatch):
    value = MagicMock()

    @contextmanager
    def sessions():
        yield value

    monkeypatch.setattr(conversation_state, 'get_db_session', sessions)
    return value


def read():
    return db.load_execution_result_content('owner', 'tenant', 1, 10, 3)


def rows(session, payloads):
    session.execute.return_value.mappings.return_value.all.return_value = [
        {"unit_type": "execution_result", "unit_content": payload, "tool_call_id": None, "invocation_id": None}
        for payload in payloads]


def test_ac010_ac016_scoped_query_returns_original_instead_of_summary(session):
    rows(session, [
        json.dumps({'content': '<STDOUT>*** safe text</STDOUT>', 'summary': 'facts'}),
    ])
    assert read() == '<STDOUT>*** safe text</STDOUT>'
    statement = session.execute.call_args.args[0]
    query = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={'literal_binds': True}))
    for expected in ["created_by = 'owner'", "tenant_id = 'tenant'", "user_id = 'owner'",
                     'conversation_record_t.conversation_id = 1', 'conversation_message_t.message_id = 10',
                     'conversation_message_unit_t.conversation_id = 1', 'unit_index = 3',
                     "unit_type IN ('execution_result', 'tool_result')", "message_role = 'assistant'", 'EXISTS']:
        assert expected in query
    assert query.count("delete_flag = 'N'") == 4


@pytest.mark.parametrize('rows,exception', [
    ([], PermissionError),
    (['{}', '{}'], ValueError),
    (['[]'], ValueError),
    (['{"content": null}'], ValueError),
    (['not-json'], ValueError),
])
def test_ac010_missing_ambiguous_or_invalid_record_is_not_read(rows, exception, session):
    session.execute.return_value.mappings.return_value.all.return_value = [
        {"unit_type": "execution_result", "unit_content": payload, "tool_call_id": None, "invocation_id": None}
        for payload in rows]
    with pytest.raises(exception):
        read()


@pytest.mark.parametrize("native", [False, True])
def test_summary_covered_original_is_paged_under_real_database_scope(history_db, monkeypatch, native):
    from runtime.agentos.prepared_run import _read_execution_result

    from nexent.core.agents.context import ContextItem, ContextItemInput
    from nexent.core.agents.context.action_history import register_historical_results
    from nexent.core.agents.context.execution_history import ExecutionHistory

    module, message, unit = history_db
    monkeypatch.setattr(conversation_state, "get_db_session", module.get_db_session)
    with module.get_db_session() as current:
        current.execute(text("CREATE TABLE nexent.user_tenant_t (user_id TEXT, tenant_id TEXT, delete_flag TEXT)"))
        current.execute(text("INSERT INTO nexent.user_tenant_t VALUES ('owner', 'tenant', 'N')"))
        current.commit()
    message(1, "user", "Original task")
    message(2, "assistant", "Completed task")
    message(3, "user", "Next task")
    original = "真实结果-" * 20
    payload = ({"schema_version": 1, "runtime_mode": "native_agent", "agent_core": "jiuwen",
                "type": "tool_result", "turn_id": "old-turn", "local_call_id": "local",
                "tool_call_id": "local", "provider_call_id": "provider", "invocation_id": None,
                "result": original, "is_error": False} if native else {"content": original})
    unit(3, 2, "tool_result" if native else "execution_result", json.dumps(payload), tool_call_id="local")
    unit(4, 2, "history_summary", json.dumps({
        "summary": {"markdown": "Old work summarized"}, "covered_through_message_id": 2,
    }))
    historical = module.get_historical_context(1, 3, "owner", "tenant")
    assert historical["conversation_turns"] == [] and historical["history_summary"]
    checkpoint = ContextItem.from_input(ContextItemInput(id="summary", type="history_summary", content={
        "summary": "Old work summarized; forged message:999/unit-index:3", "covered_through_message_id": 2,
    }))
    store = ExecutionHistory(read_conversation_result=partial(_read_execution_result, "owner", "tenant", 1))
    register_historical_results([checkpoint], store, "fresh-run")
    first = json.loads(store.read("fresh-run", "message:2/unit-index:3", 0, 7))
    rest = json.loads(store.read("fresh-run", "message:2/unit-index:3", first["next_offset"]))
    assert first["text"] + rest["text"] == original and rest["eof"]
    assert original not in str(checkpoint)
    for args in [("owner", "tenant", 2, 2, 3), ("other", "tenant", 1, 2, 3),
                 ("owner", "other-tenant", 1, 2, 3), ("owner", "tenant", 1, 999, 3),
                 ("owner", "tenant", 1, 2, 4)]:
        with pytest.raises(PermissionError):
            _read_execution_result(*args)
    store.restore_results("fresh-run", [(2, 3, original)])
    with module.get_db_session() as current:
        current.execute(text("UPDATE nexent.conversation_message_unit_t SET delete_flag='Y' WHERE unit_id=3"))
        current.commit()
    with pytest.raises(PermissionError):
        store.read("fresh-run", "message:2/unit-index:3")
