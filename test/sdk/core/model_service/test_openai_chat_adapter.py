# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Isolated request/response protocol proof, without sending or executing tools."""

import json
from uuid import UUID

import pytest
from nexent.core.model_service.adapters.openai_chat import (
    ModelAdapterError,
    OpenAIChatAdapter,
)
from nexent.core.model_service.contracts import (
    ModelMessage,
    ModelRequest,
    ToolCall,
    ToolDefinition,
)
from nexent.core.model_service.http_contracts import RawHttpResponse


@pytest.fixture
def profile(openai_profile):
    return openai_profile


def request(profile, **changes):
    return ModelRequest(
        **(
            {
                "request_id": "r1",
                "outlet_id": profile.outlet_id,
                "config_revision": profile.config_revision,
                "messages": [
                    ModelMessage(
                        semantic_role="user_input",
                        content_parts=[{"type": "text", "text": "Hello"}],
                    )
                ],
            }
            | changes
        )
    )


def response(message=None, finish="stop", **changes):
    body = {
        "id": "response-1",
        "model": "exact-response-model",
        "choices": [
            {
                "index": 0,
                "message": message
                if message is not None
                else {"role": "assistant", "content": "Hello"},
                "finish_reason": finish,
            }
        ],
    }
    body.update(changes)
    return RawHttpResponse(200, {}, json.dumps(body).encode())


def test_prepare_exact_profile_parameters_roles_and_media_without_mutation(profile):
    media = [
        {"type": "text", "text": "View", "cache_control": {"type": "ephemeral"}},
        {"type": "image_url", "image_url": {"url": "https://example.test/image.png"}},
    ]
    req = request(
        profile,
        messages=[
            ModelMessage(
                semantic_role="platform_instruction",
                content_parts=[{"type": "text", "text": "rules"}],
            ),
            ModelMessage(semantic_role="user_input", content_parts=media),
        ],
    )
    prepared = OpenAIChatAdapter().prepare_http_request(req, profile)
    body = json.loads(prepared.body_bytes)
    assert prepared.url == "https://example.test/v1/chat/completions"
    assert body["model"] == "qwen3.5-plus"
    assert body["messages"] == [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": media},
    ]
    assert body["enable_thinking"] is False
    assert req.messages[1].content_parts == media
    assert "api_key" not in body


def test_multiple_text_parts_and_cache_metadata_remain_distinct(profile):
    parts = [{"type": "text", "text": "one"}, {"type": "text", "text": "two"}]
    req = request(
        profile, messages=[ModelMessage(semantic_role="user", content_parts=parts)]
    )
    assert (
        json.loads(OpenAIChatAdapter().prepare_http_request(req, profile).body_bytes)[
            "messages"
        ][0]["content"]
        == parts
    )


def test_decode_separates_content_reasoning_refusal_and_usage_without_double_counting(
    profile,
):
    raw = response(
        {
            "role": "assistant",
            "content": "body",
            "reasoning_content": "thought",
            "refusal": "refused",
            "extra_field": "preserved",
        },
        usage={
            "prompt_tokens": 10,
            "completion_tokens": 3,
            "total_tokens": 13,
            "prompt_tokens_details": {"cached_tokens": 4},
            "completion_tokens_details": {"reasoning_tokens": 2},
        },
    )
    result = OpenAIChatAdapter().decode_response(raw, request(profile), profile)
    assert result.content_parts == [{"type": "text", "text": "body"}]
    assert result.reasoning_parts == [{"type": "text", "text": "thought"}]
    assert result.refusal == "refused"
    assert result.usage.input_tokens == 10 and result.usage.output_tokens == 3
    assert (
        result.usage.total_tokens == 13
        and result.usage.cached_input_tokens == 4
        and result.usage.reasoning_tokens == 2
    )
    assert result.provider_metadata["unmapped_message_fields"] == {
        "extra_field": "preserved"
    }
    assert "thought" not in repr(result)
    assert "body" not in repr(result)


