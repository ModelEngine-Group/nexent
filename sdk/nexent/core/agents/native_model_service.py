# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Native runtime messages over develop's resolved model service and converters."""

from copy import deepcopy

from smolagents.models import ChatMessage, Model, get_tool_json_schema
from smolagents.monitoring import TokenUsage

from ..agent_runtime_support.contracts import ResourceItem, RuntimeResourceView
from ..concurrency.cancellation import RunTerminated
from ..model_service.compatibility.invocation_options import LegacyInvocationOptions
from ..model_service.compatibility.legacy_chat_model import _legacy_tool_call
from ..model_service.contracts import ModelMessage, ToolDefinition
from ..model_service.resource_conversion import ResourceConverterRegistry


class NativeServiceModel(Model):
    """Keep provider protocol/parameters, retries and lifecycle inside ModelService."""

    def __init__(self, delegate):
        super().__init__(model_id=delegate.model_id)
        self.delegate = delegate

    def _request(self, messages, tools, schemas, parameters):
        model = self.delegate
        controls = dict(parameters)
        stop_sequences = controls.pop("stop_sequences", None)
        response_format = controls.pop("response_format", None)
        profile = LegacyInvocationOptions(
            controls,
            stop_sequences,
            response_format,
            context_budget_snapshot=model.context_budget_snapshot,
            capacity_snapshot=model.capacity_snapshot,
        ).resolve(model.profile)
        definitions = schemas if schemas is not None else [get_tool_json_schema(tool) for tool in tools or []]
        items = []
        instructions = []
        users = []
        for order, wire in enumerate(deepcopy(messages)):
            role = wire["role"]
            semantic = {
                "system": "platform_instruction",
                "developer": "application_instruction",
                "user": "user_input",
                "assistant": "assistant_history",
                "tool": "tool_result",
            }[role]
            content = wire.get("content")
            parts = [{"type": "text", "text": content}] if isinstance(content, str) else (content or [])
            message = ModelMessage(
                semantic_role=semantic,
                content_parts=parts,
                reasoning_parts=(wire.get("reasoning_parts") or [])
                if profile.capabilities.reasoning.status == "supported"
                else [],
                tool_calls=[_legacy_tool_call(call, index) for index, call in enumerate(wire.get("tool_calls") or [])],
                tool_call_id=wire.get("tool_call_id"),
            )
            item = ResourceItem(message=message, source=semantic, order=order)
            if role in {"system", "developer"}:
                instructions.append(item)
            else:
                items.append(item)
                if role == "user":
                    users.append(item)
        if not users:
            raise ValueError("Native generation requires a user task")
        current = users[-1]
        resources = RuntimeResourceView(
            instructions=instructions,
            history=[item for item in items if item is not current],
            current_user_input=current,
            tool_definitions=[
                ToolDefinition(
                    name=s["function"]["name"],
                    description=s["function"].get("description", ""),
                    input_schema=s["function"]["parameters"],
                )
                for s in definitions
            ],
        )
        converted = (
            ResourceConverterRegistry()
            .resolve(profile.bindings.native_converter)
            .convert(
                resources,
                profile,
                stream=True,
                purpose="native_agent",
            )
        )
        if converted.tool_protocol != "native":
            raise ValueError("Native runtime requires declared native tool support")
        return converted.request, profile

    def generate(self, messages, tools_to_call_from=None, native_tool_schemas=None, **kwargs):
        from .native_runtime import validate_native_completion

        model = self.delegate
        request, profile = self._request(messages, tools_to_call_from, native_tool_schemas, kwargs)
        observer = model.observer
        active_attempt = None
        committed = False
        try:
            with model.service.stream(request, profile, scope=model.cancellation_scope) as events:
                for event in events:
                    if active_attempt != event.attempt:
                        if active_attempt is not None:
                            observer.rollback_model_attempt(request.request_id, active_attempt)
                        active_attempt = event.attempt
                        model.last_finish_reason = None
                        observer.begin_model_attempt(request.request_id, active_attempt)
                    if event.type == "error" and not event.error.will_retry:
                        raise model._terminal(event.error)
                    if event.type == "text_delta" and event.content_kind != "refusal":
                        observer.add_assistant_text_delta(event.delta)
                    if event.type != "message_completed":
                        continue
                    if model.stop_event.is_set():
                        raise RunTerminated("Agent run cancelled")
                    complete = event.message
                    content = "".join(part["text"] for part in complete.content_parts if part.get("type") == "text")
                    model.last_finish_reason = complete.finish_reason
                    validate_native_completion(content, complete.tool_calls, complete.finish_reason, complete.refusal)
                    wire = {"role": "assistant", "content": content}
                    if complete.reasoning_parts:
                        wire["reasoning_parts"] = deepcopy(complete.reasoning_parts)
                    if complete.tool_calls:
                        wire["tool_calls"] = [
                            {
                                "id": call.provider_call_id,
                                "type": "function",
                                "function": {"name": call.name, "arguments": call.raw_arguments},
                            }
                            for call in complete.tool_calls
                        ]
                    message = ChatMessage.from_dict(
                        {key: value for key, value in wire.items() if key != "reasoning_parts"}
                    )
                    message.raw = wire
                    message.finish_reason = complete.finish_reason
                    if complete.usage.input_tokens is not None and complete.usage.output_tokens is not None:
                        message.token_usage = TokenUsage(complete.usage.input_tokens, complete.usage.output_tokens)
                    model.last_input_token_count = complete.usage.input_tokens
                    model.last_output_token_count = complete.usage.output_tokens
                    observer.flush_remaining_tokens()
                    observer.commit_model_attempt(request.request_id, active_attempt)
                    committed = True
                    return message
            raise ValueError("Native model service ended without a completed message")
        finally:
            if active_attempt is not None and not committed:
                observer.rollback_model_attempt(request.request_id, active_attempt)
