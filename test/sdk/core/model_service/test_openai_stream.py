# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Controlled stream state without network, retry or tool execution."""

import json

import pytest
from nexent.core.model_service.adapters.openai_chat import (
    ModelAdapterError,
    OpenAIChatAdapter,
)
from nexent.core.model_service.adapters.openai_stream import OpenAIStreamDecoder
from nexent.core.model_service.contracts import ModelMessage, ModelRequest
from nexent.core.model_service.sse import SSEEvent


@pytest.fixture
def stream_request(openai_profile):
    return ModelRequest(
        request_id="r1",
        outlet_id=openai_profile.outlet_id,
        config_revision=openai_profile.config_revision,
        messages=[
            ModelMessage(
                semantic_role="user", content_parts=[{"type": "text", "text": "hello"}]
            )
        ],
        stream=True,
    )


def frame(delta=None, finish=None, **extra):
    body = {
        "id": "response-id",
        "model": "provider-exact",
        "choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish}],
    }
    return SSEEvent(json.dumps(body | extra))


def tool(index, name=None, arguments=None, call_id=None):
    raw = {"index": index, "function": {}}
    if name is not None:
        raw["function"]["name"] = name
    if arguments is not None:
        raw["function"]["arguments"] = arguments
    if call_id is not None:
        raw["id"] = call_id
    return raw


def test_interleaved_reasoning_text_and_tools_complete_with_stable_ids(
    openai_profile, stream_request
):
    decoder = OpenAIStreamDecoder(stream_request, openai_profile)
    events = decoder.push(frame({"role": "assistant", "reasoning_content": "thinking"}))
    events += decoder.push(
        frame(
            {
                "content": "body",
                "tool_calls": [
                    tool(2, "sea", '{"q":', "call-two"),
                    tool(0, "calc", '{"n":', "call-zero"),
                ],
            }
        )
    )
    events += decoder.push(
        frame(
            {
                "tool_calls": [
                    tool(0, arguments="0}"),
                    tool(2, name="rch", arguments='"x"}'),
                ]
            },
            finish="tool_calls",
        )
    )
    assert not any(event.type == "message_completed" for event in events)
    assert all(
        event.tool_call_delta is None
        or not hasattr(event.tool_call_delta, "parsed_arguments")
        for event in events
    )
    events += decoder.push(
        SSEEvent(
            json.dumps(
                {
                    "choices": [],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 4,
                        "total_tokens": 14,
                    },
                }
            )
        )
    )
    events += decoder.push(SSEEvent("[DONE]"))
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert len({event.message_id for event in events}) == 1
    assert events[0].type == "reasoning_delta" and events[0].delta == "thinking"
    assert events[1].type == "text_delta" and events[1].content_kind == "text"
    complete = events[-1].message
    assert (
        events[-1].type == "message_completed"
        and complete.message_id == events[-1].message_id
    )
    assert complete.reasoning_parts == [{"type": "text", "text": "thinking"}]
    assert complete.content_parts == [{"type": "text", "text": "body"}]
    assert [
        (call.index, call.name, call.provider_call_id, call.parsed_arguments)
        for call in complete.tool_calls
    ] == [(0, "calc", "call-zero", {"n": 0}), (2, "search", "call-two", {"q": "x"})]
    ids = {
        event.tool_call_delta.index: event.tool_call_delta.local_call_id
        for event in events
        if event.type == "tool_call_delta"
    }
    assert all(call.local_call_id == ids[call.index] for call in complete.tool_calls)
    assert complete.usage.total_tokens == 14
    assert decoder.finish() == []
    with pytest.raises(ModelAdapterError, match="^MODEL_STREAM_CLOSED$"):
        decoder.push(frame({"content": "late"}))


def test_refusal_and_unknown_delta_do_not_become_body_or_tool_calls(
    openai_profile, stream_request
):
    decoder = OpenAIStreamDecoder(stream_request, openai_profile)
    events = decoder.push(
        frame(
            {"refusal": "no", "future_field": {"data": "retained"}},
            finish="content_filter",
        )
    )
    assert events[0].content_kind == "refusal"
    complete = decoder.push(SSEEvent("[DONE]"))[0].message
    assert (
        complete.refusal == "no"
        and complete.content_parts == []
        and complete.tool_calls == []
    )
    assert complete.provider_metadata["unmapped_delta_fields"] == [
        {"future_field": {"data": "retained"}}
    ]


