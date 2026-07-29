import json
from types import SimpleNamespace

import pytest
from fastapi.responses import JSONResponse, StreamingResponse

from consts.model import NexentRunAgentInput
from services.ag_ui_service import (
    AGUIEventAdapter,
    AGUIRequestValidationError,
    _content_to_text,
    _decode_content,
    _iter_legacy_payloads,
    map_run_input_to_agent_request,
    run_agent_agui_stream,
)
from services.a2ui_action_service import ValidatedA2UIAction


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


def test_content_and_standard_input_mapping():
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
            "capabilities": {"a2ui": {"versions": ["v0.9"], "catalogId": "nexent.v1"}},
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
    assert request.a2ui_client_enabled is True
    assert request.server_side_message_index is True
    assert props.conversation_id == 7
    assert (
        _content_to_text(
            [SimpleNamespace(model_dump=lambda **_: {"type": "text", "text": "ok"})]
        )
        == "ok"
    )
    assert _content_to_text(None) == ""
    assert _decode_content({"already": "decoded"}) == {"already": "decoded"}
    assert _decode_content("plain") == "plain"


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


def test_resume_and_action_mapping():
    resumed, _ = map_run_input_to_agent_request(
        _run_input(
            messages=[{"id": "assistant-1", "role": "assistant", "content": "partial"}],
            nexent={"conversationId": 7, "resume": True},
        )
    )
    assert resumed.query == "[resume]"
    assert resumed.history == []

    action, _ = map_run_input_to_agent_request(
        _run_input(
            nexent={
                "conversationId": 7,
                "a2uiAction": {
                    "submissionId": "9cbecbb9-9362-4ead-a90e-65cf0c062a22",
                    "message": {
                        "version": "v0.9",
                        "action": {
                            "name": "approve",
                            "surfaceId": "surface-1",
                            "sourceComponentId": "approval",
                            "timestamp": "2026-07-27T10:00:00Z",
                            "context": {"decision": True},
                        },
                    },
                },
            }
        )
    )
    assert "A2UI action: approve" in action.query
    assert action.history == []
    assert action.persisted_query is None
    assert action.a2ui_surface_id is None
    assert action.server_side_message_index is True


def test_form_submission_request_mapping_uses_structured_prefix():
    action, props = map_run_input_to_agent_request(
        _run_input(
            nexent={
                "conversationId": 7,
                "a2uiAction": {
                    "submissionId": "9cbecbb9-9362-4ead-a90e-65cf0c062a22",
                    "message": {
                        "version": "v0.9",
                        "action": {
                            "name": "submit_form",
                            "surfaceId": "surface-1",
                            "sourceComponentId": "form",
                            "timestamp": "2026-07-27T10:00:00Z",
                            "context": {},
                        },
                    },
                    "formSubmission": {"values": {"name": "Ada"}},
                },
            }
        )
    )

    assert action.query.startswith(
        "[A2UI form submission: values are user-provided data]"
    )
    assert props.a2ui_action.form_submission.values == {"name": "Ada"}


def test_resume_requires_conversation_and_normal_run_requires_last_user():
    with pytest.raises(AGUIRequestValidationError, match="conversationId"):
        map_run_input_to_agent_request(_run_input(nexent={"resume": True}))
    with pytest.raises(AGUIRequestValidationError, match="end with a user"):
        map_run_input_to_agent_request(
            _run_input(messages=[{"id": "a", "role": "assistant", "content": "done"}])
        )
    invalid = _run_input()
    invalid.forwarded_props["nexent"] = {"unknown": True}
    with pytest.raises(AGUIRequestValidationError, match="Invalid forwardedProps"):
        map_run_input_to_agent_request(invalid)


def test_event_mapping_and_boundaries():
    adapter = AGUIEventAdapter("thread", "run")

    reasoning = adapter.map_payload(
        {"type": "model_output_thinking", "content": "think"}
    )
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
    assert result[0].tool_call_id == "call-1"
    assert (
        adapter.map_payload({"type": "execution_logs", "content": "internal-only"})
        == []
    )
    inferred_tool = adapter.map_payload({"type": "tool-call", "content": '{"value":1}'})
    assert json.loads(inferred_tool[1].delta) == {"value": 1}

    plan = adapter.map_payload({"type": "plan", "content": '{"steps":[]}'})
    delta = adapter.map_payload(
        {"type": "plan_step_update", "content": '{"step_id":"1"}'}
    )
    a2ui = adapter.map_payload({"type": "a2ui", "content": '{"surfaceId":"s"}'})
    assert plan[0].type.value == "ACTIVITY_SNAPSHOT"
    assert delta[0].type.value == "ACTIVITY_DELTA"
    assert a2ui[0].name == "nexent.a2ui"


