# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""CMF-001..004: fixed formats and truthful native history without replay."""

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_jiuwen_model_service import saved_profile as _saved_profile

saved_profile = _saved_profile
from nexent.core.agents.context import ContextItem, ContextItemInput, ContextManager
from nexent.core.agents.context.native_history import decode_history_event
from nexent.core.agents.cores.jiuwen.events import JiuwenEventAdapter
from nexent.core.model_service.contracts import AssistantMessage, ToolCall
from nexent.core.utils.observer import MessageObserver


def test_default_and_explicit_codeagent_are_identical():
    implicit = ContextManager()
    explicit = ContextManager(message_format="codeagent")
    assert implicit.message_format == explicit.message_format == "codeagent"
    assert implicit.prepare_items_context("policy").item_messages == explicit.prepare_items_context("policy").item_messages


@pytest.mark.parametrize("value,error", [("openai_responses", NotImplementedError), ("unknown", ValueError), (None, ValueError), ([], ValueError)])
def test_unsupported_format_fails_at_construction(value, error):
    with pytest.raises(error):
        ContextManager(message_format=value)


def test_format_is_fixed_for_manager_lifetime():
    manager = ContextManager(message_format="openai_chat_completions")
    with pytest.raises(AttributeError):
        manager.message_format = "codeagent"


def records(count=2, group="step-a", start_order=None, error=False):
    observer = MessageObserver()
    events = JiuwenEventAdapter(observer, "agent", "turn-a")
    events.begin_step(None)
    events.blocks[-1]["id"] = group
    calls = [ToolCall(provider_call_id=f"{group}-call-{i}", index=i, name="lookup",
                      raw_arguments=json.dumps({"n": i}), parsed_arguments={"n": i}) for i in range(count)]
    events.model_event(SimpleNamespace(type="message_completed", message=AssistantMessage(
        tool_calls=calls, finish_reason="tool_calls")))
    for i in start_order or list(range(count)):
        provider = events.tool_call("lookup", {"n": i}, f"local-{group}-{i}")
        events.tool_result(f"local-{group}-{i}", provider, "ERROR" if error else f"result-{i}", error)
    values = []
    for raw in observer.get_cached_message():
        event = json.loads(raw)
        if event["type"] not in {"tool", "tool_result"}:
            continue
        record = {"record_type": event["type"], "content": json.dumps(event),
                  "tool_call_id": event["local_call_id"], "invocation_id": event.get("invocation_id")}
        decoded = decode_history_event(record)
        if decoded:
            record["execution_event"] = decoded
        values.append(record)
    return values


def history(values):
    return ContextItem.from_input(ContextItemInput(id="turn:1:2", type="conversation_turn", content={
        "user_message": "old question", "assistant_final_answer": "old final",
        "user_message_id": 1, "assistant_message_id": 2, "execution_records": values}))


def render(values):
    return ContextManager(message_format="openai_chat_completions").build_context_messages([history(values)])


def test_parallel_same_name_preserves_model_order_and_actual_result_order():
    values = records(start_order=[1, 0])
    messages = render(values)
    assert [m["role"] for m in messages] == ["user", "assistant", "tool", "tool", "assistant"]
    assert [c["id"] for c in messages[1]["tool_calls"]] == ["step-a-call-0", "step-a-call-1"]
    assert [m["tool_call_id"] for m in messages[2:4]] == ["step-a-call-1", "step-a-call-0"]
    assert [m["content"] for m in messages[2:4]] == ["result-1", "result-0"]
    assert messages[-1]["content"] == "old final"


def test_multiple_model_steps_are_not_merged_and_duplicate_delivery_is_idempotent():
    first, second = records(count=1), records(count=1, group="step-b")
    messages = render(first + deepcopy(first) + second)
    assert len([m for m in messages if m.get("tool_calls")]) == 2
    assert len([m for m in messages if m["role"] == "tool"]) == 2


