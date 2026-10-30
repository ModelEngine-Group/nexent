# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Authorized resources cross a stable conversion boundary without execution."""

import json

import pytest
from nexent.core.agents.contracts.resources import ResourceItem, RuntimeResourceView
from nexent.core.model_service.adapters.openai_chat import OpenAIChatAdapter
from nexent.core.model_service.contracts import ModelMessage, ToolCall, ToolDefinition
from nexent.core.model_service.resource_conversion import (
    ResourceConverterRegistry,
    ResourceRequestConverter,
)
from pydantic import ValidationError


def item(role, text, order, source="history", **kwargs):
    return ResourceItem(message=ModelMessage(
        semantic_role=role, content_parts=[{"type": "text", "text": text}], **kwargs,
    ), source=source, order=order)


def resources():
    return RuntimeResourceView(
        instructions=[item("application_instruction", "skill", 2, "activated_skill_instruction"),
                      item("platform_instruction", "platform", 1, "platform_instruction")],
        references=[item("reference_data", "knowledge", 3, "knowledge")],
        history=[item("assistant_history", "progress", 4, tool_calls=[ToolCall(
            provider_call_id="call-1", index=0, name="lookup", raw_arguments='{"q":"x"}',
        )])],
        tool_observations=[item("tool_result", "result", 5, "tool", tool_call_id="call-1")],
        authorized_metadata=[item("reference_data", "approved metadata", 6, "metadata")],
        current_user_input=item("user_input", "continue", 7, "current_input"),
        tool_definitions=[ToolDefinition(name="lookup", description="Find data", input_schema={"type": "object"})],
    )


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


def test_resource_boundary_rejects_privilege_promotion_and_execution_objects():
    data = resources().model_dump()
    data["references"][0]["message"]["semantic_role"] = "platform_instruction"
    with pytest.raises(ValidationError, match="authorized group"):
        RuntimeResourceView.model_validate(data)
    data = resources().model_dump()
    data["executor"] = object()
    with pytest.raises(ValidationError):
        RuntimeResourceView.model_validate(data)
    data = resources().model_dump()
    data["current_user_input"]["order"] = data["history"][0]["order"]
    with pytest.raises(ValidationError, match="ordering"):
        RuntimeResourceView.model_validate(data)


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
