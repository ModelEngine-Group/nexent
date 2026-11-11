# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Native runtime selection and model-service request/continuation contracts."""

from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest
from nexent.core.agents.native_model_service import NativeServiceModel
from nexent.core.agents.native_runtime import NativeCompletionError
from nexent.core.agents.runtime_factory import (
    adapt_fallback_context_items,
    select_agent_runtime,
)
from nexent.core.concurrency.cancellation import RunCancellationScope, RunTerminated
from nexent.core.model_service.compatibility.legacy_chat_model import LegacyChatModel
from nexent.core.model_service.contracts import AssistantMessage, ModelEvent


@pytest.fixture
def native_profile(protocol_profile):
    values = protocol_profile.model_dump()
    values["bindings"]["native_converter"] = {"ref": "native_tools_v1", "version": 1}
    return type(protocol_profile).model_validate(values)


class ServiceBoundary:
    def __init__(self, message):
        self.message = message
        self.requests = []
        self.closed = False

    @contextmanager
    def stream(self, request, profile, **kwargs):
        self.requests.append((request, profile, kwargs))
        try:
            yield iter(
                [
                    ModelEvent(
                        request_id=request.request_id,
                        message_id=self.message.message_id,
                        sequence=1,
                        finish_reason=self.message.finish_reason,
                        type="message_completed",
                        message=self.message,
                    )
                ]
            )
        finally:
            self.closed = True


@pytest.mark.parametrize("tools", ["supported", "unsupported", "unknown"])
@pytest.mark.parametrize("reasoning", ["supported", "unsupported", "unknown"])
def test_selection_uses_tool_capability_independently(native_profile, tools, reasoning):
    values = native_profile.model_dump()
    values["capabilities"]["tools"]["status"] = tools
    values["capabilities"]["reasoning"]["status"] = reasoning
    if reasoning != "supported":
        values["capabilities"]["reasoning"]["controls"] = []
        values["parameter_values"].pop("enable_thinking", None)
    model = SimpleNamespace(profile=type(native_profile).model_validate(values))
    assert select_agent_runtime("codeagent", model) == "codeagent"
    assert select_agent_runtime("toolcalling", model) == ("toolcalling" if tools == "supported" else "codeagent")


def test_missing_profile_is_compatibility_fallback():
    assert select_agent_runtime("toolcalling", object()) == "codeagent"
    with pytest.raises(ValueError):
        select_agent_runtime("typo", object())


