"""Translate Jiuwen messages into the public, non-executable resource view."""

import json
from copy import deepcopy

from ...agent_runtime_support.contracts import ResourceItem, RuntimeResourceView
from ...model_service.contracts import ModelMessage, ToolCall, ToolDefinition
from .jiuwen_protocol import EXECUTION_TOOL, PROTOCOL_INSTRUCTION, JiuwenProtocolError


def _mapping(value):
    return value.model_dump() if hasattr(value, "model_dump") else deepcopy(value)


def _parts(content):
    if content is None:
        return []
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append({"type": "text", "text": part})
            elif isinstance(part, dict) and isinstance(part.get("type"), str):
                parts.append(deepcopy(part))
            else:
                raise JiuwenProtocolError("JIUWEN_MESSAGE_CONTENT_INVALID")
        return parts
    raise JiuwenProtocolError("JIUWEN_MESSAGE_CONTENT_INVALID")


def resource_view(messages, tools, *, prefix=(), text_protocol=False):
    """Keep ordering, actual call IDs and authorized definitions; copy caller data."""
    current = [{"role": "user", "content": messages}] if isinstance(messages, str) else [_mapping(m) for m in messages]
    boundary = 0
    while boundary < len(current) and current[boundary]["role"] in {"system", "developer"}:
        boundary += 1
    current[boundary:boundary] = [_mapping(message) for message in prefix]
    if text_protocol:
        current.insert(0, {"role": "system", "content": PROTOCOL_INSTRUCTION})
    roles = {"system": "application_instruction", "developer": "application_instruction", "user": "user_input",
             "assistant": "assistant_history", "tool": "tool_result"}
    items = []
    for index, value in enumerate(current):
        if value.get("role") not in roles:
            raise JiuwenProtocolError("JIUWEN_MESSAGE_ROLE_UNSUPPORTED")
        calls = []
        for position, raw in enumerate(value.get("tool_calls") or []):
            call = _mapping(raw)
            function = call.get("function", call)
            arguments = function.get("arguments", "")
            if not isinstance(arguments, str):
                arguments = json.dumps(arguments, ensure_ascii=False, allow_nan=False)
            if not call.get("id"):
                raise JiuwenProtocolError("JIUWEN_TOOL_CALL_ID_MISSING")
            calls.append(ToolCall(provider_call_id=call["id"], index=position, name=function["name"],
                                  raw_arguments=arguments))
        role = roles[value["role"]]
        message = ModelMessage(semantic_role=role, content_parts=_parts(value.get("content")), tool_calls=calls,
                               tool_call_id=value.get("tool_call_id"))
        items.append(ResourceItem(message=message, source="application" if role == "application_instruction"
                                  else "conversation", order=index))
    user = next((item for item in reversed(items) if item.message.semantic_role == "user_input"), None)
    if user is None:
        raise JiuwenProtocolError("JIUWEN_CURRENT_INPUT_MISSING")
    definitions = []
    for tool in tools or []:
        data = _mapping(tool)
        function = data.get("function", data)
        if function["name"] == EXECUTION_TOOL:
            continue
        definitions.append(ToolDefinition(name=function["name"], description=function.get("description") or "",
                                          input_schema=function.get("parameters") or {}))
    return RuntimeResourceView(
        current_user_input=user, tool_definitions=definitions,
        instructions=[item for item in items if item.message.semantic_role == "application_instruction"],
        history=[item for item in items if item is not user and item.message.semantic_role != "application_instruction"],
    )
