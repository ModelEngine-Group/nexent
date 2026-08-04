import json
from types import SimpleNamespace

import pytest
from fastapi.responses import JSONResponse, StreamingResponse

from consts.model import NexentRunAgentInput
from services.ag_ui_service import (
    AGUIEventAdapter,
    AGUIRequestValidationError,
    _content_to_text,
    _iter_legacy_payloads,
    map_run_input_to_agent_request,
    run_agent_agui_stream,
)


def _run_input(*, messages=None, nexent=None, **overrides):
    payload = {
        "threadId": "thread-1",
        "runId": "run-1",
        "state": {},
        "messages": messages or [{"id": "user-1", "role": "user", "content": "hello"}],
        "tools": [],
        "context": [],
        "forwardedProps": {"nexent": nexent or {"conversationId": 7}},
        **overrides,
    }
    return NexentRunAgentInput.model_validate(payload)


def test_maps_standard_input_to_legacy_request():
    run_input = _run_input(
        messages=[
            {"id": "user-1", "role": "user", "content": "question"},
            {"id": "assistant-1", "role": "assistant", "content": "answer"},
            {
                "id": "user-2",
                "role": "user",
                "content": [
                    {"type": "text", "text": "next"},
                    {"type": "binary", "mimeType": "image/png", "data": "AA=="},
                ],
            },
        ],
        nexent={
            "conversationId": 7,
            "agentId": 10,
            "modelId": 5,
            "versionNo": 2,
            "requestedOutputTokens": 4096,
            "enablePlan": True,
            "capabilities": {
                "a2ui": {"versions": ["unsupported"], "catalogId": "legacy-client"}
            },
        },
    )

    request, props = map_run_input_to_agent_request(run_input)

    assert request.query == "next"
    assert [(item.role, item.content) for item in request.history] == [
        ("user", "question"),
        ("assistant", "answer"),
    ]
    assert request.agent_id == 10
    assert request.model_id == 5
    assert request.version_no == 2
    assert request.requested_output_tokens == 4096
    assert request.enable_plan is True
    assert props.conversation_id == 7
    assert _content_to_text(
        [SimpleNamespace(model_dump=lambda **_: {"type": "text", "text": "ok"})]
    ) == "ok"
    assert _content_to_text(None) == ""


def test_ignores_non_conversational_messages_and_rejects_invalid_nexent_props():
    request, _ = map_run_input_to_agent_request(
        _run_input(
            messages=[
                {"id": "system-1", "role": "system", "content": "ignore"},
                {"id": "user-1", "role": "user", "content": "hello"},
            ]
        )
    )
    assert request.query == "hello"

    with pytest.raises(AGUIRequestValidationError, match="Invalid forwardedProps.nexent"):
        map_run_input_to_agent_request(
            _run_input(nexent={"conversationId": "not-an-integer"})
        )


def test_maps_a2ui_action_without_rewriting_visible_query():
    request, _ = map_run_input_to_agent_request(
        _run_input(
            messages=[{"id": "user-1", "role": "user", "content": "提交"}],
            nexent={
                "conversationId": 7,
                "a2uiAction": {
                    "version": "v0.9",
                    "action": {
                        "name": "submit_form",
                        "surfaceId": "surface-1",
                        "sourceComponentId": "submit",
                        "timestamp": "2026-07-29T10:00:00Z",
                        "context": {"name": "Ada"},
                    },
                },
            },
        )
    )

    assert request.query == "提交"
    assert request.a2ui_action.action.name == "submit_form"
    assert request.a2ui_action.action.context == {"name": "Ada"}


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"tools": [{"name": "unsafe", "description": "", "parameters": {}}]}, "tools"),
        ({"context": [{"description": "unsafe", "value": "x"}]}, "context"),
        ({"state": {"unsafe": True}}, "state"),
        ({"forwardedProps": {"nexent": {}, "other": {}}}, "forwardedProps"),
    ],
)
def test_rejects_client_configuration(overrides, message):
    with pytest.raises(AGUIRequestValidationError, match=message):
        map_run_input_to_agent_request(_run_input(**overrides))


def test_resume_and_message_validation():
    resumed, props = map_run_input_to_agent_request(
        _run_input(
            messages=[{"id": "assistant-1", "role": "assistant", "content": "partial"}],
            nexent={"conversationId": 7, "resume": True},
        )
    )
    assert resumed.query == "[resume]"
    assert resumed.history == []
    assert props.resume is True

    with pytest.raises(AGUIRequestValidationError, match="conversationId"):
        map_run_input_to_agent_request(_run_input(nexent={"resume": True}))
    with pytest.raises(AGUIRequestValidationError, match="end with a user"):
        map_run_input_to_agent_request(
            _run_input(messages=[{"id": "a", "role": "assistant", "content": "done"}])
        )


def test_maps_only_core_events_and_preserves_boundaries():
    adapter = AGUIEventAdapter("thread", "run")

    reasoning = adapter.map_payload({"type": "model_output_thinking", "content": "think"})
    assert [event.type.value for event in reasoning] == [
        "REASONING_MESSAGE_START",
        "REASONING_MESSAGE_CONTENT",
    ]
    text = adapter.map_payload({"type": "final_answer", "content": "answer"})
    assert [event.type.value for event in text] == [
        "REASONING_MESSAGE_END",
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_CONTENT",
    ]
    tool = adapter.map_payload(
        {
            "type": "tool",
            "content": "",
            "tool_call_id": "call-1",
            "tool_name": "search",
            "tool_arguments": {"q": "nexent"},
        }
    )
    assert [event.type.value for event in tool] == [
        "TEXT_MESSAGE_END",
        "TOOL_CALL_START",
        "TOOL_CALL_ARGS",
        "TOOL_CALL_END",
    ]
    assert json.loads(tool[2].delta) == {"q": "nexent"}
    result = adapter.map_payload(
        {"type": "execution_logs", "content": "ok", "tool_call_id": "call-1"}
    )
    assert result[0].type.value == "TOOL_CALL_RESULT"
    assert adapter.map_payload({"type": "plan", "content": "ignored"}) == []

    a2ui = adapter.map_payload({"type": "a2ui", "content": '{"surfaceId":"s"}'})
    conversation = adapter.map_payload(
        {"type": "conversation_created", "content": {"conversation_id": 42}}
    )
    assert a2ui[0].name == "nexent.a2ui"
    assert conversation[0].name == "nexent.conversation.created"


