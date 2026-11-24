# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Discover covered source metadata without fetching bulk result bodies or trusting summaries."""

import json
from functools import partial

import pytest
from runtime.agentos.history_sources import discover_summary_sources
from runtime.agentos.prepared_run import _read_execution_result
from sqlalchemy import event, text
from test_conversation_history_stopped import history_db as history_db

from infrastructure.rdb import conversation_state
from nexent.core.agents.context.action_history import register_historical_results
from nexent.core.agents.context.execution_history import ExecutionHistory
from nexent.core.agents.context.models import ContextItem, ContextItemInput
from nexent.core.tools.read_execution_output_tool import ReadExecutionOutputTool


def native(kind, local="source", **changes):
    value = {"type": kind, "schema_version": 1, "runtime_mode": "native_agent", "agent_core": "jiuwen",
             "turn_id": "real-turn", "local_call_id": local, "tool_call_id": local,
             "provider_call_id": local, "invocation_id": None, "parent_call_id": None}
    if kind == "tool":
        value.update(tool_name="calculate", raw_arguments='{"page":17}', call_group_id=local,
                     call_index=0, call_count=1, source_protocol="model_native_fc")
    else:
        value.update(result="10335393", is_error=False)
    return json.dumps({**value, **changes})


@pytest.fixture
def sources(history_db, monkeypatch):
    module, message, unit = history_db
    monkeypatch.setattr(conversation_state, "get_db_session", module.get_db_session)
    with module.get_db_session() as session:
        session.execute(text("CREATE TABLE nexent.user_tenant_t (user_id TEXT, tenant_id TEXT, delete_flag TEXT)"))
        session.execute(text("INSERT INTO nexent.user_tenant_t VALUES ('owner','tenant','N')"))
        session.commit()
    message(1, "user", "Calculate page17")
    message(2, "assistant", "Completed page17")
    message(3, "user", "Later suffix")
    message(4, "assistant", "Known uncompressed suffix")
    message(5, "user", "Current request")
    message(6, "assistant", "Incomplete future", status="streaming")
    unit(10, 2, "tool", native("tool"), tool_call_id="source")
    unit(11, 2, "tool_result", native("tool_result"), tool_call_id="source")
    unit(12, 2, "execution_result", json.dumps({"content": "ORIGINAL_CODE_OUTPUT"}))
    unit(20, 4, "execution_result", json.dumps({"content": "KNOWN_SUFFIX"}))
    unit(30, 6, "execution_result", json.dumps({"content": "FUTURE"}))
    checkpoint = {"summary": {"markdown": "Wrong summarized page17 value:10033393"}, "covered_through_message_id": 2}
    unit(50, 2, "history_summary", json.dumps(checkpoint))
    return module, message, unit, checkpoint


def discover(offset=0, max_chars=4000, **scope):
    return discover_summary_sources(**{
        "user_id": "owner", "tenant_id": "tenant", "conversation_id": 1,
        "checkpoint_unit_id": 50, "covered_message_id": 2,
        "offset": offset, "max_chars": max_chars, **scope})


def test_wrong_summary_discovers_real_value_and_preserves_explicit_suffix_and_current_reads(sources):
    _, _, _, checkpoint = sources
    store = ExecutionHistory(read_conversation_result=partial(_read_execution_result, "owner", "tenant", 1),
        discover_summary_sources=partial(discover))
    item = ContextItem.from_input(ContextItemInput(id="summary", type="history_summary", content=checkpoint))
    register_historical_results([item], store, "owner-run")
    tool = ReadExecutionOutputTool(store, "owner-run", lambda: None)
    found = json.loads(tool.forward("summary"))
    assert found["eof"] and [row["output_ref"] for row in found["results"]] == [
        "message:2/unit-index:11", "message:2/unit-index:12"]
    assert found["results"][0]["tool_names"] == ["calculate"]
    assert "17" in found["results"][0]["arguments_preview"]
    assert "10335393" not in json.dumps(found) and "10033393" not in json.dumps(found)
    original = json.loads(tool.forward(found["results"][0]["output_ref"]))
    assert original["text"] == "10335393"
    assert json.loads(tool.forward("message:4/unit-index:20"))["text"] == "KNOWN_SUFFIX"
    key = store.register("owner-run", {"STDOUT": "CURRENT_RESULT"})
    store.bind_run(key, "a" * 32, 1)
    assert "CURRENT_RESULT" in json.loads(tool.forward("run:" + "a" * 32 + "/execution:1"))["text"]
    with pytest.raises(PermissionError):
        store.read("foreign-run", "summary")


