# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Displayed model bodies retain provider fields rather than internal message DTOs."""

import json
from types import SimpleNamespace

import pytest
from test_model_attempt_capture import capture as capture  # noqa: PLC0414
from test_model_service import Sender, complete
from test_model_service import setup as setup  # noqa: PLC0414

from nexent.core.model_service.http_contracts import RawHttpResponse
from nexent.core.model_service.service import ModelService
from nexent.core.model_service.sse import SSEEvent
from nexent.monitor.model_attempt import ModelAttemptSession


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_model_service_bodies_match_actual_http_request_and_response(
    capture, setup, asynchronous
):
    from unittest.mock import Mock

    manager, local, _ = capture
    profile, request, limiter, _ = setup
    response = complete()
    sender = Sender([response])
    manager.trace_llm_request = lambda *a, **kw: manager.tracer.start_as_current_span(
        "logical"
    )
    manager.add_span_event = Mock()
    manager.set_span_attributes = Mock()
    manager.set_openinference_output = Mock()
    service = ModelService(lambda _: sender, limiter=limiter, monitoring=manager)
    result = (
        await service.ainvoke(request, profile)
        if asynchronous
        else service.invoke(request, profile)
    )
    assert result.content_parts[0]["text"] == "answer"
    attempt = next(s for s in local.get_finished_spans() if s.name == "model.attempt")
    assert json.loads(attempt.attributes["input.value"]) == json.loads(
        sender.calls[0].body_bytes
    )
    assert json.loads(
        attempt.attributes["nexent.provider.response.value"]
    ) == json.loads(response.body)
    assert len(sender.calls) == 1 and not limiter._entries


def test_stream_response_merges_only_received_fields_and_preserves_native_tool_arguments(
    capture,
):
    manager, local, _ = capture
    frames = [
        {
            "id": "response-1",
            "model": "actual-model",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "role": "assistant",
                        "reasoning_content": "分析",
                        "tool_calls": [
                            {
                                "index": 1,
                                "id": "call-2",
                                "type": "function",
                                "function": {"name": "wea", "arguments": '{"city":"'},
                            }
                        ],
                    },
                    "finish_reason": None,
                }
            ],
        },
        {
            "id": "response-1",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "reasoning_content": "完成",
                        "tool_calls": [
                            {
                                "index": 1,
                                "function": {"name": "ther", "arguments": '北京"}'},
                            },
                            {
                                "index": 0,
                                "id": "call-1",
                                "function": {"name": "lookup", "arguments": "{}"},
                            },
                        ],
                    },
                    "finish_reason": "tool_calls",
                    "provider_detail": {"code": 7},
                }
            ],
        },
        {
            "id": "response-1",
            "choices": [],
            "usage": {"prompt_tokens": 3, "completion_tokens": 5},
        },
    ]
    with manager.tracer.start_as_current_span("logical") as logical:
        session = ModelAttemptSession(manager, "model", logical, "request", 1)
        session.begin({"messages": []}, semantic={"internal": "must not be displayed"})
        for value in frames:
            session.frame(SSEEvent(json.dumps(value, ensure_ascii=False)))
            assert "nexent.provider.response.value" not in session.span.attributes
        session.frame(SSEEvent("[DONE]"))
        session.end(cancelled=True)
    attempt = next(s for s in local.get_finished_spans() if s.name == "model.attempt")
    output = json.loads(attempt.attributes["nexent.provider.response.value"])
    choice = output["choices"][0]
    assert choice["delta"] == {
        "role": "assistant",
        "reasoning_content": "分析完成",
        "tool_calls": [
            {
                "index": 0,
                "id": "call-1",
                "function": {"name": "lookup", "arguments": "{}"},
            },
            {
                "index": 1,
                "id": "call-2",
                "type": "function",
                "function": {"name": "weather", "arguments": '{"city":"北京"}'},
            },
        ],
    }
    assert choice["finish_reason"] == "tool_calls" and choice["provider_detail"] == {
        "code": 7
    }
    assert output["usage"] == frames[-1]["usage"] and output["model"] == "actual-model"
    assert set(output) == {"id", "model", "choices", "usage"}
    assert attempt.attributes["nexent.business_status"] == "cancelled"
    assert json.loads(attempt.attributes["input.value"]) == {"messages": []}