def test_maps_tool_content_fallback_and_preserves_non_json_custom_content():
    adapter = AGUIEventAdapter("thread", "run")

    tool = adapter.map_payload({"type": "tool-call", "content": '{"q":"nexent"}'})
    assert tool[0].tool_call_name == "nexent_tool"
    assert json.loads(tool[1].delta) == {"q": "nexent"}

    custom = adapter.map_payload({"type": "a2ui", "content": "not-json"})
    assert custom[0].value == "not-json"


def test_error_terminates_without_run_finished():
    adapter = AGUIEventAdapter("thread", "run")
    adapter.map_payload({"type": "final_answer", "content": "partial"})
    error = adapter.map_payload({"type": "error", "content": "boom"})
    assert error[-1].type.value == "RUN_ERROR"
    assert all(event.type.value != "RUN_FINISHED" for event in adapter.finish())


def test_ignored_events_do_not_split_text_or_reasoning_boundaries():
    adapter = AGUIEventAdapter("thread", "run")

    first = adapter.map_payload({"type": "final_answer", "content": "hello"})
    assert [event.type.value for event in first] == [
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_CONTENT",
    ]
    assert adapter.map_payload({"type": "token_count", "content": "{}"}) == []
    second = adapter.map_payload({"type": "final_answer", "content": " world"})
    assert [event.type.value for event in second] == ["TEXT_MESSAGE_CONTENT"]


@pytest.mark.asyncio
async def test_legacy_sse_decoder_handles_chunk_boundaries():
    async def chunks():
        yield 'data: {"type":"final_'
        yield 'answer","content":"ok"}\n\ndata: {"type":"a2ui","content":"{}"}\n\n'

    values = [value async for value in _iter_legacy_payloads(chunks())]
    assert values == [
        {"type": "final_answer", "content": "ok"},
        {"type": "a2ui", "content": "{}"},
    ]


@pytest.mark.asyncio
async def test_legacy_sse_decoder_ignores_malformed_blocks_and_reads_trailing_data():
    async def chunks():
        yield "event: ping\n\n"
        yield "data: not-json\n\n"
        yield 'data: {"type":"final_answer","content":"tail"}'

    values = [value async for value in _iter_legacy_payloads(chunks())]
    assert values == [{"type": "final_answer", "content": "tail"}]

    async def malformed_tail():
        yield "data: not-json"

    assert [value async for value in _iter_legacy_payloads(malformed_tail())] == []


@pytest.mark.asyncio
async def test_run_stream_encodes_core_events(monkeypatch):
    async def body():
        yield 'data: {"type":"conversation_created","content":{"conversation_id":42}}\n\n'
        yield 'data: {"type":"a2ui","content":"{\\"surfaceId\\":\\"s\\"}"}\n\n'
        yield 'data: {"type":"final_answer","content":"hello"}\n\n'

    async def fake_run_agent_stream(**kwargs):
        kwargs["agent_request"].conversation_id = 42
        return StreamingResponse(body(), media_type="text/event-stream")

    monkeypatch.setattr("services.ag_ui_service.run_agent_stream", fake_run_agent_stream)
    response = await run_agent_agui_stream(
        _run_input(nexent={"agentId": 10}), SimpleNamespace(), "token"
    )
    output = "".join([chunk async for chunk in response.body_iterator])

    assert response.headers["conversation_id"] == "42"
    assert '"type":"RUN_STARTED"' in output
    assert "nexent.conversation.created" in output
    assert "nexent.a2ui" in output
    assert '"delta":"hello"' in output
    assert '"type":"RUN_FINISHED"' in output


@pytest.mark.asyncio
async def test_non_streaming_legacy_response_becomes_run_error(monkeypatch):
    async def fake_run_agent_stream(**_kwargs):
        return JSONResponse({"status": "completed"})

    monkeypatch.setattr("services.ag_ui_service.run_agent_stream", fake_run_agent_stream)
    response = await run_agent_agui_stream(_run_input(), SimpleNamespace(), "token")
    output = "".join([chunk async for chunk in response.body_iterator])
    assert "NEXENT_AGUI_ERROR" in output
    assert "RUN_FINISHED" not in output


@pytest.mark.asyncio
async def test_stream_adaptation_failure_closes_messages_and_returns_run_error(monkeypatch):
    async def body():
        yield 'data: {"type":"final_answer","content":"partial"}\n\n'
        raise RuntimeError("stream failed")

    async def fake_run_agent_stream(**_kwargs):
        return StreamingResponse(body(), media_type="text/event-stream")

    monkeypatch.setattr("services.ag_ui_service.run_agent_stream", fake_run_agent_stream)
    response = await run_agent_agui_stream(_run_input(), SimpleNamespace(), "token")
    output = "".join([chunk async for chunk in response.body_iterator])

    assert '"type":"TEXT_MESSAGE_END"' in output
    assert "Agent stream encoding failed" in output
    assert "RUN_FINISHED" not in output