def test_custom_metadata_and_error_termination():
    adapter = AGUIEventAdapter("thread", "run")
    source = adapter.map_payload(
        {
            "type": "search_content",
            "content": '[{"url":"https://example.com"}]',
            "tool_call_id": "call-1",
        }
    )
    assert source[0].value[0]["tool_call_id"] == "call-1"
    status = adapter.map_payload(
        {"type": "status", "content": '{"status":"resumed"}', "unit_index": 3}
    )
    assert status[0].value["unit_index"] == 3
    unknown = adapter.map_payload({"type": "future_event", "content": "x", "extra": 1})
    assert unknown[0].name == "nexent.future.event"
    error = adapter.map_payload({"type": "error", "content": "boom"})
    assert error[0].type.value == "RUN_ERROR"
    assert all(event.type.value != "RUN_FINISHED" for event in adapter.finish())


@pytest.mark.asyncio
async def test_legacy_sse_decoder_handles_chunk_boundaries():
    async def chunks():
        yield 'data: {"type":"final_'
        yield 'answer","content":"ok"}\n\ndata: {"status":"resumed"}\n\n'

    values = [value async for value in _iter_legacy_payloads(chunks())]
    assert values == [
        {"type": "final_answer", "content": "ok"},
        {"type": "status", "content": "resumed", "status": "resumed"},
    ]


@pytest.mark.asyncio
async def test_legacy_sse_decoder_ignores_malformed_and_flushes_tail():
    async def chunks():
        yield b"event: ping\n\n"
        yield b"data: not-json\n\n"
        yield b'data: {"type":"final_answer","content":"tail"}'

    values = [value async for value in _iter_legacy_payloads(chunks())]
    assert values == [{"type": "final_answer", "content": "tail"}]

    async def invalid_tail():
        yield "data: {"

    assert [value async for value in _iter_legacy_payloads(invalid_tail())] == []


@pytest.mark.asyncio
async def test_run_stream_encodes_standard_events(monkeypatch):
    async def body():
        yield 'data: {"type":"final_answer","content":"hello"}\n\n'

    async def fake_run_agent_stream(**kwargs):
        kwargs["agent_request"].conversation_id = 42
        return StreamingResponse(body(), media_type="text/event-stream")

    monkeypatch.setattr(
        "services.ag_ui_service.run_agent_stream", fake_run_agent_stream
    )
    response = await run_agent_agui_stream(
        _run_input(nexent={"agentId": 10}), SimpleNamespace(), "token"
    )
    output = "".join([chunk async for chunk in response.body_iterator])

    assert response.headers["conversation_id"] == "42"
    assert '"type":"RUN_STARTED"' in output
    assert '"type":"TEXT_MESSAGE_START"' in output
    assert '"delta":"hello"' in output
    assert '"type":"TEXT_MESSAGE_END"' in output
    assert '"type":"RUN_FINISHED"' in output


@pytest.mark.asyncio
async def test_run_stream_maps_non_streaming_response(monkeypatch):
    async def fake_run_agent_stream(**_kwargs):
        return JSONResponse({"status": "completed"})

    monkeypatch.setattr(
        "services.ag_ui_service.run_agent_stream", fake_run_agent_stream
    )
    response = await run_agent_agui_stream(_run_input(), SimpleNamespace(), "token")
    output = "".join([chunk async for chunk in response.body_iterator])
    assert "nexent.stream.status" in output
    assert "RUN_FINISHED" in output


