# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Stable request, event and resource contracts reject ambiguous runtime state."""

import pytest
from pydantic import ValidationError

from nexent.core.agent_runtime_support.contracts import RuntimeResourceView
from nexent.core.model_service.contracts import (
    AssistantMessage, ModelError, ModelEvent, ModelMessage, ModelRequest, ToolCall, ToolCallDelta, ToolDefinition,
)
from nexent.core.model_service.profiles.parameter_rules import compile_parameter_rules
from nexent.core.model_service.profiles.protocol_parameters import openai_chat_parameter_rules
from test.sdk.core.model_service.resource_fixtures import resources


def test_request_rejects_reused_message_ids_and_tool_names():
    message = ModelMessage(semantic_role="user")
    request = dict(request_id="r", outlet_id=None, config_revision=1, messages=[message])
    assert ModelRequest(**request).messages == [message]
    with pytest.raises(ValidationError, match="identities"):
        ModelRequest(**{**request, "messages": [message, message]})
    tool = ToolDefinition(name="lookup", description="Lookup", input_schema={})
    with pytest.raises(ValidationError, match="tool names"):
        ModelRequest(**request, tools=[tool, tool])


@pytest.mark.parametrize("field", ["provider_call_id", "index"])
def test_complete_calls_require_distinct_provider_ids_and_indexes(field):
    call = ToolCall(provider_call_id="one", index=0, name="lookup", raw_arguments="{}")
    other = call.model_copy(update={"provider_call_id": "two", "index": 1, field: getattr(call, field)})
    with pytest.raises(ValidationError, match="identities"):
        AssistantMessage(finish_reason="tool_calls", tool_calls=[call, other])


@pytest.mark.parametrize("kind", ["text_delta", "reasoning_delta", "tool_call_delta", "message_completed", "usage", "error"])
def test_events_carry_only_their_declared_payload(kind):
    message = AssistantMessage(finish_reason="stop")
    values = dict(request_id="r", message_id=message.message_id, sequence=1, type=kind)
    error = ModelError(category="safe", scope="protocol", retryable=False, safe_message="Failed", request_id="r")
    payload = {"text_delta": {"delta": "hi"}, "reasoning_delta": {"delta": "summary"},
        "tool_call_delta": {"tool_call_delta": ToolCallDelta(local_call_id=message.message_id, index=0)},
        "message_completed": {"message": message, "finish_reason": "stop"},
        "usage": {"usage": {}}, "error": {"error": error}}[kind]
    assert ModelEvent(**values, **payload).type == kind
    with pytest.raises(ValidationError, match="declared payload"):
        ModelEvent(**values)
    with pytest.raises(ValidationError, match="declared payload"):
        ModelEvent(**values, **{**payload, "delta" if kind not in {"text_delta", "reasoning_delta"} else "usage": "extra" if kind not in {"text_delta", "reasoning_delta"} else {}})


@pytest.mark.parametrize("change", ["content_kind", "finish_reason", "completion_id", "completion_finish", "error_request"])
def test_event_metadata_cannot_contradict_its_payload(change):
    message = AssistantMessage(finish_reason="stop")
    data = dict(request_id="r", message_id=message.message_id, sequence=1, type="usage", usage={})
    if change in {"content_kind", "finish_reason"}:
        data[change] = "text" if change == "content_kind" else "stop"
    elif change.startswith("completion"):
        data.update(type="message_completed", message=message, finish_reason="stop")
        data.pop("usage")
        data["message_id" if change == "completion_id" else "finish_reason"] = ModelMessage(semantic_role="user").message_id if change == "completion_id" else "length"
    else:
        data.update(type="error", error=ModelError(category="safe", scope="protocol", retryable=False, safe_message="Failed", request_id="other"))
        data.pop("usage")
    with pytest.raises(ValidationError):
        ModelEvent(**data)


@pytest.mark.parametrize("change", ["message_id", "tool_name", "tool_call_role", "tool_result_role"])
def test_resource_identity_and_authorization_invariants(change):
    data = resources().model_dump()
    if change == "message_id":data["current_user_input"]["message"]["message_id"] = data["history"][0]["message"]["message_id"]
    elif change == "tool_name":data["tool_definitions"] *= 2
    elif change == "tool_call_role":data["history"][0]["message"]["semantic_role"] = "user"
    else:data["tool_observations"][0]["message"]["semantic_role"] = "assistant"
    with pytest.raises(ValidationError):RuntimeResourceView.model_validate(data)


def test_protocol_rules_have_no_invented_defaults_and_are_detached():
    rules = openai_chat_parameter_rules()
    compile_parameter_rules(rules)
    assert {rule["key"] for rule in rules} == {"temperature", "top_p", "max_output_tokens", "stop", "response_format"}
    assert all("default_value" not in rule for rule in rules)
    rules[0]["schema"]["type"].clear()
    assert openai_chat_parameter_rules()[0]["schema"]["type"] == ["number", "null"]
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
