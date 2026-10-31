# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""OpenAI-compatible chat framing; runtime execution and retries stay outside."""

import json
import math

from pydantic import ValidationError

from nexent.core.model_service.contracts import AssistantMessage, ModelRequest, TokenUsage, ToolCall
from nexent.core.model_service.http_contracts import PreparedHttpRequest, RawHttpResponse
from nexent.core.model_service.parameter_transforms import parameter_transform_references, transform_parameter
from nexent.core.model_service.profiles.contracts import VersionedReference
from nexent.core.model_service.profiles.instruction_mapping import validate_instruction_mapping
from nexent.core.model_service.profiles.parameter_bindings import validate_parameter_bindings
from nexent.core.model_service.profiles.parameter_rules import compile_parameter_rules, validate_saved_parameter_values
from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError
from nexent.core.model_service.profiles.request_parameters import _set, _tokens, apply_extra_api_parameters
from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile


class ModelAdapterError(ValueError):
    """Fixed protocol category without model text, tool arguments or raw body."""

    def __init__(self, category: str, *, response: RawHttpResponse | None = None):
        self.category = category
        self.response = response
        super().__init__(category)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON member")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("Invalid JSON constant")


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Invalid JSON number")
    return number


def parse_json(text: str):
    return json.loads(
        text, object_pairs_hook=_unique_object, parse_constant=_invalid_constant, parse_float=_finite_float
    )