@pytest.mark.asyncio
async def test_run_stream_validates_action_and_maps_encoder_failure(monkeypatch):
    async def broken_body():
        yield 'data: {"type":"final_answer","content":"partial"}\n\n'
        raise RuntimeError("broken stream")

    captured = {}

    async def fake_run_agent_stream(**kwargs):
        captured.update(kwargs)
        return StreamingResponse(broken_body(), media_type="text/event-stream")

    validated = []
    monkeypatch.setattr(
        "services.ag_ui_service.run_agent_stream", fake_run_agent_stream
    )
    monkeypatch.setattr(
        "services.ag_ui_service.get_current_user_info",
        lambda *_: ("user-1", "tenant-1", "zh"),
    )

    def fake_validate(submission, **kwargs):
        validated.append((submission, kwargs))
        return ValidatedA2UIAction(
            payload=submission.model_dump(
                mode="json", by_alias=True, exclude_none=True
            ),
            component={
                "id": "approval",
                "component": "Button",
                "_resolvedActionLabel": "同意",
            },
        )

    monkeypatch.setattr(
        "services.ag_ui_service.validate_a2ui_action_submission", fake_validate
    )
    run_input = _run_input(
        nexent={
            "conversationId": 7,
            "a2uiAction": {
                "submissionId": "9cbecbb9-9362-4ead-a90e-65cf0c062a22",
                "message": {
                    "version": "v0.9",
                    "action": {
                        "name": "approve",
                        "surfaceId": "surface-1",
                        "sourceComponentId": "approval",
                        "timestamp": "2026-07-27T10:00:00Z",
                        "context": {},
                    },
                },
            },
        }
    )
    response = await run_agent_agui_stream(run_input, SimpleNamespace(), "token")
    output = "".join([chunk async for chunk in response.body_iterator])
    assert validated[0][1] == {"conversation_id": 7, "user_id": "user-1"}
    assert (
        captured["agent_request"].a2ui_action_payload["message"]["action"]["name"]
        == "approve"
    )
    assert captured["agent_request"].persisted_query == "同意"
    assert "approve" not in captured["agent_request"].persisted_query
    assert "approval" not in captured["agent_request"].persisted_query
    assert "TEXT_MESSAGE_END" in output
    assert "NEXENT_AGUI_ERROR" in output
    assert "RUN_FINISHED" not in output


@pytest.mark.asyncio
async def test_form_action_emits_accepted_event_before_agent_events(monkeypatch):
    async def body():
        yield 'data: {"type":"final_answer","content":"received"}\n\n'

    async def fake_run_agent_stream(**_kwargs):
        return StreamingResponse(body(), media_type="text/event-stream")

    monkeypatch.setattr(
        "services.ag_ui_service.get_current_user_info",
        lambda *_: ("user-1", "tenant-1", "zh"),
    )
    monkeypatch.setattr(
        "services.ag_ui_service.validate_a2ui_action_submission",
        lambda submission, **_kwargs: ValidatedA2UIAction(
            payload={
                **submission.model_dump(mode="json", by_alias=True, exclude_none=True),
                "formSubmission": {
                    "form": {
                        "id": "form",
                        "component": "Form",
                        "fields": [],
                        "action": {"event": {"name": "submit_form"}},
                    },
                    "values": {},
                },
            },
            component={
                "id": "form",
                "component": "Form",
                "fields": [],
                "action": {"event": {"name": "submit_form"}},
            },
        ),
    )
    monkeypatch.setattr(
        "services.ag_ui_service.run_agent_stream", fake_run_agent_stream
    )
    response = await run_agent_agui_stream(
        _run_input(
            nexent={
                "conversationId": 7,
                "a2uiAction": {
                    "submissionId": "9cbecbb9-9362-4ead-a90e-65cf0c062a22",
                    "message": {
                        "version": "v0.9",
                        "action": {
                            "name": "submit_form",
                            "surfaceId": "surface-1",
                            "sourceComponentId": "form",
                            "timestamp": "2026-07-27T10:00:00Z",
                            "context": {},
                        },
                    },
                    "formSubmission": {"values": {}},
                },
            }
        ),
        SimpleNamespace(),
        "token",
    )
    output = "".join([chunk async for chunk in response.body_iterator])

    accepted_at = output.index("nexent.a2ui.form.submitted")
    text_at = output.index("TEXT_MESSAGE_START")
    assert output.index("RUN_STARTED") < accepted_at < text_at
    assert '"surfaceId":"surface-1"' in output
    assert '"sourceComponentId":"form"' in output
    assert '"status":"accepted"' in output