def test_native_service_preserves_profile_ids_reasoning_and_correlated_history(native_profile):
    complete = AssistantMessage(
        content_parts=[{"type": "text", "text": "Done"}],
        reasoning_parts=[{"type": "text", "text": "private fixture"}],
        finish_reason="stop",
    )
    service = ServiceBoundary(complete)
    scope = RunCancellationScope()
    delegate = LegacyChatModel(native_profile, service, cancellation_scope=scope)
    model = NativeServiceModel(delegate)
    messages = [
        {"role": "system", "content": "Platform instructions"},
        {"role": "user", "content": "Task"},
        {
            "role": "assistant",
            "content": "Checking",
            "reasoning_parts": [{"type": "text", "text": "continuation fixture"}],
            "tool_calls": [
                {"id": "provider-call", "type": "function", "function": {"name": "echo", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "provider-call", "content": "Observed"},
    ]
    before = deepcopy(messages)
    schema = {
        "type": "function",
        "function": {"name": "echo", "description": "Echo", "parameters": {"type": "object", "properties": {}}},
    }
    result = model.generate(messages, native_tool_schemas=[schema])
    request, profile, options = service.requests[0]
    assert profile.identity == native_profile.identity
    assert profile.parameter_values == native_profile.parameter_values
    assert options["scope"] is scope
    assert request.tools[0].name == "echo"
    assert request.messages[-2].tool_calls[0].provider_call_id == "provider-call"
    assert request.messages[-2].reasoning_parts == messages[-2]["reasoning_parts"]
    assert request.messages[-1].tool_call_id == "provider-call"
    assert messages == before
    assert result.content == "Done"
    assert result.finish_reason == "stop"
    assert result.raw["reasoning_parts"] == complete.reasoning_parts
    assert service.closed


@pytest.mark.parametrize("reason", ["length", "content_filter", "pause"])
def test_service_terminal_policy_rejects_non_success(native_profile, reason):
    service = ServiceBoundary(
        AssistantMessage(content_parts=[{"type": "text", "text": "Partial"}], finish_reason=reason)
    )
    delegate = LegacyChatModel(native_profile, service)
    with pytest.raises(NativeCompletionError):
        NativeServiceModel(delegate).generate([{"role": "user", "content": "Task"}])
    assert service.closed


def test_cancellation_after_provider_completion_never_accepts_answer(native_profile):
    service = ServiceBoundary(
        AssistantMessage(content_parts=[{"type": "text", "text": "Answer"}], finish_reason="stop")
    )
    delegate = LegacyChatModel(native_profile, service)
    delegate.stop_event.set()
    with pytest.raises(RunTerminated):
        NativeServiceModel(delegate).generate([{"role": "user", "content": "Task"}])
    assert service.closed


def test_fallback_removes_only_trusted_thought_instruction(native_profile):
    from nexent.core.agents.context import ContextItemInput

    values = native_profile.model_dump()
    values["capabilities"]["reasoning"]["status"] = "unsupported"
    values["capabilities"]["reasoning"]["controls"] = []
    model = SimpleNamespace(profile=type(native_profile).model_validate(values))
    trusted = ContextItemInput(
        id="system:execution_flow",
        type="system",
        content={"text": "Think then act"},
        source=("agent_prompt:execution_flow",),
        metadata={"authority": "platform"},
    )
    authored = trusted.model_copy(update={"id": "system:custom", "content": {"text": "Keep authored instructions"}})
    result = adapt_fallback_context_items([trusted, authored], "toolcalling", "codeagent", model)
    assert "No written thought" in result[0].content["text"]
    assert "<code>" in result[0].content["text"]
    assert result[1] is authored
    assert trusted.content["text"] == "Think then act"


@pytest.mark.parametrize("status", ["supported", "unsupported", "unknown"])
def test_actual_agent_factory_uses_selected_model_capability(native_profile, status, mocker):
    from threading import Event

    from nexent.core.agents.agent_model import AgentConfig
    from nexent.core.agents.core_agent import CoreAgent
    from nexent.core.agents.native_runtime import NativeToolCallingAgent
    from nexent.core.agents.nexent_agent import NexentAgent
    from nexent.core.utils.observer import MessageObserver

    values = native_profile.model_dump()
    values["capabilities"]["tools"]["status"] = status
    profile = type(native_profile).model_validate(values)
    stop = Event()
    delegate = LegacyChatModel(
        profile, ServiceBoundary(AssistantMessage(finish_reason="stop")), cancellation_scope=RunCancellationScope(stop)
    )
    factory = NexentAgent(MessageObserver(lang="en"), [], stop, agent_runtime="toolcalling")
    mocker.patch.object(factory, "create_model", return_value=delegate)
    definition = AgentConfig(name="existing", description="Existing definition", model_name="outlet", tools=[])
    before = definition.model_dump()
    agent = factory.create_single_agent(definition)
    assert isinstance(agent, NativeToolCallingAgent if status == "supported" else CoreAgent)
    assert agent.nexent_requested_runtime == "toolcalling"
    assert agent.nexent_effective_runtime == ("toolcalling" if status == "supported" else "codeagent")
    assert agent.stop_event is stop
    assert definition.model_dump() == before


def test_native_call_controls_use_declared_model_service_rules(native_profile):
    from nexent.core.model_service.profiles.parameter_schema import (
        ParameterValidationError,
    )

    service = ServiceBoundary(
        AssistantMessage(content_parts=[{"type": "text", "text": "Answer"}], finish_reason="stop")
    )
    model = NativeServiceModel(LegacyChatModel(native_profile, service))
    with pytest.raises(ParameterValidationError):
        model.generate([{"role": "user", "content": "Task"}], made_up_control=True)
    assert service.requests == []
    before = native_profile.model_dump()
    model.generate([{"role": "user", "content": "Task"}], temperature=0.3)
    assert service.requests[0][1].parameter_values["temperature"] == 0.3
    assert native_profile.model_dump() == before
