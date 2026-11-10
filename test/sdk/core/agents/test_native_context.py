# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Native context never turns estimates into an admission policy."""

from copy import deepcopy

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


def test_native_originals_are_bound_to_messages_even_if_provider_reuses_call_id():
    from nexent.core.agents.native_context import native_context_items

    messages = [
        {"role": "tool", "tool_call_id": "reused", "content": "first"},
        {"role": "tool", "tool_call_id": "reused", "content": "second"},
    ]
    items = native_context_items(messages, {0: "first-original", 1: "second-original"}, {1})
    assert [item.content["execution_key"] for item in items] == ["first-original", "second-original"]
    assert not items[0].content["loaded_result"] and items[1].content["loaded_result"]
