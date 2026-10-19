# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Controlled model-visible resources shared by boundary and converter unit tests."""

from nexent.core.agent_runtime_support.contracts import ResourceItem, RuntimeResourceView
from nexent.core.model_service.contracts import ModelMessage, ToolCall, ToolDefinition


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