@pytest.mark.parametrize("scope", [
    {"tenant_id": "other"}, {"user_id": "other"}, {"conversation_id": 2},
    {"checkpoint_unit_id": 999}, {"covered_message_id": 4}, {"covered_message_id": 6},
])
def test_discovery_never_expands_the_loaded_checkpoint_authority(sources, scope):
    with pytest.raises(PermissionError):
        discover(**scope)


def test_discovery_filters_child_deleted_unfinished_ambiguous_and_wrong_types(sources):
    module, _, unit, _ = sources
    unit(60, 2, "tool", native("tool", local="child", parent_call_id="parent"), tool_call_id="child")
    unit(61, 2, "tool_result", native("tool_result", local="child", parent_call_id="parent"), tool_call_id="child")
    unit(62, 2, "execution_result", '{"content":"deleted"}', deleted="Y")
    unit(63, 2, "execution_result", '{"content":"pending"}', status="streaming")
    unit(64, 2, "model_output_thinking", "PRIVATE_MODEL_TEXT")
    unit(65, 2, "tool", native("tool", local="ambiguous"), tool_call_id="ambiguous")
    unit(66, 2, "tool", native("tool", local="ambiguous"), tool_call_id="ambiguous")
    unit(67, 2, "tool_result", native("tool_result", local="ambiguous"), tool_call_id="ambiguous")
    unit(68, 2, "tool", "not-json", tool_call_id="bad")
    unit(69, 2, "tool_result", native("tool_result", local="bad"), tool_call_id="bad")
    assert [row["output_ref"] for row in discover()["results"]] == [
        "message:2/unit-index:11", "message:2/unit-index:12"]
    with module.get_db_session() as session:
        session.execute(text("UPDATE nexent.conversation_message_t SET status='stopped' WHERE message_id=2"))
        session.commit()
    with pytest.raises(PermissionError):
        discover()


def test_discovery_uses_one_candidate_query_and_does_not_select_result_bodies(sources):
    module, _, _, _ = sources
    with module.get_db_session() as session:
        engine = session.get_bind()
        session.execute(text("UPDATE nexent.conversation_message_unit_t SET unit_content=:body WHERE unit_id=11"),
                        {"body": native("tool_result", result="LARGE_BODY" * 100000)})
        session.commit()
    queries = []
    def record(_connection, _cursor, statement, _parameters, _context, _many):
        queries.append(statement)
    event.listen(engine, "before_cursor_execute", record)
    try:
        page = discover()
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert len(queries) == 2
    selected = queries[-1].split("FROM", 1)[0]
    assert "source_call.unit_content" in selected
    assert "conversation_message_unit_t.unit_content" not in selected
    assert "LARGE_BODY" not in json.dumps(page)


def test_source_pages_are_bounded_and_preserve_every_reference(sources):
    _, _, unit, _ = sources
    for index in range(100, 140):
        unit(index, 2, "execution_result", '{"content":"original"}')
    offset, refs = 0, []
    while True:
        page = discover(offset=offset, max_chars=700)
        assert len(json.dumps(page, ensure_ascii=False)) <= 700
        refs.extend(row["output_ref"] for row in page["results"])
        if page["eof"]:
            break
        assert page["next_offset"] > offset
        offset = page["next_offset"]
    assert len(refs) == len(set(refs)) == 42
    with pytest.raises(ValueError, match="Increase max_chars"):
        discover(max_chars=10)
