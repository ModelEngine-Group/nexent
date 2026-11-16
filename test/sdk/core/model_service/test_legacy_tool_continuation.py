# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Legacy histories retain native tool associations at the real adapter boundary."""

import json
from contextlib import asynccontextmanager, contextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest
from smolagents.models import ChatMessage

from nexent.core.model_service.adapters.openai_chat import ModelAdapterError, OpenAIChatAdapter
from nexent.core.model_service.compatibility.legacy_chat_model import LegacyChatModel
from nexent.core.model_service.contracts import AssistantMessage, ModelEvent, ToolCall
from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile


@pytest.fixture
def native_profile(openai_profile):
    data = openai_profile.model_dump(mode="json")
    data["capabilities"]["tools"]["status"] = "supported"
    return ResolvedModelProfile.model_validate(data)


@pytest.fixture
def continuation(native_profile):
    bodies = []
    calls = [ToolCall(provider_call_id="call-" + str(i), index=i, name="calculate",
                      raw_arguments='{"value": ' + str(i) + '}') for i in range(2)]

    @contextmanager
    def stream(request, profile, **kwargs):
        prepared = OpenAIChatAdapter().prepare_http_request(request, profile)
        bodies.append(json.loads(prepared.body_bytes))
        message = (AssistantMessage(tool_calls=calls, finish_reason="tool_calls") if len(bodies) == 1 else
                   AssistantMessage(content_parts=[{"type": "text", "text": "DONE"}], finish_reason="stop"))
        events = []
        if len(bodies) > 1:
            events.append(ModelEvent(request_id=request.request_id, message_id=message.message_id,
                                     sequence=1, type="text_delta", delta="DONE"))
        events.append(ModelEvent(request_id=request.request_id, message_id=message.message_id,
                                 sequence=len(events) + 1, type="message_completed", message=message,
                                 finish_reason=message.finish_reason))
        yield iter(events)


    return LegacyChatModel(native_profile, SimpleNamespace(stream=stream)), bodies


@pytest.mark.parametrize("assistant_kind", ["object", "dictionary"])
@pytest.mark.parametrize("tool_role", ["tool", "tool-response"])
@pytest.mark.parametrize("flatten", [False, True])
@pytest.mark.parametrize("streaming", [False, True])
def test_second_invocation_retains_returned_tool_calls(continuation, assistant_kind, tool_role, flatten, streaming):
    model, bodies = continuation
    model.flatten_messages_as_text = flatten
    first = model.generate([{"role": "user", "content": "Calculate two values"}])
    assert isinstance(first, ChatMessage)
    assert [call.id for call in first.tool_calls] == ["call-0", "call-1"]
    assistant = first if assistant_kind == "object" else {
        "role": "assistant", "content": None,
        "tool_calls": [{"id": call.id, "type": call.type,
                        "function": {"name": call.function.name, "arguments": call.function.arguments}}
                       for call in first.tool_calls],
    }
    history = [{"role": "user", "content": "Calculate two values"}, assistant,
               {"role": tool_role, "tool_call_id": "call-0", "content": "10"},
               {"role": tool_role, "tool_call_id": "call-1", "content": "20"}]
    original = deepcopy(history)
    result = ("".join(delta.content or "" for delta in model.generate_stream(history)) if streaming else
              model.generate(history).content)
    assert result == "DONE" and history == original
    wire = bodies[1]["messages"]
    assert len(wire) == 4
    assert wire[1]["role"] == "assistant"
    assert wire[1]["tool_calls"] == [
        {"id": "call-" + str(i), "type": "function",
         "function": {"name": "calculate", "arguments": '{"value": ' + str(i) + '}'}} for i in range(2)]
    assert wire[2:] == [{"role": "tool", "tool_call_id": "call-0", "content": "10"},
                       {"role": "tool", "tool_call_id": "call-1", "content": "20"}]


def test_missing_native_tool_id_stays_invalid(continuation):
    model, bodies = continuation
    with pytest.raises(ModelAdapterError, match="^MODEL_MESSAGE_INVALID$"):
        model.generate([{"role": "tool", "content": "orphan"}])
    assert bodies == []


@pytest.mark.parametrize("arguments", [{"text": "中文", "nested": {"value": 3}}, '{"value":  3}'])
def test_argument_objects_serialize_and_strings_keep_exact_bytes(continuation, arguments):
    model, bodies = continuation
    call = {"id": "original-call", "type": "function", "function": {"name": "calculate", "arguments": arguments}}
    history = [{"role": "assistant", "content": None, "tool_calls": [call]},
               {"role": "tool", "tool_call_id": "original-call", "content": "3"}]
    before = deepcopy(history)
    model.generate(history)
    actual = bodies[0]["messages"][0]["tool_calls"][0]["function"]["arguments"]
    assert json.loads(actual) == (arguments if isinstance(arguments, dict) else json.loads(arguments))
    if isinstance(arguments, str):
        assert actual == arguments
    assert history == before


@pytest.mark.parametrize("call", [
    {}, {"id": "c", "type": "other", "function": {"name": "f", "arguments": "{}"}},
    {"id": "c", "type": "function", "function": {"name": "f", "arguments": []}},
    {"id": "c", "type": "function", "function": {"name": "f", "arguments": {"n": float("nan")}}},
])
def test_invalid_tool_shapes_fail_without_sending_or_mutating(continuation, call):
    model, bodies = continuation
    history = [{"role": "assistant", "content": None, "tool_calls": [call]}]
    with pytest.raises(ValueError):
        model.generate(history)
    assert bodies == [] and history[0]["tool_calls"][0] is call


def test_unsupported_native_tool_capability_is_not_bypassed(continuation):
    model, bodies = continuation
    snapshot = model.profile.model_dump(mode="json")
    snapshot["capabilities"]["tools"]["status"] = "unknown"
    model.profile = ResolvedModelProfile.model_validate(snapshot)
    with pytest.raises(ModelAdapterError, match="^NATIVE_TOOL_PROTOCOL_UNAVAILABLE$"):
        model.generate([{"role": "tool", "content": "result", "tool_call_id": "call-0"}])
    assert bodies == []


@pytest.mark.asyncio
async def test_async_stream_continues_returned_calls(continuation):
    model, bodies = continuation
    first = model.generate([{"role": "user", "content": "Calculate"}])

    @asynccontextmanager
    async def astream(request, profile, **kwargs):
        bodies.append(json.loads(OpenAIChatAdapter().prepare_http_request(request, profile).body_bytes))
        async def events():
            yield ModelEvent(request_id=request.request_id, message_id=request.messages[0].message_id,
                             sequence=1, type="text_delta", delta="ASYNC_DONE")
        yield events()

    model.service.astream = astream
    history = [first, {"role": "tool", "tool_call_id": "call-0", "content": "10"},
               {"role": "tool", "tool_call_id": "call-1", "content": "20"}]
    assert "".join([delta.content or "" async for delta in model.agenerate_stream(history)]) == "ASYNC_DONE"
    assert [row["tool_call_id"] for row in bodies[-1]["messages"][1:]] == ["call-0", "call-1"]