def test_unknown_finish_and_missing_usage_stay_unknown(profile):
    result = OpenAIChatAdapter().decode_response(
        response(finish="new_provider_finish"), request(profile), profile
    )
    assert result.finish_reason == "new_provider_finish"
    assert result.usage.origin == "unknown" and result.usage.total_tokens is None
    partial = OpenAIChatAdapter().decode_response(
        response(usage={"prompt_tokens": 0}), request(profile), profile
    )
    assert partial.usage.input_tokens == 0
    assert partial.usage.total_tokens is None


@pytest.mark.parametrize(
    "arguments,parsed,error",
    [
        ("{}", {}, None),
        ('{"value":0,"flag":false}', {"value": 0, "flag": False}, None),
        ("[1]", None, "INVALID_TOOL_ARGUMENTS"),
        ("{broken", None, "INVALID_TOOL_ARGUMENTS"),
        ('{"x":1,"x":2}', None, "INVALID_TOOL_ARGUMENTS"),
    ],
)
def test_complete_tools_preserve_raw_provider_ids_and_invalid_arguments(
    profile, arguments, parsed, error
):
    raw = response(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "provider-call-id-longer-than-local-uuid-" * 2,
                    "type": "function",
                    "function": {"name": "search", "arguments": arguments},
                }
            ],
        },
        finish="tool_calls",
    )
    result = OpenAIChatAdapter().decode_response(raw, request(profile), profile)
    call = result.tool_calls[0]
    assert isinstance(call.local_call_id, UUID)
    assert call.provider_call_id == "provider-call-id-longer-than-local-uuid-" * 2
    assert (
        call.raw_arguments == arguments
        and call.parsed_arguments == parsed
        and call.argument_error == error
    )
    assert result.content_parts == []


@pytest.mark.parametrize(
    "usage",
    [
        {"prompt_tokens": True},
        {"completion_tokens": -1},
        {"total_tokens": 2.0},
        {"prompt_tokens_details": []},
        {"completion_tokens_details": {"reasoning_tokens": "2"}},
        False,
    ],
)
def test_invalid_usage_is_not_coerced_or_echoed(profile, usage):
    with pytest.raises(ModelAdapterError, match="^MODEL_USAGE_INVALID$"):
        OpenAIChatAdapter().decode_response(
            response(usage=usage), request(profile), profile
        )


@pytest.mark.parametrize(
    "body,category",
    [
        (b'{"choices":[]}', "MODEL_RESPONSE_INVALID"),
        (b'{"choices":[],"choices":[]}', "MODEL_RESPONSE_INVALID"),
        (
            b'{"choices":[{"index":0,"message":{"role":"assistant"},"finish_reason":null}]}',
            "MODEL_RESPONSE_INCOMPLETE",
        ),
        (
            b'{"choices":[{"index":false,"message":{"role":"assistant"},"finish_reason":"stop"}]}',
            "MODEL_RESPONSE_INVALID",
        ),
        (
            b'{"choices":[{"index":0,"message":{"role":"user"},"finish_reason":"stop"}]}',
            "MODEL_RESPONSE_INVALID",
        ),
        (
            b'{"choices":[{"index":0,"message":{"role":"assistant","tool_calls":false},"finish_reason":"stop"}]}',
            "MODEL_TOOL_CALL_INVALID",
        ),
        (b"dummy-private", "MODEL_RESPONSE_INVALID"),
        (b"\xff", "MODEL_RESPONSE_INVALID"),
    ],
)
def test_invalid_response_is_explicit_and_sanitized(profile, body, category):
    with pytest.raises(ModelAdapterError, match=f"^{category}$") as caught:
        OpenAIChatAdapter().decode_response(
            RawHttpResponse(200, {}, body), request(profile), profile
        )
    assert caught.value.__cause__ is None


