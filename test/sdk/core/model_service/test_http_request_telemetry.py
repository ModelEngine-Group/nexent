# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""AC-OBS-HTTP-001..003: public request evidence comes from the prepared body."""

import json

import pytest
from test_context_recovery import overflow
from test_model_service import Sender, complete, frame
from test_model_service import setup as setup  # noqa: PLC0414
from test_stop_invocation_parameters import monitoring as monitoring  # noqa: PLC0414

from nexent.core.model_service.contracts import ModelMessage, ToolCall, ToolDefinition
from nexent.core.model_service.sse import SSEEvent


def logical_span(exported):
    spans = [s for s in exported.get_finished_spans() if s.attributes.get("openinference.span.kind") == "LLM"]
    assert len(spans) == 1
    return spans[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["invoke", "ainvoke", "stream", "astream"])
@pytest.mark.parametrize("native", [False, True])
async def test_exported_request_is_the_complete_actual_body(setup, monitoring, mode, native):
    profile, request, limiter, factory = setup
    manager, exported = monitoring
    manager._config.trace_content_mode = "full"
    manager._config.trace_max_chars = 0
    data = profile.model_dump()
    data["parameter_values"]["stop"] = ["ACTUAL_STOP"]
    data["extra_api_parameters"].append({"path": "/provider_extension", "value": {"zero": 0, "values": [False, "中文"]}})
    if native:
        data["capabilities"]["tools"]["status"] = "supported"
        tools = [ToolDefinition(name="lookup", description="Actual tool schema", input_schema={
            "type": "object", "properties": {"password": {"type": "string"}, "headers": {"type": "object"}},
        })]
        messages = list(request.messages)
        for name in ("past", "current"):
            messages.extend([
                ModelMessage(semantic_role="assistant", tool_calls=[ToolCall(
                    provider_call_id=name, index=0, name="lookup", raw_arguments='{"key":"value"}',
                )]),
                ModelMessage(semantic_role="tool", tool_call_id=name,
                             content_parts=[{"type": "text", "text": name + " result"}]),
            ])
        request = request.model_copy(update={"messages": messages, "tools": tools})
    profile = type(profile).model_validate(data)
    streaming = mode in {"stream", "astream"}
    request = request.model_copy(update={"stream": streaming})
    response = [frame({"content": "answer"}), frame(finish="stop"), SSEEvent("[DONE]")] if streaming else complete()
    sender = Sender([response])
    model = factory(sender, monitoring=manager)
    if mode == "astream":
        async with model.astream(request, profile) as events:
            assert [event async for event in events][-1].message.content_parts[0]["text"] == "answer"
    elif mode == "stream":
        with model.stream(request, profile) as events:
            assert list(events)[-1].message.content_parts[0]["text"] == "answer"
    else:
        result = await model.ainvoke(request, profile) if mode == "ainvoke" else model.invoke(request, profile)
        assert result.content_parts[0]["text"] == "answer"
    assert len(sender.calls) == 1 and not limiter._entries
    body = json.loads(sender.calls[0].body_bytes)
    span = logical_span(exported)
    attrs = span.attributes
    assert json.loads(attrs["input.value"]) == body
    assert attrs["input.preview"] == attrs["input.value"]
    assert attrs["input.size_chars"] == len(attrs["input.value"])
    assert attrs["input.type"] == "dict" and attrs["input.truncated"] is False
    assert attrs["model.request.attempt"] == 1
    assert attrs["http.request.method"] == sender.calls[0].method
    assert attrs["url.full"] == sender.calls[0].url
    attempts = [event for event in span.events if event.name == "model_attempt_begin"]
    assert len(attempts) == 1 and attempts[0].attributes["attempt"] == 1
    assert json.loads(attempts[0].attributes["input.value"]) == body
    assert body["model"] == profile.identity.request_model_id and body["stream"] is streaming
    assert body["provider_extension"] == {"zero": 0, "values": [False, "中文"]}
    assert json.loads(attrs["llm.invocation_parameters"])["stop"] == body["stop"] == ["ACTUAL_STOP"]
    if streaming:
        assert body["stream_options"] == {"include_usage": True}
    if native:
        assert [m["tool_call_id"] for m in body["messages"] if m["role"] == "tool"] == ["past", "current"]
        assert [m["tool_calls"][0]["id"] for m in body["messages"] if m.get("tool_calls")] == ["past", "current"]
        assert set(body["tools"][0]["function"]["parameters"]["properties"]) == {"password", "headers"}
    else:
        assert "tools" not in body


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_rebuilt_retry_events_keep_each_actual_body_and_first_input(setup, monitoring, asynchronous):
    profile, request, limiter, factory = setup
    manager, exported = monitoring
    manager._config.trace_content_mode = "full"
    manager._config.trace_max_chars = 0
    sender = Sender([overflow(), complete()])

    def rebuild(error):
        assert error.attempt == 1
        return request.model_copy(update={"messages": [ModelMessage(
            semantic_role="user", content_parts=[{"type": "text", "text": "rebuilt prompt"}],
        )]})

    async def arebuild(error):
        return rebuild(error)

    model = factory(sender, monitoring=manager)
    result = (await model.ainvoke(request, profile, request_rebuild=arebuild) if asynchronous
              else model.invoke(request, profile, request_rebuild=rebuild))
    assert result.content_parts[0]["text"] == "answer"
    assert len(sender.calls) == 2 and sender.frozen == 1 and not limiter._entries
    bodies = [json.loads(call.body_bytes) for call in sender.calls]
    assert bodies[0] != bodies[1]
    span = logical_span(exported)
    assert json.loads(span.attributes["input.value"]) == bodies[0]
    attempts = [e.attributes for e in span.events if e.name == "model_attempt_begin"]
    assert [e["attempt"] for e in attempts] == [1, 2]
    assert [e["request_id"] for e in attempts] == [request.request_id] * 2
    assert [json.loads(e["input.value"]) for e in attempts] == bodies