def _content_parts(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [{"type": "text", "text": value}]
    if isinstance(value, list) and all(isinstance(part, dict) and isinstance(part.get("type"), str) for part in value):
        return value
    raise ModelAdapterError("MODEL_RESPONSE_INVALID")


def _usage(raw, semantics_id):
    if raw is None:
        return TokenUsage(semantics_id=semantics_id)
    if not isinstance(raw, dict):
        raise ModelAdapterError("MODEL_USAGE_INVALID")
    details = []
    for key in ("prompt_tokens_details", "completion_tokens_details"):
        value = raw.get(key)
        if value is None:
            value = {}
        if not isinstance(value, dict):
            raise ModelAdapterError("MODEL_USAGE_INVALID")
        details.append(value)
    try:
        return TokenUsage(
            input_tokens=raw.get("prompt_tokens"),
            output_tokens=raw.get("completion_tokens"),
            total_tokens=raw.get("total_tokens"),
            cached_input_tokens=details[0].get("cached_tokens"),
            reasoning_tokens=details[1].get("reasoning_tokens"),
            origin="provider",
            semantics_id=semantics_id,
        )
    except ValidationError:
        raise ModelAdapterError("MODEL_USAGE_INVALID") from None


def _tool_call(raw, index):
    if not isinstance(raw, dict) or raw.get("type") != "function" or not isinstance(raw.get("function"), dict):
        raise ModelAdapterError("MODEL_TOOL_CALL_INVALID")
    function = raw["function"]
    arguments = function.get("arguments")
    if not isinstance(arguments, str):
        raise ModelAdapterError("MODEL_TOOL_CALL_INVALID")
    parsed, error = None, None
    try:
        parsed = parse_json(arguments)
        if not isinstance(parsed, dict):
            raise ValueError("Tool arguments must be an object")
    except (ValueError, RecursionError):
        parsed, error = None, "INVALID_TOOL_ARGUMENTS"
    try:
        return ToolCall(
            provider_call_id=raw.get("id"),
            index=index,
            name=function.get("name"),
            raw_arguments=arguments,
            parsed_arguments=parsed,
            argument_error=error,
        )
    except ValidationError:
        raise ModelAdapterError("MODEL_TOOL_CALL_INVALID") from None


class OpenAIChatAdapter:
    """Single-choice messages with declared parameter bindings and wire metadata."""

    reference = VersionedReference(ref="openai_chat_v1", version=1)
    protocol_reference = VersionedReference(ref="openai_chat_completions", version=1)

    def __init__(self, *, reasoning_replay: bool = False):
        if type(reasoning_replay) is not bool:
            raise ValueError("Reasoning replay declaration must be boolean")
        self._reasoning_replay = reasoning_replay

    def prepare_http_request(self, request: ModelRequest, profile: ResolvedModelProfile) -> PreparedHttpRequest:
        if request.outlet_id != profile.outlet_id or request.config_revision != profile.config_revision:
            raise ModelAdapterError("MODEL_SNAPSHOT_MISMATCH")
        if profile.bindings.protocol != self.protocol_reference:
            raise ModelAdapterError("MODEL_PROTOCOL_UNSUPPORTED")
        validate_instruction_mapping(profile.instruction_mapping)
        if request.tools and profile.capabilities.tools.status != "supported":
            raise ModelAdapterError("NATIVE_TOOL_PROTOCOL_UNAVAILABLE")
        mappings = profile.instruction_mapping.mappings.model_dump()
        messages = []
        for message in request.messages:
            role = mappings.get(message.semantic_role, message.semantic_role)
            if role not in profile.instruction_mapping.supported_roles:
                raise ModelAdapterError("MODEL_ROLE_UNSUPPORTED")
            if message.tool_calls and role != "assistant" or message.tool_call_id is not None and role != "tool":
                raise ModelAdapterError("MODEL_MESSAGE_INVALID")
            if role == "tool" and message.tool_call_id is None:
                raise ModelAdapterError("MODEL_MESSAGE_INVALID")
            if (
                message.tool_calls or message.tool_call_id is not None or role == "tool"
            ) and profile.capabilities.tools.status != "supported":
                raise ModelAdapterError("NATIVE_TOOL_PROTOCOL_UNAVAILABLE")
            parts = message.content_parts
            if any(
                part.get("type")
                not in {"text", "image_url", "input_audio", "audio_url", "video_url", "input_image", "input_video"}
                for part in parts
            ):
                raise ModelAdapterError("MODEL_CONTENT_UNSUPPORTED")
            if any(part.get("type") == "text" and not isinstance(part.get("text"), str) for part in parts):
                raise ModelAdapterError("MODEL_CONTENT_UNSUPPORTED")
            simple_text = len(parts) == 1 and set(parts[0]) == {"type", "text"}
            wire = {"role": role, "content": parts[0]["text"] if simple_text else parts}
            if not parts:
                wire["content"] = None if role == "assistant" and message.tool_calls else ""
            if message.tool_call_id is not None:
                wire["tool_call_id"] = message.tool_call_id
            if message.tool_calls:
                wire["tool_calls"] = [
                    {
                        "id": call.provider_call_id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": call.raw_arguments},
                    }
                    for call in message.tool_calls
                ]
            if message.reasoning_parts:
                if (
                    not self._reasoning_replay
                    or role != "assistant"
                    or any(
                        part.get("type") != "text" or not isinstance(part.get("text"), str)
                        for part in message.reasoning_parts
                    )
                ):
                    raise ModelAdapterError("MODEL_REASONING_FORMAT_UNSUPPORTED")
                wire["reasoning_content"] = "".join(part["text"] for part in message.reasoning_parts)
            messages.append(wire)
        body = {"model": profile.identity.request_model_id, "messages": messages, "stream": request.stream}
        if request.tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {"name": tool.name, "description": tool.description, "parameters": tool.input_schema},
                }
                for tool in request.tools
            ]
        if request.stream:
            body["stream_options"] = {"include_usage": True}
        try:
            rules = compile_parameter_rules(profile.parameter_rules)
            validate_saved_parameter_values(rules, profile.parameter_values)
            bindings = validate_parameter_bindings(rules, parameter_transform_references())
            for key, binding in bindings.items():
                if key in {"temperature", "top_p"} and getattr(profile.capabilities.sampling, key).status == "unsupported":
                    continue
                if key in profile.parameter_values:
                    _set(body, _tokens(binding["path"]), transform_parameter(binding, profile.parameter_values[key]),
                         binding["path"])
            body = apply_extra_api_parameters(
                body, profile.extra_api_parameters, parameter_paths=[binding["path"] for binding in bindings.values()]
            )
            return PreparedHttpRequest(
                request_id=request.request_id,
                method=profile.connection_rules.method,
                base_url=profile.connection.base_url,
                relative_path=profile.connection_rules.relative_path,
                headers=profile.connection_rules.headers,
                credential_ref=profile.connection.credential_ref,
                json_body=body,
                timeout_seconds=profile.connection.timeout_seconds,
                ssl_verify=profile.connection.ssl_verify,
                stream_protocol="sse" if request.stream else None,
            )
        except (ParameterValidationError, ValueError, TypeError):
            raise ModelAdapterError("MODEL_REQUEST_CONFIGURATION_INVALID") from None

    def decode_response(
        self, raw: RawHttpResponse, request: ModelRequest, profile: ResolvedModelProfile
    ) -> AssistantMessage:
        try:
            body = parse_json(raw.body.decode("utf-8"))
            if isinstance(body, dict) and body.get("error") is not None:
                raise ModelAdapterError("MODEL_PROVIDER_ERROR", response=raw)
            if not isinstance(body, dict) or not isinstance(body.get("choices"), list) or len(body["choices"]) != 1:
                raise ModelAdapterError("MODEL_RESPONSE_INVALID")
            choice = body["choices"][0]
            if not isinstance(choice, dict) or type(choice.get("index")) is not int or choice["index"] != 0:
                raise ModelAdapterError("MODEL_RESPONSE_INVALID")
            message = choice.get("message")
            if not isinstance(message, dict) or message.get("role") != "assistant":
                raise ModelAdapterError("MODEL_RESPONSE_INVALID")
            finish = choice.get("finish_reason")
            if not isinstance(finish, str) or not finish.strip():
                raise ModelAdapterError("MODEL_RESPONSE_INCOMPLETE")
            calls = message.get("tool_calls")
            if calls is None:
                calls = []
            if not isinstance(calls, list):
                raise ModelAdapterError("MODEL_TOOL_CALL_INVALID")
            parts = _content_parts(message.get("content"))
            if message.get("audio") is not None:
                parts.append({"type": "audio", "audio": message["audio"]})
            return AssistantMessage(
                content_parts=parts,
                reasoning_parts=_content_parts(message.get("reasoning_content")),
                refusal=message.get("refusal"),
                tool_calls=[_tool_call(call, index) for index, call in enumerate(calls)],
                finish_reason=finish,
                usage=_usage(body.get("usage"), profile.capabilities.usage.semantics_id),
                provider_metadata={
                    "response_id": body.get("id"),
                    "model": body.get("model"),
                    "request_id": request.request_id,
                    "unmapped_message_fields": {
                        key: value
                        for key, value in message.items()
                        if key not in {"role", "content", "reasoning_content", "refusal", "tool_calls", "audio"}
                    },
                },
            )
        except ModelAdapterError:
            raise
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise ModelAdapterError("MODEL_RESPONSE_INVALID") from None

    def new_stream_decoder(self, request, profile):
        """Import the stream state lazily to keep complete-message helpers reusable."""
        from nexent.core.model_service.adapters.openai_stream import OpenAIStreamDecoder

        return OpenAIStreamDecoder(request, profile)

    def normalize_error(self, error, *, request_id, attempt=1, max_attempts=1, will_retry=False):
        from nexent.core.model_service.errors import normalize_model_error

        return normalize_model_error(
            error, request_id=request_id, attempt=attempt, max_attempts=max_attempts, will_retry=will_retry
        )

    def decode_stream(self, raw_events, request, profile):
        """Stop at the verified completion marker; HTTP ownership is external."""
        decoder = self.new_stream_decoder(request, profile)
        for frame in raw_events:
            for event in decoder.push(frame):
                yield event
                if event.type == "message_completed":
                    return
        yield from decoder.finish()

    async def adecode_stream(self, raw_events, request, profile):
        decoder = self.new_stream_decoder(request, profile)
        async for frame in raw_events:
            for event in decoder.push(frame):
                yield event
                if event.type == "message_completed":
                    return
        for event in decoder.finish():
            yield event