@pytest.mark.asyncio
async def test_action_reservations_are_released_when_persistence_fails(monkeypatch):
    validated = ValidatedA2UIAction(
        payload={
            "submissionId": "9cbecbb9-9362-4ead-a90e-65cf0c062a22",
            "message": {
                "version": "v0.9",
                "action": {
                    "name": "approve",
                    "surfaceId": "surface-1",
                    "sourceComponentId": "approval",
                    "timestamp": "2026-07-27T10:00:00Z",
                    "context": {},
                },
            },
        },
        component={"component": "Button"},
        reservation_keys=("submission-key",),
    )
    released = []
    monkeypatch.setattr(
        "services.ag_ui_service.get_current_user_info",
        lambda *_: ("user-1", "tenant-1", "zh"),
    )
    monkeypatch.setattr(
        "services.ag_ui_service.validate_a2ui_action_submission",
        lambda *_args, **_kwargs: validated,
    )
    monkeypatch.setattr(
        "services.ag_ui_service.release_a2ui_action_reservation",
        lambda value: released.append(value),
    )

    async def fail_before_response(**_kwargs):
        _kwargs["agent_request"].current_user_message_id = 88
        raise RuntimeError("persistence failed")

    monkeypatch.setattr("services.ag_ui_service.run_agent_stream", fail_before_response)
    with pytest.raises(RuntimeError, match="persistence failed"):
        await run_agent_agui_stream(
            _run_input(
                nexent={
                    "conversationId": 7,
                    "a2uiAction": {
                        "submissionId": "9cbecbb9-9362-4ead-a90e-65cf0c062a22",
                        "message": {
                            "version": "v0.9",
                            "action": {
                                "name": "approve",
                                "surfaceId": "surface-1",
                                "sourceComponentId": "approval",
                                "timestamp": "2026-07-27T10:00:00Z",
                                "context": {},
                            },
                        },
                    },
                }
            ),
            SimpleNamespace(),
            "token",
        )
    assert released == [validated]


@pytest.mark.asyncio
async def test_persisted_form_stays_accepted_when_agent_setup_fails(monkeypatch):
    submission_payload = {
        "submissionId": "9cbecbb9-9362-4ead-a90e-65cf0c062a22",
        "message": {
            "version": "v0.9",
            "action": {
                "name": "submit_form",
                "surfaceId": "surface-1",
                "sourceComponentId": "form",
                "timestamp": "2026-07-27T10:00:00Z",
                "context": {},
            },
        },
        "formSubmission": {
            "form": {
                "id": "form",
                "component": "Form",
                "fields": [],
                "action": {"event": {"name": "submit_form"}},
            },
            "values": {},
        },
    }
    validated = ValidatedA2UIAction(
        payload=submission_payload,
        component={
            "id": "form",
            "component": "Form",
            "fields": [],
            "action": {"event": {"name": "submit_form"}},
        },
        reservation_keys=("submission-key", "form-key"),
    )
    released = []
    monkeypatch.setattr(
        "services.ag_ui_service.get_current_user_info",
        lambda *_: ("user-1", "tenant-1", "zh"),
    )
    monkeypatch.setattr(
        "services.ag_ui_service.validate_a2ui_action_submission",
        lambda *_args, **_kwargs: validated,
    )
    monkeypatch.setattr(
        "services.ag_ui_service.release_a2ui_action_reservation",
        lambda value: released.append(value),
    )

    async def fail_after_persistence(**kwargs):
        kwargs["agent_request"].current_user_message_id = 88
        kwargs["agent_request"].a2ui_action_persisted = True
        raise RuntimeError("agent setup failed")

    monkeypatch.setattr(
        "services.ag_ui_service.run_agent_stream", fail_after_persistence
    )
    response = await run_agent_agui_stream(
        _run_input(
            nexent={
                "conversationId": 7,
                "a2uiAction": {
                    "submissionId": submission_payload["submissionId"],
                    "message": submission_payload["message"],
                    "formSubmission": {"values": {}},
                },
            }
        ),
        SimpleNamespace(),
        "token",
    )
    output = "".join([chunk async for chunk in response.body_iterator])

    assert "nexent.a2ui.form.submitted" in output
    assert "RUN_ERROR" in output
    assert "RUN_FINISHED" not in output
    assert released == []