@pytest.mark.parametrize("failed", [False, True])
def test_raw_response_retains_body_without_transport_or_capture_wrapper(
    capture, failed
):
    manager, local, _ = capture
    body = (
        {"error": {"message": "denied secret-value"}}
        if failed
        else {"choices": [], "custom": [1, 2]}
    )
    with manager.tracer.start_as_current_span("logical") as logical:
        session = ModelAttemptSession(manager, "model", logical, "request", 1)
        session.begin({"messages": []})
        session.raw_response(
            RawHttpResponse(
                400 if failed else 200, {}, json.dumps(body).encode(), ("secret-value",)
            )
        )
        if failed:
            session.fail({"category": "MODEL_PERMISSION"})
        else:
            session.complete(
                {"content_parts": [], "message_id": "internal", "provider_metadata": {}}
            )
            session.end()
    attempt = next(s for s in local.get_finished_spans() if s.name == "model.attempt")
    expected = {"error": {"message": "denied [redacted]"}} if failed else body
    assert json.loads(attempt.attributes["nexent.provider.response.value"]) == expected


def test_legacy_chunk_omits_sdk_defaults_and_keeps_provider_extensions(capture):
    from openai.types.chat import ChatCompletionChunk

    manager, local, _ = capture
    values = [
        {
            "id": "native",
            "created": 1,
            "object": "chat.completion.chunk",
            "model": "model",
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": "答", "reasoning_content": "思考"},
                    "finish_reason": None,
                }
            ],
            "vendor": {"tag": "v1"},
        },
        {
            "id": "native",
            "created": 1,
            "object": "chat.completion.chunk",
            "model": "model",
            "choices": [
                {"index": 0, "delta": {"content": "案"}, "finish_reason": "stop"}
            ],
        },
    ]
    with manager.tracer.start_as_current_span("logical") as logical:
        session = ModelAttemptSession(manager, "model", logical, "request", 1)
        session.begin({"messages": []})
        for value in values:
            session.legacy_chunk(ChatCompletionChunk.model_validate(value))
        session.legacy_complete("rewritten internal answer", "stop")
        session.end()
    attempt = next(s for s in local.get_finished_spans() if s.name == "model.attempt")
    response = json.loads(attempt.attributes["nexent.provider.response.value"])
    expected = {
        **values[0],
        "choices": [
            {
                "index": 0,
                "delta": {"content": "答案", "reasoning_content": "思考"},
                "finish_reason": "stop",
            }
        ],
    }
    assert response == expected


def test_stream_body_scrubs_credentials_split_across_frames(capture):
    manager, local, _ = capture
    with manager.tracer.start_as_current_span("logical") as logical:
        session = ModelAttemptSession(manager, "model", logical, "request", 1)
        session.begin({"messages": []})
        for text in ["private-", "credential"]:
            session.frame(
                SSEEvent(
                    json.dumps({"choices": [{"index": 0, "delta": {"content": text}}]}),
                    sensitive_values=("private-credential",),
                )
            )
        session.end(cancelled=True)
    attempt = next(s for s in local.get_finished_spans() if s.name == "model.attempt")
    output = json.loads(attempt.attributes["nexent.provider.response.value"])
    assert output["choices"][0]["delta"]["content"] == "[redacted]"


def test_budget_does_not_publish_internal_message_as_provider_body(capture):
    manager, local, _ = capture
    manager._config.local_span_processor = SimpleNamespace(run_queue_max_bytes=300)
    with manager.tracer.start_as_current_span("logical") as logical:
        session = ModelAttemptSession(manager, "model", logical, "request", 1)
        session.begin({"messages": []})
        session.frame(
            SSEEvent(
                json.dumps(
                    {"choices": [{"index": 0, "delta": {"content": "a" * 1000}}]}
                )
            )
        )
        session.complete({"content_parts": [{"type": "text", "text": "internal"}]})
        session.end()
    attempt = next(s for s in local.get_finished_spans() if s.name == "model.attempt")
    assert "nexent.provider.response.value" not in attempt.attributes
    assert attempt.attributes["nexent.provider.response.format"] == "provider_json"
    assert attempt.attributes["nexent.availability.output"] == "not_captured"
    assert attempt.attributes["nexent.business_status"] == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_service_stream_output_keeps_native_body_in_both_execution_modes(
    capture, setup, asynchronous
):
    from unittest.mock import Mock

    manager, local, _ = capture
    profile, request, limiter, _ = setup
    values = [
        {
            "id": "native",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": "你好"},
                    "finish_reason": None,
                }
            ],
        },
        {
            "id": "native",
            "choices": [
                {"index": 0, "delta": {"content": "世界"}, "finish_reason": "stop"}
            ],
        },
    ]
    sender = Sender(
        [[*(SSEEvent(json.dumps(value)) for value in values), SSEEvent("[DONE]")]]
    )
    manager.trace_llm_request = lambda *a, **kw: manager.tracer.start_as_current_span(
        "logical"
    )
    manager.add_span_event = Mock()
    manager.set_span_attributes = Mock()
    manager.set_openinference_output = Mock()
    service = ModelService(lambda _: sender, limiter=limiter, monitoring=manager)
    request = request.model_copy(update={"stream": True})
    if asynchronous:
        async with service.astream(request, profile) as events:
            received = [event async for event in events]
    else:
        with service.stream(request, profile) as events:
            received = list(events)
    assert [e.delta for e in received if e.type == "text_delta"] == ["你好", "世界"]
    attempt = next(s for s in local.get_finished_spans() if s.name == "model.attempt")
    assert json.loads(attempt.attributes["input.value"]) == json.loads(
        sender.calls[0].body_bytes
    )
    assert json.loads(attempt.attributes["nexent.provider.response.value"]) == {
        "id": "native",
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": "你好世界"},
                "finish_reason": "stop",
            }
        ],
    }
    assert sender.closed == 1 and not limiter._entries