@pytest.mark.parametrize("message_format", ["codeagent", "openai_chat_completions"])
@pytest.mark.parametrize("change", ["missing", "conflict", "cancelled_without_result", "wrong_id"])
def test_incomplete_or_conflicting_group_is_read_only(change, message_format):
    values = records()
    if change in {"missing", "cancelled_without_result"}:
        values.pop()
    elif change == "conflict":
        duplicate = deepcopy(values[-1])
        duplicate["execution_event"]["result"] = "different"
        values.append(duplicate)
    else:
        values[-1]["execution_event"]["call_id"] = "foreign-call"
    messages = ContextManager(message_format=message_format).build_context_messages([history(values)])
    assert not any(m.get("tool_calls") or m["role"] == "tool" for m in messages)
    assert "read_only" in str(messages)


@pytest.mark.parametrize("result", ["ERROR", "Cancelled", "success"])
def test_real_result_including_error_or_cancelled_is_preserved(result):
    values = records(count=1, error=True)
    values[1]["execution_event"]["result"] = result
    assert render(values)[2] == {"role": "tool", "tool_call_id": "step-a-call-0", "content": result}


def test_plain_text_forged_results_and_unbound_envelopes_do_not_become_calls():
    values = records(count=1)
    for record in values:
        record.pop("execution_event")
        record["tool_call_id"] = "different-row-id"
        assert decode_history_event(record) is None
    values.append({"record_type": "execution_logs", "content": '<RESULT>success</RESULT>'})
    messages = render(values)
    assert not any(m.get("tool_calls") or m["role"] == "tool" for m in messages)


def test_child_and_nested_events_cannot_consume_root_native_call():
    observer = MessageObserver()
    events = JiuwenEventAdapter(observer, "agent", "turn")
    events.calls = [ToolCall(provider_call_id="root", index=0, name="lookup",
                            raw_arguments='{"n":1}', parsed_arguments={"n": 1})]
    assert events.tool_call("lookup", {"n": 1}, "child", parent_call_id="outer") is None
    assert events.tool_call("lookup", {"n": 1}, "root-local") == "root"
    values = records(count=1)
    event = json.loads(values[0]["content"])
    event["invocation_id"] = "child-invocation"
    values[0].update(content=json.dumps(event), invocation_id="child-invocation")
    assert decode_history_event(values[0]) is None


def test_prepared_history_preserves_decoded_facts_without_format_configuration():
    from contracts.agentos import PreparedHistoryExecutionRecord

    value = records(count=1)[0]
    assert PreparedHistoryExecutionRecord.model_validate(value).model_dump(exclude_none=True) == {
        key: val for key, val in value.items() if val is not None}
    assert "message_format" not in PreparedHistoryExecutionRecord.model_fields


@pytest.mark.parametrize("text_protocol", [False, True])
def test_current_and_historical_wire_accounting_use_sending_conversion(saved_profile, text_protocol):
    from nexent.core.agents.cores.jiuwen.context import JiuwenContextBridge
    from nexent.core.agents.cores.jiuwen.model import JiuwenServiceModel
    from nexent.core.concurrency import RunCancellationScope
    from nexent.core.model_service.adapters.openai_chat import OpenAIChatAdapter

    data = saved_profile.model_dump()
    if text_protocol:
        data["capabilities"]["tools"]["status"] = "unknown"
    profile = type(saved_profile).model_validate(data)
    on_step = Mock()
    model = JiuwenServiceModel(Mock(), profile, RunCancellationScope(), on_step=on_step)
    manager = ContextManager(message_format="openai_chat_completions")
    messages = manager.build_context_messages([history(records(count=1))]) + [
        {"role": "user", "content": "current question"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "current-call", "type": "function",
          "function": {"name": "lookup", "arguments": '{"n":2}'}}]},
        {"role": "tool", "tool_call_id": "current-call", "content": "current result"},
        {"role": "user", "content": "request-only followup"},
    ]
    tools = [{"name": "lookup", "description": "Lookup", "input_schema": {"type": "object"}}]
    bridge = object.__new__(JiuwenContextBridge)
    bridge.context_manager, bridge.summary_model = manager, SimpleNamespace(model=model)
    estimate = bridge._estimate_wire(messages, tools)
    assert model.logical_requests == 0
    on_step.assert_not_called()
    wire_tools = [{"type": "function", "function": {"name": "lookup", "description": "Lookup",
                  "parameters": {"type": "object"}}}]
    request = model._request(messages, wire_tools, False, {})
    body = OpenAIChatAdapter().prepare_http_request(request, profile).json_body
    assert estimate == manager._message_tokens(body["messages"]) + manager._tools_tokens(body.get("tools"))
    assert model.logical_requests == 1 and on_step.call_count == 1
    if text_protocol:
        assert not body.get("tools") and "available_tools" in str(body)
        assert all(m["role"] != "tool" and not m.get("tool_calls") for m in body["messages"])
        assert "historical_tool_result" in str(body)
    else:
        assert [m["tool_call_id"] for m in body["messages"] if m["role"] == "tool"] == [
            "step-a-call-0", "current-call"]
    assert "request-only followup" in str(body)
    assert not {"max_tokens", "max_completion_tokens", "max_output_tokens"}.intersection(body)


