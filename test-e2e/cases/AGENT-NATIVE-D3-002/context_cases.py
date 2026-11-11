# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Native shared maintenance across the actual HTTP/SSE boundary."""

import json

import pytest
from nexent.core.agents.context import (
    ContextManager,
    ContextManagerConfig,
    ManagedContextRuntime,
)
from nexent.core.agents.context.execution_history import ExecutionHistory
from nexent.core.agents.native_runtime import NativeToolCallingAgent
from nexent.core.utils.observer import MessageObserver, ProcessType


class BoundObserver(MessageObserver):
    """Model the backend's authoritative binding without an external database."""

    def __init__(self):
        super().__init__(lang="en")
        self.execution_history = ExecutionHistory()
        self.keys = []

    def add_message(self, agent_name, process_type, content, **kwargs):
        super().add_message(agent_name, process_type, content, **kwargs)
        if process_type == ProcessType.EXECUTION_RESULT:
            key = json.loads(content)["execution_key"]
            self.execution_history.bind(key, 7, len(self.keys))
            self.keys.append(key)


def build(provider, request, limit):
    config, captured, create = provider
    config.update(calls=True, mixed=True, context=True)
    model = create()
    observer = BoundObserver()
    model.observer = observer
    tool = request.module.EffectTool()
    tool.result = "ORIGINAL-FACT-7429 " + "observed evidence " * 1400
    runtime = ManagedContextRuntime(ContextManager(ContextManagerConfig(effective_input_limit_tokens=limit, policy_layers={"request": {"processing_mode": "adaptive_compact"}})))
    agent = NativeToolCallingAgent(tools=[tool], model=model, observer=observer,
                                  context_runtime=runtime, verbosity_level=0, max_steps=3)
    return config, captured, model, observer, tool, agent


@pytest.mark.case_id("AGENT-NATIVE-D3-002")
@pytest.mark.stage("D3")
def test_native_estimated_excess_continues_over_http(provider, request):
    _, captured, model, _, tool, agent = build(provider, request, 1)
    assert str(agent.run("PROTECTED-CURRENT-TASK")) == "FINAL_OBSERVED"
    assert tool.executions == 1
    assert model.last_context_observation.input_tokens == 10
    assert len(captured) == 2
    assert "PROTECTED-CURRENT-TASK" in str(captured[-1]["messages"])
    assert any(m.get("tool_call_id") == "actual-call" for m in captured[-1]["messages"])


def assert_offloaded(captured, observer, tool, agent):
    assert tool.executions == 1
    final = captured[-1]["messages"]
    call = next(m for m in final if m.get("tool_calls"))
    result = next(m for m in final if m.get("role") == "tool")
    assert call["tool_calls"][0]["id"] == result["tool_call_id"] == "actual-call"
    assert "SUMMARY-SENTINEL" in result["content"] and "message:7/unit-index:0" in result["content"]
    record = observer.execution_history.get(observer.keys[0])
    assert record.fields["OUTPUT"] == tool.result and record.summary
    loaded = observer.execution_history.read(agent._execution_owner, record.reference, max_chars=100)
    assert "ORIGINAL-FACT-7429" in loaded
    assert "PROTECTED-CURRENT-TASK" in str(final)


@pytest.mark.case_id("AGENT-NATIVE-D3-002")
@pytest.mark.stage("D3")
def test_native_result_offload_preserves_correlated_http_history(provider, request):
    _, captured, _, observer, tool, agent = build(provider, request, 20000)
    assert str(agent.run("PROTECTED-CURRENT-TASK")) == "FINAL_OBSERVED"
    assert len(captured) == 3, len(captured)  # Main, actual auxiliary summary, continuation.
    assert_offloaded(captured, observer, tool, agent)


@pytest.mark.case_id("AGENT-NATIVE-D3-002")
@pytest.mark.stage("D3")
def test_native_overflow_rebuild_preserves_completed_effect(provider, request):
    config, captured, model, observer, tool, agent = build(provider, request, 1_000_000)
    config["overflow_after_tool"] = True
    assert str(agent.run("PROTECTED-CURRENT-TASK")) == "FINAL_OBSERVED"
    assert config["overflow_sent"] and len(captured) == 4, len(captured)
    assert model.last_attempt_number == 2
    assert_offloaded(captured, observer, tool, agent)