def test_repeated_stream_metadata_does_not_consume_budget_for_every_frame():
    from nexent.monitor.provider_response import ProviderResponse

    remaining = 12000

    def reserve(size):
        nonlocal remaining
        remaining -= size
        return remaining >= 0

    response = ProviderResponse(reserve)
    for _ in range(1000):
        response.frame(
            {
                "id": "provider-response-" * 100,
                "choices": [{"index": 0, "delta": {"content": "a"}}],
            }
        )
    assert response.seen and not response.failed
    assert response.value()["choices"][0]["delta"]["content"] == "a" * 1000


def test_non_json_http_error_body_and_absent_stream_body_remain_distinct(capture):
    manager, local, _ = capture
    with manager.tracer.start_as_current_span("logical") as logical:
        session = ModelAttemptSession(manager, "model", logical, "request", 2)
        session.begin({"messages": []})
        session.raw_response(RawHttpResponse(502, {}, b"upstream unavailable"))
        session.fail({"category": "MODEL_UPSTREAM"})
        session.begin({"messages": []})
        session.frame(SSEEvent("[DONE]"))
        session.end(cancelled=True)
    first, second = [s for s in local.get_finished_spans() if s.name == "model.attempt"]
    assert (
        json.loads(first.attributes["nexent.provider.response.value"])
        == "upstream unavailable"
    )
    assert "nexent.provider.response.value" not in second.attributes
    assert second.attributes["nexent.availability.output"] == "not_returned"


def test_duplicate_http_observation_and_malformed_choice_do_not_break_capture():
    from nexent.monitor.provider_response import ProviderResponse

    charged = []
    response = ProviderResponse(lambda size: charged.append(size) or True)
    response.response({"error": "same observed body"})
    size = sum(charged)
    response.response({"error": "same observed body"})
    assert sum(charged) == size
    response = ProviderResponse(lambda _: True)
    response.frame(
        {
            "choices": [
                {"index": "invalid", "delta": {"content": "body"}},
                {"index": 0, "delta": {"content": "valid"}},
            ]
        }
    )
    assert response.value()["choices"] == [
        {"index": "invalid", "delta": {"content": "body"}},
        {"index": 0, "delta": {"content": "valid"}},
    ]


def test_excessive_native_nesting_marks_output_unavailable_without_failing_business(
    capture,
):
    manager, local, _ = capture
    body = {}
    for _ in range(70):
        body = {"extension": body}
    with manager.tracer.start_as_current_span("logical") as logical:
        session = ModelAttemptSession(manager, "model", logical, "request", 1)
        session.begin({"messages": []})
        session.frame(SSEEvent(json.dumps(body)))
        session.complete(
            {"content_parts": [{"type": "text", "text": "business succeeded"}]}
        )
        session.end()
    attempt = next(s for s in local.get_finished_spans() if s.name == "model.attempt")
    assert "nexent.provider.response.value" not in attempt.attributes
    assert attempt.attributes["nexent.availability.output"] == "not_captured"
    assert attempt.attributes["nexent.business_status"] == "completed"
    assert attempt.attributes["nexent.trajectory.gap"]