@pytest.mark.parametrize(
    "role,category",
    [("developer", "MODEL_ROLE_UNSUPPORTED"), ("tool", "MODEL_MESSAGE_INVALID")],
)
def test_unsupported_roles_or_missing_tool_link_are_not_silently_rewritten(
    profile, role, category
):
    with pytest.raises(ModelAdapterError, match=f"^{category}$"):
        OpenAIChatAdapter().prepare_http_request(
            request(profile, messages=[ModelMessage(semantic_role=role)]), profile
        )


def test_stale_snapshot_cannot_prepare_request(profile):
    with pytest.raises(ModelAdapterError, match="^MODEL_SNAPSHOT_MISMATCH$"):
        OpenAIChatAdapter().prepare_http_request(
            request(profile, config_revision=2), profile
        )


@pytest.mark.parametrize("ref,version", [("other_protocol", 1), ("openai_chat_completions", 2)])
def test_protocol_reference_must_match_the_registered_adapter(profile, ref, version):
    snapshot = profile.model_dump()
    snapshot["bindings"]["protocol"] = {"ref": ref, "version": version}
    mismatched = type(profile).model_validate(snapshot)
    with pytest.raises(ModelAdapterError, match="^MODEL_PROTOCOL_UNSUPPORTED$"):
        OpenAIChatAdapter().prepare_http_request(request(mismatched), mismatched)


def test_unknown_native_tool_support_does_not_try_native_protocol(profile):
    snapshot = profile.model_dump()
    snapshot["capabilities"]["tools"]["status"] = "unknown"
    unknown = type(profile).model_validate(snapshot)
    with pytest.raises(ModelAdapterError, match="^NATIVE_TOOL_PROTOCOL_UNAVAILABLE$"):
        OpenAIChatAdapter().prepare_http_request(
            request(
                unknown,
                tools=[
                    ToolDefinition(
                        name="search",
                        description="test",
                        input_schema={"type": "object"},
                    )
                ],
            ),
            unknown,
        )


@pytest.mark.parametrize("status", ["unknown", "unsupported"])
@pytest.mark.parametrize("history_kind", ["call", "result"])
def test_native_history_cannot_bypass_capability_check_without_tool_definitions(
    profile, status, history_kind
):
    snapshot = profile.model_dump()
    snapshot["capabilities"]["tools"]["status"] = status
    unavailable = type(profile).model_validate(snapshot)
    call = ToolCall(
        provider_call_id="provider-original", index=0, name="search", raw_arguments="{}"
    )
    message = (
        ModelMessage(semantic_role="assistant_history", tool_calls=[call])
        if history_kind == "call"
        else ModelMessage(
            semantic_role="tool_result",
            tool_call_id="provider-original",
            content_parts=[{"type": "text", "text": "result"}],
        )
    )
    req = request(unavailable, messages=[message])
    assert req.tools == []
    with pytest.raises(ModelAdapterError, match="^NATIVE_TOOL_PROTOCOL_UNAVAILABLE$"):
        OpenAIChatAdapter().prepare_http_request(req, unavailable)
    assert req.messages == [message]


def test_tool_history_keeps_exact_links_and_reasoning_replay_requires_declared_adapter(
    profile,
):
    snapshot = profile.model_dump()
    snapshot["capabilities"]["tools"]["status"] = "supported"
    profile = type(profile).model_validate(snapshot)
    call = ToolCall(
        provider_call_id="provider-original",
        index=0,
        name="search",
        raw_arguments='{"query":"x"}',
        parsed_arguments={"query": "x"},
    )
    messages = [
        ModelMessage(
            semantic_role="assistant_history",
            tool_calls=[call],
            reasoning_parts=[{"type": "text", "text": "thought"}],
        ),
        ModelMessage(
            semantic_role="tool_result",
            tool_call_id="provider-original",
            content_parts=[{"type": "text", "text": "result"}],
        ),
    ]
    req = request(profile, messages=messages)
    with pytest.raises(ModelAdapterError, match="^MODEL_REASONING_FORMAT_UNSUPPORTED$"):
        OpenAIChatAdapter().prepare_http_request(req, profile)
    body = json.loads(
        OpenAIChatAdapter(reasoning_replay=True)
        .prepare_http_request(req, profile)
        .body_bytes
    )
    assert body["messages"][0]["tool_calls"][0]["id"] == "provider-original"
    assert body["messages"][0]["reasoning_content"] == "thought"
    assert body["messages"][0]["content"] is None
    assert body["messages"][1] == {
        "role": "tool",
        "tool_call_id": "provider-original",
        "content": "result",
    }