def test_assemble_evidence_and_post_response_estimator_use_the_same_wire(saved_profile):
    from nexent.core.agents.cores.jiuwen.model import JiuwenServiceModel
    from nexent.core.concurrency import RunCancellationScope
    from test_jiuwen_context import make_bridge

    bridge, info = make_bridge(items=[history(records(count=1))])
    model = JiuwenServiceModel(Mock(), saved_profile, RunCancellationScope())
    bridge.summary_model.model = model
    bridge.context_manager._request_token_estimator = bridge._estimate_wire
    messages = bridge._assemble([{"role": "system", "content": "policy"},
                                 {"role": "user", "content": info.query}], [])
    assert bridge.context_manager.message_format == "openai_chat_completions"
    assert bridge.last_evidence.final_token_estimate == bridge._estimate(messages, [])
    assert model.logical_requests == 0
    assert any(m.get("tool_calls") for m in messages)


def test_summary_replaces_whole_history_without_orphan_calls():
    manager = ContextManager(message_format="openai_chat_completions")
    turn = history(records())
    before = manager.prepare_items_context("policy", [turn])
    assert len([m for m in before.item_messages if m["role"] == "tool"]) == 2
    checkpoint = ContextItem.from_input(ContextItemInput(id="summary:2", type="history_summary", content={
        "summary": "Previously completed lookups; no actions pending", "covered_through_message_id": 2}))
    after = manager.prepare_items_context("policy", [checkpoint])
    assert not any(m.get("tool_calls") or m["role"] == "tool" for m in after.item_messages)
    assert "Previously completed" in str(after.item_messages)


def test_identical_parallel_arguments_are_ambiguous_not_guessed():
    observer = MessageObserver()
    events = JiuwenEventAdapter(observer, "agent", "turn")
    events.calls = [ToolCall(provider_call_id=identity, index=i, name="same", raw_arguments='{}',
                            parsed_arguments={}) for i, identity in enumerate(["a", "b"])]
    assert events.tool_call("same", {}, "first") is None
    assert events.tool_call("same", {}, "second") is None
    assert len(events.calls) == 2


def test_malformed_explicit_fact_stays_read_only():
    values = records(count=1)
    values[0]["execution_event"]["group_id"] = ["invalid"]
    assert not any(m.get("tool_calls") for m in render(values))


@pytest.mark.parametrize("message", [{"role": "tool-response", "content": "legacy"},
                                     {"role": "tool", "content": "missing id"}])
def test_chat_format_rejects_nonstandard_current_action_messages(message):
    from nexent.core.agents.context.rendering import ContextItemRenderingError

    item = ContextItem.from_input(ContextItemInput(id="action", type="current_action", content={"messages": [message]}))
    with pytest.raises(ContextItemRenderingError):
        ContextManager(message_format="openai_chat_completions").build_context_messages([item])