@pytest.mark.parametrize("mode,max_chars", [("metrics", 0), ("summary", 24), ("full", 24)])
def test_request_recording_respects_content_limits(setup, monitoring, mode, max_chars):
    profile, request, _, factory = setup
    manager, exported = monitoring
    manager._config.trace_content_mode = mode
    manager._config.trace_max_chars = max_chars
    sender = Sender([complete()])
    factory(sender, monitoring=manager).invoke(request, profile)
    span = logical_span(exported)
    event = next(e for e in span.events if e.name == "model_attempt_begin")
    for attrs in (span.attributes, event.attributes):
        assert attrs["input.truncated"] is True
        if mode == "metrics":
            assert attrs["input.value"] == attrs["input.preview"] == ""
        else:
            assert attrs["input.value"].endswith("...[truncated]")
            assert attrs["input.value"] == attrs["input.preview"]


def test_headers_and_endpoint_credentials_are_not_exported(setup, monitoring):
    profile, request, _, factory = setup
    manager, exported = monitoring
    manager._config.trace_content_mode = "full"
    manager._config.trace_max_chars = 0
    data = profile.model_dump()
    data["connection"]["base_url"] = "https://example.test/v1?api_key=endpoint-secret&region=cn"
    data["connection_rules"]["headers"] = {"x-private-header": "header-secret"}
    profile = type(profile).model_validate(data)
    sender = Sender([complete()])
    factory(sender, monitoring=manager).invoke(request, profile)
    assert sender.calls[0].headers["x-private-header"] == "header-secret"
    assert "endpoint-secret" in sender.calls[0].url
    span = logical_span(exported)
    public = str(span.attributes) + str([dict(e.attributes) for e in span.events])
    assert "endpoint-secret" not in public and "header-secret" not in public
    assert "credential_ref" not in public and "x-private-header" not in public
    assert "api_key=REDACTED_CREDENTIAL&region=cn" in span.attributes["url.full"]
    assert json.loads(span.attributes["input.value"]) == json.loads(sender.calls[0].body_bytes)
