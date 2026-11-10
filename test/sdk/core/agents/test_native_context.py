# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Native context never turns estimates into an admission policy."""

import json
from copy import deepcopy

import pytest
from native_runtime_fixtures import agent_for, call
from nexent.core.agents.context import (
    ContextManager,
    ContextManagerConfig,
    ManagedContextRuntime,
)
from nexent.core.agents.context.models import ContextItem, ContextItemInput
from nexent.core.agents.context.rendering import ContextItemRenderer


def test_native_estimated_excess_preserves_task_and_tool_pair():
    agent, model = agent_for([
        {"role": "assistant", "content": "Checking", "tool_calls": [call("one")]},
        {"role": "assistant", "content": "Done"},
    ])
    agent.context_runtime = ManagedContextRuntime(ContextManager(ContextManagerConfig(effective_input_limit_tokens=1)))
    assert str(agent.run("PROTECTED TASK")) == "Done"
    assert len(model.requests) == 2
    assert "PROTECTED TASK" in str(model.requests[1])
    assert model.requests[1][-2]["tool_calls"][0]["id"] == model.requests[1][-1]["tool_call_id"] == "one"


def test_compact_native_result_changes_only_tool_content():
    message = {"role": "tool", "tool_call_id": "one", "content": "ORIGINAL"}
    item = ContextItem.from_input(ContextItemInput(id="native:1", type="current_action", content={
        "messages": [message], "execution_fields": {"OUTPUT": "ORIGINAL"},
        "summary": "Exact fact", "output_ref": "message:7/unit-index:2",
    }))
    before = deepcopy(item.content)
    result = ContextItemRenderer().render([item])
    assert result[0]["role"] == "tool" and result[0]["tool_call_id"] == "one"
    assert "Exact fact" in result[0]["content"] and "message:7/unit-index:2" in result[0]["content"]
    assert item.content == before


def test_native_call_record_cannot_be_deterministically_truncated():
    messages = [{"role": "assistant", "content": "progress", "tool_calls": [call("one")]}]
    item = ContextItem.from_input(ContextItemInput(id="native:1", type="current_action", content={"messages": messages}))
    assert ContextItemRenderer().render([item.compact()]) == messages


def test_legacy_export_compacts_while_unbound_native_protocol_stays_intact():
    manager = ContextManager(ContextManagerConfig(effective_input_limit_tokens=1000))
    legacy = ContextItem.from_input(ContextItemInput(id="legacy", type="current_action", content={
        "tool_calls": [{"name": "search", "arguments": {"q": "x"}}],
        "observations": "observed " * 1000,
        "model_output": "private process",
        "messages": [{"role": "assistant", "content": "raw process"}],
    }))
    compact = manager._compact_execution(legacy, None)
    assert compact.content["tool_calls"] == legacy.content["tool_calls"]
    assert len(compact.content["observations"]) < len(legacy.content["observations"])
    assert "messages" not in compact.content and "model_output" not in compact.content
    native = ContextItem.from_input(ContextItemInput(id="native:0", type="current_action", content={
        "messages": [{"role": "assistant", "content": "progress", "tool_calls": [call("one")]}],
    }))
    assert manager._compact_execution(native, None) is None
    assert ContextItemRenderer().render([native.compact()]) == native.content["messages"]


def test_native_originals_are_bound_to_messages_even_if_provider_reuses_call_id():
    from nexent.core.agents.native_context import native_context_items

    messages = [
        {"role": "tool", "tool_call_id": "reused", "content": "first"},
        {"role": "tool", "tool_call_id": "reused", "content": "second"},
    ]
    items = native_context_items(messages, {0: "first-original", 1: "second-original"}, {1})
    assert [item.content["execution_key"] for item in items] == ["first-original", "second-original"]
    assert not items[0].content["loaded_result"] and items[1].content["loaded_result"]


def test_native_owned_result_can_be_read_and_loaded_range_is_protected():
    from nexent.core.agents.context.execution_history import ExecutionHistory
    from nexent.core.utils.observer import MessageObserver, ProcessType

    class BindingObserver(MessageObserver):
        def __init__(self):
            super().__init__(lang="en")
            self.execution_history = ExecutionHistory()
            self.bound = []

        def add_message(self, name, kind, content, **kwargs):
            super().add_message(name, kind, content, **kwargs)
            if kind == ProcessType.EXECUTION_RESULT:
                key = json.loads(content)["execution_key"]
                self.execution_history.bind(key, 7, len(self.bound))
                self.bound.append(key)

    from native_runtime_fixtures import EchoTool, ScriptedModel
    from nexent.core.agents.native_runtime import NativeToolCallingAgent

    observer = BindingObserver()
    model = ScriptedModel([
        {"role": "assistant", "tool_calls": [call("original")]},
        {"role": "assistant", "tool_calls": [call("load", "read_execution_output",
            '{"output_ref":"message:7/unit-index:0","offset":0,"max_chars":100}')]},
        {"role": "assistant", "content": "Done"},
    ])
    runtime = ManagedContextRuntime(ContextManager(ContextManagerConfig(effective_input_limit_tokens=1)))
    agent = NativeToolCallingAgent(model=model, tools=[EchoTool()], observer=observer,
                                  context_runtime=runtime, verbosity_level=0)
    assert str(agent.run("Read the actual original.")) == "Done"
    assert len(observer.bound) == 2 and len(agent._native_records) == 2
    loaded = model.requests[2][-1]
    assert loaded["tool_call_id"] == "load" and "hello" in loaded["content"]
    assert agent._native_loaded_messages
    assert "read_execution_output" in agent.programmatic_tool_names
    with pytest.raises(PermissionError):
        observer.execution_history.read("another-owner", "message:7/unit-index:0")
    original = observer.execution_history.get(observer.bound[0])
    assert original.owner == agent._execution_owner and original.fields == {"OUTPUT": "hello"}
