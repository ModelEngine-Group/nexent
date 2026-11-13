# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Convert already-authorized resources; execution and prompt policy stay in Runtime."""

import json
from typing import Literal
from uuid import uuid4

from nexent.core.agent_runtime_support.contracts import RuntimeResourceView as _RuntimeResourceView
from nexent.core.model_service.contracts import ModelMessage, ModelRequest
from nexent.core.model_service.profiles.contracts import ProfileContract, VersionedReference
from nexent.core.model_service.profiles.instruction_mapping import validate_instruction_mapping


class ConvertedModelRequest(ProfileContract):
    request: ModelRequest
    tool_protocol: Literal["native", "text_block"]


def _text(data):
    return {"type": "text", "text": json.dumps(data, ensure_ascii=False, allow_nan=False)}


def _code_message(message):
    value = message.model_dump()
    value["reasoning_parts"] = []  # Diagnostic history is not a portable provider reasoning continuation.
    if message.tool_calls:
        value["content_parts"].append(_text({
            "historical_tool_calls": [
                {"id": call.provider_call_id, "name": call.name, "arguments": call.raw_arguments}
                for call in message.tool_calls
            ],
        }))
        value["tool_calls"] = []
    if message.semantic_role in {"tool_result", "tool"}:
        value["semantic_role"] = "reference_data"
        value["content_parts"].insert(0, _text({"historical_tool_result": message.tool_call_id}))
        value["tool_call_id"] = None
    return ModelMessage.model_validate(value)


class ResourceRequestConverter:
    """One registered conversion per mode, chosen before any model request."""

    def __init__(self, *, native=False):
        if type(native) is not bool:
            raise TypeError("Native mode must be boolean")
        self.native = native
        self.reference = VersionedReference(ref="native_tools_v1" if native else "code_messages_v1", version=1)

    def convert(self, resources, profile, *, stream=False, request_id=None, purpose="agent", run_id=None):
        # Detach mutable collections before sorting or producing a request.
        resources = _RuntimeResourceView.model_validate(resources.model_dump())
        validate_instruction_mapping(profile.instruction_mapping)
        native = self.native and profile.capabilities.tools.status == "supported"
        priorities = {name: index for index, name in enumerate(profile.instruction_mapping.ordering)}
        instructions = sorted(resources.instructions, key=lambda item: (
            priorities.get("platform_instruction" if item.message.semantic_role == "platform_instruction"
                           else item.source, len(priorities)), item.order,
        ))
        instruction_ids = {item.message.message_id for item in instructions}
        remainder = sorted((item for item in resources.items() if item.message.message_id not in instruction_ids),
                           key=lambda item: item.order)
        messages = [item.message.model_copy(update={"source": item.source}) for item in instructions + remainder]
        if native:
            # Code histories can contain observations without provider-native call IDs.
            messages = [_code_message(message) if message.semantic_role in {"tool_result", "tool"}
                        and message.tool_call_id is None else message for message in messages]
        else:
            messages = [_code_message(message) for message in messages]
            if resources.tool_definitions:
                description = ModelMessage(
                    semantic_role="reference_data", source="authorized_tool_definitions",
                    content_parts=[_text({"available_tools": [tool.model_dump() for tool in resources.tool_definitions]})],
                )
                # Keep the current input in its original position relative to other resources.
                index = next(index for index, message in enumerate(messages)
                             if message.message_id == resources.current_user_input.message.message_id)
                messages.insert(index, description)
        return ConvertedModelRequest(
            request=ModelRequest(
                request_id=request_id if request_id is not None else str(uuid4()), outlet_id=profile.outlet_id,
                config_revision=profile.config_revision, messages=messages,
                tools=resources.tool_definitions if native else [], stream=stream, purpose=purpose, run_id=run_id,
            ),
            tool_protocol="native" if native else "text_block",
        )


class ResourceConverterRegistry:
    def __init__(self):
        self._converters = tuple(ResourceRequestConverter(native=native) for native in (False, True))

    def references(self, mode):
        if mode not in {"code_converter", "native_converter"}:
            raise ValueError("Unknown converter mode")
        return tuple(converter.reference for converter in self._converters
                     if converter.native == (mode == "native_converter"))

    def resolve(self, reference):
        for converter in self._converters:
            if converter.reference == reference:
                return converter
        raise ValueError("MODEL_CONVERTER_UNREGISTERED")
