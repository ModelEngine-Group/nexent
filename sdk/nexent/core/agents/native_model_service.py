# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Native runtime messages over develop's resolved model service and converters."""

from copy import deepcopy
from inspect import iscoroutinefunction

from smolagents.models import ChatMessage, Model, get_tool_json_schema
from smolagents.monitoring import TokenUsage

from ..agent_runtime_support.contracts import ResourceItem, RuntimeResourceView
from ..concurrency.cancellation import RunTerminated
from ..model_service.compatibility.invocation_options import LegacyInvocationOptions
from ..model_service.compatibility.legacy_chat_model import _legacy_tool_call
from ..model_service.contracts import ModelMessage, ToolDefinition
from ..model_service.resource_conversion import ResourceConverterRegistry
from ..model_service.service import ModelServiceError
from ..models.context_usage import InputUsageObservation, context_model_key


class NativeServiceModel(Model):
    """Keep provider protocol/parameters, retries and lifecycle inside ModelService."""

    def __init__(self, delegate):
        super().__init__(model_id=delegate.model_id)
        self.delegate = delegate

    @property
    def last_finish_reason(self):
        return self.delegate.last_finish_reason

    @property
    def last_prompt_cache_usage(self):
        return self.delegate.last_prompt_cache_usage

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

    def generate(self, messages, tools_to_call_from=None, native_tool_schemas=None, context_rebuild=None, **kwargs):
        from .native_runtime import validate_native_completion

        model = self.delegate
        if context_rebuild is not None and (
            not callable(context_rebuild) or iscoroutinefunction(context_rebuild)
            or iscoroutinefunction(getattr(context_rebuild, "__call__", None))
        ):
            raise TypeError("Native context_rebuild must be a synchronous callback")
        request, profile = self._request(messages, tools_to_call_from, native_tool_schemas, kwargs)
        observed_messages = messages
        observed_schemas = native_tool_schemas
        model.last_context_observation = None
        model.last_context_evidence = None

        def rebuild_request(_error):
            nonlocal observed_messages, observed_schemas
            rebuilt = context_rebuild()
            observed_messages = getattr(rebuilt, "messages", rebuilt)
            if not isinstance(observed_messages, list):
                raise TypeError("context_rebuild must return FinalContext or a message list")
            observed_schemas = getattr(rebuilt, "tools", native_tool_schemas)
            model.last_context_evidence = getattr(rebuilt, "evidence", None)
            replacement, _ = self._request(observed_messages, tools_to_call_from, observed_schemas, kwargs)
            return replacement.model_copy(update={"request_id": request.request_id})

        observer = model.observer
        active_attempt = None
        committed = False
        streamed_text = streamed_reasoning = False
        model.last_attempt_id = request.request_id
        model.last_attempt_number = None
        model.last_retry_count = 0
        model._reset_response(profile)
        try:
            with model.service.stream(
                request, profile, scope=model.cancellation_scope,
                request_rebuild=rebuild_request if context_rebuild is not None else None,
            ) as events:
                for event in events:
                    if model.stop_event.is_set():
                        raise RunTerminated("Agent run cancelled")
                    if active_attempt != event.attempt:
                        if active_attempt is not None:
                            observer.rollback_model_attempt(request.request_id, active_attempt)
                        active_attempt = event.attempt
                        model.last_attempt_number = event.attempt
                        model.last_retry_count = event.attempt - 1
                        model._reset_response(profile)
                        streamed_text = streamed_reasoning = False
                        observer.begin_model_attempt(request.request_id, active_attempt)
                    model._observe_event(event, profile)
                    if event.type == "error" and not event.error.will_retry:
                        raise model._terminal(event.error)
                    if event.type == "reasoning_delta":
                        observer.add_model_reasoning_content(event.delta)
                        streamed_reasoning |= bool(event.delta)
                    elif event.type == "text_delta" and event.content_kind != "refusal":
                        observer.add_assistant_text_delta(event.delta)
                        streamed_text |= bool(event.delta)
                    if event.type != "message_completed":
                        continue
                    if model.stop_event.is_set():
                        raise RunTerminated("Agent run cancelled")
                    complete = event.message
                    model.last_context_observation = InputUsageObservation.capture(
                        usage=complete.usage, messages=observed_messages,
                        tools=observed_schemas if observed_schemas is not None else tools_to_call_from,
                        model_key=context_model_key(model), request_id=request.request_id, attempt=event.attempt,
                    )
                    content = "".join(part["text"] for part in complete.content_parts if part.get("type") == "text")
                    model.last_finish_reason = complete.finish_reason
                    reasoning = "".join(
                        part.get("text", "") for part in complete.reasoning_parts if part.get("type") == "text"
                    )
                    if not streamed_reasoning and reasoning:
                        model.last_response_diagnostics.update(
                            reasoning_char_count=len(reasoning), reasoning_chunk_count=1
                        )
                    model.last_response_diagnostics["reasoning_only_budget_exhausted"] = (
                        complete.finish_reason == "length"
                        and bool(reasoning)
                        and not content.strip()
                        and not complete.tool_calls
                    )
                    validate_native_completion(
                        content,
                        complete.tool_calls,
                        complete.finish_reason,
                        complete.refusal,
                        usage={
                            key: getattr(complete.usage, key)
                            for key in ("input_tokens", "output_tokens", "reasoning_tokens")
                        },
                        output_limit=profile.parameter_values.get(
                            "max_output_tokens", profile.parameter_values.get("max_tokens")
                        ),
                    )
                    if not streamed_reasoning:
                        observer.add_model_reasoning_content(reasoning)
                    if not streamed_text:
                        observer.add_assistant_text_delta(content)
                        model.last_response_diagnostics.update(
                            content_char_count=len(content), content_chunk_count=int(bool(content))
                        )
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
        except ModelServiceError as error:
            raise model._terminal(error.error) from None
        finally:
            if active_attempt is not None and not committed:
                observer.rollback_model_attempt(request.request_id, active_attempt)
