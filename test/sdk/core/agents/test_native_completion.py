# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Provider completion, interleaved content and tool-side-effect regression tests."""

from copy import deepcopy
from threading import Event
from types import SimpleNamespace

import pytest
from nexent.core.agents.native_runtime import (
    NativeCompletionError,
    NativeToolCallingAgent,
    collect_native_stream,
    validate_native_completion,
)
from smolagents.models import ChatMessage, Model
from smolagents.tools import Tool


class CounterTool(Tool):
    name = "count"
    description = "Count executions."
    inputs = {}  # noqa: RUF012 - smolagents tool schema.
    output_type = "string"

    def __init__(self):
        super().__init__()
        self.executions = 0

    def forward(self):
        self.executions += 1
        return "observed"


class CompletionModel(Model):
    def __init__(self, responses):
        super().__init__()
        self.responses = iter(responses)
        self.inputs = []

    def generate(self, messages, **kwargs):
        self.inputs.append(deepcopy(messages))
        wire, finish = next(self.responses)
        result = ChatMessage.from_dict(deepcopy(wire))
        result.raw = deepcopy(wire)
        result.finish_reason = finish
        return result


def tool_response(name="count"):
    return {
        "role": "assistant",
        "content": "Checking now.",
        "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": name, "arguments": "{}"}}],
    }


def packet(content=None, calls=None, finish=None, refusal=None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                index=0,
                finish_reason=finish,
                delta=SimpleNamespace(content=content, tool_calls=calls, refusal=refusal),
            )
        ],
        usage=None,
    )


@pytest.mark.parametrize("reason", [None, "length", "content_filter", "pause", "unknown", "tool_calls"])
def test_content_only_requires_normal_stop(reason):
    with pytest.raises(NativeCompletionError):
        validate_native_completion("Partial answer", [], reason)


@pytest.mark.parametrize("reason", [None, "stop", "length", "content_filter", "pause"])
def test_incomplete_tool_generation_has_no_side_effects(reason):
    tool = CounterTool()
    model = CompletionModel([(tool_response(), reason)])
    agent = NativeToolCallingAgent(tools=[tool], model=model, verbosity_level=0)
    with pytest.raises(NativeCompletionError):
        agent.run("Count")
    assert tool.executions == 0
    assert not any(message["role"] == "tool" for message in agent.native_messages)


def test_mixed_content_tool_result_then_normal_stop_is_final():
    tool = CounterTool()
    model = CompletionModel([(tool_response(), "tool_calls"), ({"role": "assistant", "content": "Finished."}, "stop")])
    agent = NativeToolCallingAgent(tools=[tool], model=model, verbosity_level=0)
    assert str(agent.run("Count")) == "Finished."
    assert tool.executions == 1
    assert len(model.inputs) == 2
    assert model.inputs[1][-2]["content"] == "Checking now."
    assert model.inputs[1][-1] == {"role": "tool", "tool_call_id": "call-1", "content": "observed"}
    assert "finish_reason" not in model.inputs[1][-2]


@pytest.mark.parametrize("reason", ["length", "content_filter", None])
def test_stream_does_not_promote_partial_text(reason):
    with pytest.raises(NativeCompletionError):
        collect_native_stream([packet(content="Partial", finish=reason)], Event())


def test_stream_accepts_terminal_reason_then_usage_only_tail():
    usage = SimpleNamespace(prompt_tokens=2, completion_tokens=3)
    wire, actual, finish = collect_native_stream(
        [packet(content="Answer"), packet(finish="stop"), SimpleNamespace(choices=[], usage=usage)], Event()
    )
    assert wire == {"role": "assistant", "content": "Answer"}
    assert actual is usage
    assert finish == "stop"


@pytest.mark.parametrize("tail", [packet(content="late"), packet(finish="stop")])
def test_choices_after_completion_are_protocol_failure(tail):
    with pytest.raises(NativeCompletionError):
        collect_native_stream([packet(content="Answer", finish="stop"), tail], Event())


def test_refusal_is_not_successful_content_completion():
    with pytest.raises(NativeCompletionError):
        collect_native_stream([packet(content="Partial", refusal="Filtered", finish="stop")], Event())


def test_transport_error_after_partial_text_is_not_final():
    def broken():
        yield packet(content="Partial")
        raise ConnectionError("disconnected")

    with pytest.raises(ConnectionError):
        collect_native_stream(broken(), Event())


@pytest.mark.parametrize("content", ["", "   ", None])
def test_empty_normal_stop_is_not_a_final_answer(content):
    with pytest.raises(NativeCompletionError):
        validate_native_completion(content, [], "stop")