@pytest.mark.parametrize(
    "mode",
    [
        "no_finish",
        "no_done",
        "only_done",
        "tool_missing_name",
        "tool_missing_id",
        "tool_finish_without_calls",
    ],
)
def test_incomplete_stream_never_promotes_tools_to_completion(
    openai_profile, stream_request, mode
):
    decoder = OpenAIStreamDecoder(stream_request, openai_profile)
    if mode == "no_finish":
        assert decoder.push(frame({"content": "partial"}))[0].type == "text_delta"
    elif mode == "no_done":
        decoder.push(frame({"content": "body"}, finish="stop"))
    elif mode.startswith("tool_missing"):
        decoder.push(
            frame(
                {
                    "tool_calls": [
                        tool(
                            0,
                            name="search" if mode.endswith("id") else None,
                            arguments="{}",
                            call_id="id" if mode.endswith("name") else None,
                        )
                    ]
                },
                finish="tool_calls",
            )
        )
    elif mode == "tool_finish_without_calls":
        decoder.push(frame({}, finish="tool_calls"))
    with pytest.raises(ModelAdapterError):
        if mode in {"no_finish", "no_done"}:
            decoder.finish()
        else:
            decoder.push(SSEEvent("[DONE]"))
    with pytest.raises(ModelAdapterError, match="^MODEL_STREAM_CLOSED$"):
        decoder.push(frame({"content": "repair"}, finish="stop"))


def test_explicit_optional_done_still_requires_finish(openai_profile, stream_request):
    decoder = OpenAIStreamDecoder(stream_request, openai_profile, require_done=False)
    decoder.push(frame({"content": "complete"}, finish="provider_new_finish"))
    complete = decoder.finish()[0]
    assert complete.message.finish_reason == "provider_new_finish"
    assert complete.message.usage.total_tokens is None
    missing = OpenAIStreamDecoder(stream_request, openai_profile, require_done=False)
    with pytest.raises(ModelAdapterError, match="^MODEL_RESPONSE_INCOMPLETE$"):
        missing.finish()


@pytest.mark.parametrize(
    "delta",
    [
        {"content": 2},
        {"reasoning_content": []},
        {"role": "user"},
        {"tool_calls": False},
        {"tool_calls": [{"index": False}]},
        {"tool_calls": [{"index": 0, "function": {"arguments": 1}}]},
    ],
)
def test_invalid_delta_types_are_not_coerced(openai_profile, stream_request, delta):
    decoder = OpenAIStreamDecoder(stream_request, openai_profile)
    with pytest.raises(ModelAdapterError):
        decoder.push(frame(delta))


@pytest.mark.parametrize(
    "data",
    [
        '{"choices":[],"choices":[]}',
        '{"choices":[false]}',
        '{"choices":[],"x":NaN}',
        "dummy-private",
        "[]",
    ],
)
def test_invalid_json_and_envelope_are_sanitized(openai_profile, stream_request, data):
    decoder = OpenAIStreamDecoder(stream_request, openai_profile)
    with pytest.raises(ModelAdapterError, match="^MODEL_RESPONSE_INVALID$") as caught:
        decoder.push(SSEEvent(data))
    assert "dummy-private" not in str(caught.value)


def test_identity_conflicts_and_post_finish_delta_fail(openai_profile, stream_request):
    decoder = OpenAIStreamDecoder(stream_request, openai_profile)
    decoder.push(frame({"content": "visible"}))
    with pytest.raises(ModelAdapterError, match="^MODEL_STREAM_IDENTITY_CONFLICT$"):
        decoder.push(frame({"content": "different"}, id="other-response"))
    decoder = OpenAIStreamDecoder(stream_request, openai_profile)
    decoder.push(frame({}, finish="stop"))
    with pytest.raises(ModelAdapterError, match="^MODEL_STREAM_AFTER_FINISH$"):
        decoder.push(frame({"content": "late"}))