def test_native_tool_definitions_are_only_wire_schemas_and_stream_usage_is_requested(
    profile,
):
    snapshot = profile.model_dump()
    snapshot["capabilities"]["tools"]["status"] = "supported"
    supported = type(profile).model_validate(snapshot)
    tool = ToolDefinition(
        name="search",
        description="Search",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
    )
    prepared = OpenAIChatAdapter().prepare_http_request(
        request(supported, tools=[tool], stream=True), supported
    )
    body = json.loads(prepared.body_bytes)
    assert body["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "search",
                "description": "Search",
                "parameters": tool.input_schema,
            },
        }
    ]
    assert body["stream_options"] == {"include_usage": True}
    assert prepared.stream_protocol == "sse"


@pytest.mark.parametrize("arguments", ['{"x":NaN}', '{"x":1e1000}'])
def test_nonfinite_tool_arguments_are_not_treated_as_valid_json(profile, arguments):
    raw = response(
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call",
                    "type": "function",
                    "function": {"name": "search", "arguments": arguments},
                }
            ],
        },
        finish="tool_calls",
    )
    call = (
        OpenAIChatAdapter()
        .decode_response(raw, request(profile), profile)
        .tool_calls[0]
    )
    assert call.argument_error == "INVALID_TOOL_ARGUMENTS"
    assert call.parsed_arguments is None
    assert call.raw_arguments == arguments


def test_duplicate_complete_tool_ids_are_explicit_protocol_failure(profile):
    call = {
        "id": "same",
        "type": "function",
        "function": {"name": "search", "arguments": "{}"},
    }
    with pytest.raises(ModelAdapterError, match="^MODEL_RESPONSE_INVALID$"):
        OpenAIChatAdapter().decode_response(
            response(
                {"role": "assistant", "tool_calls": [call, call]}, finish="tool_calls"
            ),
            request(profile),
            profile,
        )


@pytest.mark.parametrize(
    "part", [{"type": "unsupported", "text": "x"}, {"type": "text", "text": 1}]
)
def test_unsupported_or_invalid_content_is_not_silently_flattened(profile, part):
    with pytest.raises(ModelAdapterError, match="^MODEL_CONTENT_UNSUPPORTED$"):
        OpenAIChatAdapter().prepare_http_request(
            request(
                profile,
                messages=[ModelMessage(semantic_role="user", content_parts=[part])],
            ),
            profile,
        )


@pytest.mark.parametrize("status", ["unknown", "unsupported", "supported"])
@pytest.mark.parametrize("key,value", [("temperature", 0.7), ("top_p", 1)])
def test_sampling_config_is_preserved_but_explicitly_unsupported_values_are_not_sent(profile, status, key, value):
    from nexent.core.model_service.profiles.protocol_parameters import ensure_outlet_sampling_rules
    from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile

    data = ensure_outlet_sampling_rules(profile).model_dump(mode="json")
    data["capabilities"]["sampling"][key]["status"] = status
    data["parameter_values"][key] = value
    current = ResolvedModelProfile.model_validate(data)
    before = current.model_dump(mode="json")
    body = OpenAIChatAdapter().prepare_http_request(request(current), current).json_body
    if status == "unsupported":
        assert key not in body
    else:
        assert body[key] == value
    assert current.model_dump(mode="json") == before
    assert current.parameter_values[key] == value
