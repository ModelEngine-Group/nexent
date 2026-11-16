# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Authorized resources cross a stable conversion boundary without execution."""

import json

import pytest
from nexent.core.agent_runtime_support.contracts import RuntimeResourceView
from nexent.core.model_service.adapters.openai_chat import OpenAIChatAdapter
from nexent.core.model_service.resource_conversion import (
    ResourceConverterRegistry,
    ResourceRequestConverter,
)
from test.sdk.core.model_service.resource_fixtures import resources


def test_native_conversion_preserves_every_resource_and_tool_association(openai_profile):
    view = resources()
    before = view.model_dump()
    converted = ResourceRequestConverter(native=True).convert(view, openai_profile, request_id="request", stream=True)
    assert converted.tool_protocol == "native"
    request = converted.request
    assert request.request_id == "request" and request.config_revision == openai_profile.config_revision
    assert [m.content_parts[0]["text"] for m in request.messages] == [
        "platform", "skill", "knowledge", "progress", "result", "approved metadata", "continue",
    ]
    assert request.messages[3].tool_calls[0].provider_call_id == request.messages[4].tool_call_id == "call-1"
    assert request.tools == view.tool_definitions
    wire = OpenAIChatAdapter().prepare_http_request(request, openai_profile)
    assert [message["role"] for message in wire.json_body["messages"]] == [
        "system", "system", "user", "assistant", "tool", "user", "user",
    ]
    assert view.model_dump() == before
    view.history[0].message.content_parts[0]["text"] = "changed after conversion"
    assert request.messages[3].content_parts[0]["text"] == "progress"


@pytest.mark.parametrize("status", ["supported", "unsupported", "unknown"])
@pytest.mark.parametrize("native", [False, True])
def test_text_protocol_is_selected_before_request_without_changing_resources(openai_profile, status, native):
    data = openai_profile.model_dump()
    data["capabilities"]["tools"]["status"] = status
    profile = openai_profile.__class__.model_validate(data)
    view = resources()
    before = view.model_dump()
    converted = ResourceRequestConverter(native=native).convert(view, profile)
    actual_native = native and status == "supported"
    assert converted.tool_protocol == ("native" if actual_native else "text_block")
    request = converted.request
    assert bool(request.tools) == actual_native
    wire = OpenAIChatAdapter().prepare_http_request(request, profile)
    if not actual_native:
        assert all(not message.tool_calls and message.tool_call_id is None for message in request.messages)
        assert all(message["role"] != "tool" for message in wire.json_body["messages"])
        blocks = [json.loads(part["text"]) for message in request.messages for part in message.content_parts
                  if part.get("type") == "text" and part["text"].startswith("{")]
        assert {"historical_tool_calls": [{"id": "call-1", "name": "lookup", "arguments": '{"q":"x"}'}]} in blocks
        assert {"historical_tool_result": "call-1"} in blocks
        assert {"available_tools": [tool.model_dump() for tool in view.tool_definitions]} in blocks
    assert view.model_dump() == before


def test_converter_registry_rejects_unknown_versions():
    registry = ResourceConverterRegistry()
    for mode in ("code_converter", "native_converter"):
        reference, = registry.references(mode)
        assert registry.resolve(reference).reference == reference
        with pytest.raises(ValueError, match="UNREGISTERED"):
            registry.resolve(reference.model_copy(update={"version": 2}))


def test_code_observations_remain_usable_in_native_history(openai_profile):
    view = resources()
    values = view.model_dump()
    values["history"][0]["message"]["tool_calls"] = []
    values["tool_observations"][0]["message"]["tool_call_id"] = None
    converted = ResourceRequestConverter(native=True).convert(RuntimeResourceView.model_validate(values), openai_profile)
    wire = OpenAIChatAdapter().prepare_http_request(converted.request, openai_profile)
    assert wire.json_body["messages"][4]["role"] == "user"
    assert converted.request.messages[4].content_parts[-1]["text"] == "result"
    assert values["tool_observations"][0]["message"]["semantic_role"] == "tool_result"


def test_code_conversion_does_not_replay_provider_reasoning_or_mutate_history(openai_profile):
    view = resources()
    view.history[0].message.reasoning_parts.append({"type": "text", "text": "provider reasoning"})
    result = ResourceRequestConverter().convert(view, openai_profile)
    assert not any(message.reasoning_parts for message in result.request.messages)
    assert view.history[0].message.reasoning_parts == [{"type": "text", "text": "provider reasoning"}]