def test_tool_id_conflict_is_not_a_second_execution_identity(
    openai_profile, stream_request
):
    decoder = OpenAIStreamDecoder(stream_request, openai_profile)
    decoder.push(frame({"tool_calls": [tool(0, "search", "{", "original")]}))
    with pytest.raises(ModelAdapterError, match="^MODEL_STREAM_IDENTITY_CONFLICT$"):
        decoder.push(frame({"tool_calls": [tool(0, call_id="other")]}))


def test_total_stream_and_tool_limits_cannot_be_bypassed_by_small_chunks(
    openai_profile, stream_request
):
    sample = frame({"content": "中"})
    decoder = OpenAIStreamDecoder(
        stream_request, openai_profile, max_message_bytes=len(sample.data.encode()) * 2
    )
    decoder.push(sample)
    decoder.push(sample)
    with pytest.raises(ModelAdapterError, match="^MODEL_RESPONSE_TOO_LARGE$"):
        decoder.push(sample)
    decoder = OpenAIStreamDecoder(stream_request, openai_profile, max_tool_calls=1)
    decoder.push(frame({"tool_calls": [tool(100000, "one", "{}", "one")]}))
    with pytest.raises(ModelAdapterError, match="^MODEL_TOOL_CALL_LIMIT$"):
        decoder.push(frame({"tool_calls": [tool(2, "two", "{}", "two")]}))


def test_duplicate_usage_is_explicit_without_replacing_reported_values(
    openai_profile, stream_request
):
    decoder = OpenAIStreamDecoder(stream_request, openai_profile)
    first = decoder.push(frame({}, finish="stop", usage={"prompt_tokens": 0}))
    assert first[0].usage.input_tokens == 0
    with pytest.raises(ModelAdapterError, match="^MODEL_USAGE_CONFLICT$"):
        decoder.push(
            SSEEvent(json.dumps({"choices": [], "usage": {"prompt_tokens": 1}}))
        )


@pytest.mark.parametrize(
    "options", [{"require_done": 1}, {"max_message_bytes": 0}, {"max_tool_calls": True}]
)
def test_invalid_limits_or_protocol_declarations_fail(
    openai_profile, stream_request, options
):
    with pytest.raises(ValueError):
        OpenAIStreamDecoder(stream_request, openai_profile, **options)


@pytest.mark.asyncio
async def test_sync_async_adapter_interfaces_share_ordered_completion_and_stop_at_done(
    openai_profile, stream_request
):
    frames = [frame({"content": "body"}, finish="stop"), SSEEvent("[DONE]")]

    def sync_frames():
        yield from frames
        pytest.fail("The adapter should stop at the declared completion marker")

    async def async_frames():
        for item in frames:
            yield item
        pytest.fail("The adapter should stop at the declared completion marker")

    adapter = OpenAIChatAdapter()
    sync = list(adapter.decode_stream(sync_frames(), stream_request, openai_profile))
    asynchronous = [
        event
        async for event in adapter.adecode_stream(
            async_frames(), stream_request, openai_profile
        )
    ]
    assert (
        [event.type for event in sync]
        == [event.type for event in asynchronous]
        == ["text_delta", "message_completed"]
    )
    assert (
        sync[-1].message.content_parts
        == asynchronous[-1].message.content_parts
        == [{"type": "text", "text": "body"}]
    )


@pytest.mark.asyncio
async def test_both_adapter_interfaces_report_truncated_stream(
    openai_profile, stream_request
):
    adapter = OpenAIChatAdapter()
    with pytest.raises(ModelAdapterError, match="^MODEL_RESPONSE_INCOMPLETE$"):
        list(
            adapter.decode_stream(
                [frame({"content": "partial"})], stream_request, openai_profile
            )
        )

    async def partial():
        yield frame({"content": "partial"})

    with pytest.raises(ModelAdapterError, match="^MODEL_RESPONSE_INCOMPLETE$"):
        [
            event
            async for event in adapter.adecode_stream(
                partial(), stream_request, openai_profile
            )
        ]
