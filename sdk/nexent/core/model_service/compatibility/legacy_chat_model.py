# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Existing smolagents model interface over the one model service."""

from copy import deepcopy
from inspect import iscoroutinefunction
from uuid import uuid4

from smolagents.models import (
    ChatMessage,
    ChatMessageStreamDelta,
    ChatMessageToolCallFunction,
    ChatMessageToolCallStreamDelta,
    Model,
    get_clean_message_list,
    get_tool_json_schema,
    tool_role_conversions,
)
from smolagents.monitoring import TokenUsage

from nexent.core.concurrency.cancellation import RunCancellationScope
from nexent.core.model_errors import ModelErrorCode, ModelInvocationTerminalError
from nexent.core.model_service.compatibility.invocation_options import LegacyInvocationOptions
from nexent.core.model_service.contracts import ModelMessage, ModelRequest, ToolDefinition
from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile
from nexent.core.model_service.registry import AuthenticationRegistry
from nexent.core.model_service.service import ModelService, ModelServiceError
from nexent.core.model_service.errors import model_error_message
from nexent.core.models.capacity_budget import parse_context_budget_snapshot
from nexent.core.models.message_utils import merge_system_messages
from nexent.core.models.prompt_cache import PromptCacheUsage
from nexent.core.models.retry import DEFAULT_MODEL_RETRY
from nexent.core.utils.observer import MessageObserver, ProcessType


_ERROR_CODES = {
    "MODEL_EMPTY_RESPONSE": ModelErrorCode.EMPTY_RESPONSE_EXHAUSTED,
    "MODEL_AUTHENTICATION_ERROR": ModelErrorCode.AUTHENTICATION_ERROR,
    "MODEL_NOT_FOUND": ModelErrorCode.NOT_FOUND,
    "MODEL_RATE_LIMITED": ModelErrorCode.RATE_LIMIT_EXHAUSTED,
    "MODEL_SERVICE_UNAVAILABLE": ModelErrorCode.SERVICE_UNAVAILABLE,
    "MODEL_TIMEOUT": ModelErrorCode.TIMEOUT,
    "MODEL_NETWORK_ERROR": ModelErrorCode.CONNECTION_ERROR,
    "MODEL_CONTEXT_EXCEEDED": ModelErrorCode.CONTEXT_OVERFLOW,
    "MODEL_REQUEST_INVALID": ModelErrorCode.INVALID_REQUEST,
}


class LegacyChatModel(Model):
    """No provider branches, HTTP clients, tool execution or AgentMode fallback."""

    supports_deferred_attempt_commit = True
    supports_suppressed_attempt_stream = True

    def __init__(
        self, profile, service, *, observer=None, cancellation_scope=None, flatten_messages_as_text=False,
        context_budget_snapshot=None, capacity_snapshot=None,
    ):
        self.profile = ResolvedModelProfile.model_validate(profile.model_dump())
        super().__init__(
            model_id=self.profile.identity.request_model_id, flatten_messages_as_text=flatten_messages_as_text
        )
        self.service = service
        self.observer = observer if observer is not None else MessageObserver()
        self.cancellation_scope = cancellation_scope if cancellation_scope is not None else RunCancellationScope()
        self.stop_event = self.cancellation_scope.stop_event
        self.temperature = self.profile.parameter_values.get("temperature")
        self.top_p = self.profile.parameter_values.get("top_p")
        self.model_factory = self.profile.identity.provider_id
        self.display_name = self.profile.identity.display_name
        self.context_budget_snapshot = context_budget_snapshot
        self.capacity_snapshot = deepcopy(capacity_snapshot)
        self.last_input_token_count = None
        self.last_output_token_count = None
        self.last_finish_reason = None
        self.last_response_diagnostics = None
        self.last_attempt_number = None
        self.last_attempt_id = None
        self.last_reasoning_preview = None
        self.last_cached_input_token_count = None
        self.last_prompt_cache_usage = None
        self.last_provider_cache_advice = None
        self.last_retry_count = 0
        self.last_context_evidence = None

    @classmethod
    def from_profile(cls, profile, api_key, *, http_headers=None, observer=None, cancellation_scope=None):
        """Construct the compatibility model with the shared transport and retry policy."""
        auth = AuthenticationRegistry()
        service = ModelService(
            lambda snapshot: auth.sender_for(snapshot, lambda _tenant, _reference: api_key, http_headers=http_headers),
            retry_policy=DEFAULT_MODEL_RETRY,
        )
        return cls(profile, service, observer=observer, cancellation_scope=cancellation_scope)

    @property
    def context_budget_snapshot(self):
        return self._context_budget_snapshot

    @context_budget_snapshot.setter
    def context_budget_snapshot(self, value):
        self._context_budget_snapshot = parse_context_budget_snapshot(deepcopy(value)) if value is not None else None

    async def check_connectivity(self):
        """Probe endpoint/model with saved declarations through the same HTTP owner."""
        try:
            request, profile = self._request(
                [{"role": "user", "content": "Hello"}], LegacyInvocationOptions({}), None,
            )
            await self.service.ainvoke(
                request.model_copy(update={"stream": False}), profile, scope=self.cancellation_scope,
            )
            return True
        except Exception:
            return False

    def _request(self, messages, options, tools, *, profile=None):
        profile = options.resolve(self.profile if profile is None else profile)
        normalized = []
        for message in merge_system_messages(deepcopy(messages)):
            if isinstance(message, ChatMessage):
                message = {"role": message.role, "content": message.content}
            if not isinstance(message, dict) or not {"role", "content"} <= message.keys():
                raise ValueError("Legacy messages require role and content")
            message = deepcopy(message)
            if isinstance(message["content"], str):
                message["content"] = [{"type": "text", "text": message["content"]}]
            elif message["content"] is None:
                message["content"] = []
            normalized.append(message)
        cleaned = get_clean_message_list(
            normalized,
            role_conversions=tool_role_conversions,
            convert_images_to_image_urls=True,
            flatten_messages_as_text=self.flatten_messages_as_text,
        )
        request = ModelRequest(
            request_id=uuid4().hex,
            outlet_id=profile.outlet_id,
            config_revision=profile.config_revision,
            stream=True,
            messages=[
                ModelMessage(
                    semantic_role=getattr(message["role"], "value", message["role"]),
                    content_parts=(
                        [{"type": "text", "text": message["content"]}]
                        if isinstance(message["content"], str)
                        else message["content"]
                    ),
                )
                for message in cleaned
            ],
            tools=[
                ToolDefinition(
                    name=definition["function"]["name"],
                    description=definition["function"]["description"],
                    input_schema=definition["function"]["parameters"],
                )
                for definition in (get_tool_json_schema(tool) for tool in tools or [])
            ],
        )
        return request, profile

    @staticmethod
    def _terminal(error):
        return ModelInvocationTerminalError(
            _ERROR_CODES.get(error.category, ModelErrorCode.UNKNOWN_ERROR),
            error.attempt,
            cause=ModelServiceError(error),
            public_messages={lang: model_error_message(error, lang) for lang in ("en", "zh")},
        )

    def _reset_response(self, profile):
        self.last_input_token_count = self.last_output_token_count = self.last_finish_reason = None
        self.last_cached_input_token_count = self.last_prompt_cache_usage = None
        self.last_reasoning_preview = None
        self._has_response_content = False
        self.last_response_diagnostics = {
            "finish_reason": None, "content_chunk_count": 0, "content_char_count": 0,
            "reasoning_chunk_count": 0, "reasoning_char_count": 0,
            "input_tokens": None, "output_tokens": None,
            "requested_output_tokens": profile.parameter_values.get(
                "max_output_tokens", profile.parameter_values.get("max_tokens")
            ),
            "reasoning_only_budget_exhausted": False,
        }

    def _observe_event(self, event, profile):
        diagnostics = self.last_response_diagnostics
        kind = {"text_delta": "content", "reasoning_delta": "reasoning"}.get(event.type)
        if kind is not None and event.content_kind != "refusal":
            diagnostics[kind + "_chunk_count"] += 1
            diagnostics[kind + "_char_count"] += len(event.delta)
            if kind == "content":
                self._has_response_content |= bool(event.delta.strip())
        usage = event.usage if event.type == "usage" else event.message.usage if event.type == "message_completed" else None
        if usage is not None:
            self.last_input_token_count, self.last_output_token_count = usage.input_tokens, usage.output_tokens
            self.last_cached_input_token_count = usage.cached_input_tokens
            self.last_prompt_cache_usage = None
            diagnostics.update(input_tokens=usage.input_tokens, output_tokens=usage.output_tokens)
            if (
                usage.origin == "provider" and profile.capabilities.usage.input_includes_cached == "supported"
                and usage.input_tokens is not None and usage.cached_input_tokens is not None
                and usage.cached_input_tokens <= usage.input_tokens
            ):
                cached, total = usage.cached_input_tokens, usage.input_tokens
                self.last_prompt_cache_usage = PromptCacheUsage(
                    cached_input_tokens=cached, uncached_input_tokens=total - cached,
                    provider_cache_hit=cached > 0, hit_ratio=round(cached / total, 4) if total else 0.0,
                    metrics_source=usage.semantics_id or "provider_reported",
                )
        if event.type in {"message_completed", "error"}:
            self.last_finish_reason = (
                event.message.finish_reason if event.type == "message_completed" else event.error.finish_reason
            )
            diagnostics.update(
                finish_reason=self.last_finish_reason,
                reasoning_only_budget_exhausted=(
                    self.last_finish_reason == "length" and diagnostics["reasoning_char_count"] > 0
                    and not self._has_response_content
                ),
            )

    def _events(
        self, messages, options, tools, *, suppress_stream=False, empty_response_policy="accept", context_rebuild=None,
    ):
        if context_rebuild is not None and (
            not callable(context_rebuild) or iscoroutinefunction(context_rebuild)
            or iscoroutinefunction(getattr(context_rebuild, "__call__", None))
        ):
            raise TypeError("Legacy context_rebuild must be a synchronous callback")
        request, profile = self._request(messages, options, tools)

        def rebuild_request(_error):
            rebuilt = context_rebuild()
            rebuilt_messages = getattr(rebuilt, "messages", rebuilt)
            if not isinstance(rebuilt_messages, list):
                raise TypeError("context_rebuild must return FinalContext or a message list")
            self.last_context_evidence = getattr(rebuilt, "evidence", None)
            replacement, _ = self._request(rebuilt_messages, options, tools, profile=profile)
            return replacement.model_copy(update={"request_id": request.request_id})

        self.last_attempt_id = request.request_id
        self.last_attempt_number = None
        self.last_retry_count = 0
        self.last_context_evidence = None
        self._reset_response(profile)
        attempt_number = None
        completed = False
        if not suppress_stream:
            self.observer.current_mode = ProcessType.MODEL_OUTPUT_THINKING
        try:
            with self.service.stream(
                request, profile, scope=self.cancellation_scope, empty_response_policy=empty_response_policy,
                request_rebuild=rebuild_request if context_rebuild is not None else None,
            ) as events:
                for event in events:
                    if attempt_number != event.attempt:
                        if attempt_number is not None and not suppress_stream:
                            self.observer.rollback_model_attempt(request.request_id, attempt_number)
                        attempt_number = event.attempt
                        self.last_attempt_id = request.request_id
                        self.last_attempt_number = event.attempt
                        self.last_retry_count = event.attempt - 1
                        self._reset_response(profile)
                        if not suppress_stream:
                            self.observer.begin_model_attempt(request.request_id, event.attempt)
                    self._observe_event(event, profile)
                    if event.type == "error":
                        raise self._terminal(event.error)
                    if event.type == "reasoning_delta" and not suppress_stream:
                        self.observer.add_model_reasoning_content(event.delta)
                    elif event.type == "text_delta" and event.content_kind != "refusal" and not suppress_stream:
                        self.observer.add_model_new_token(event.delta)
                    elif event.type == "message_completed":
                        completed = True
                        if not suppress_stream:
                            self.observer.flush_remaining_tokens()
                        message = event.message
                        self.last_finish_reason = message.finish_reason
                        self.last_input_token_count = message.usage.input_tokens
                        self.last_output_token_count = message.usage.output_tokens
                    yield event
        except ModelServiceError as error:
            raise self._terminal(error.error) from None
        finally:
            if not completed and attempt_number is not None and not suppress_stream:
                self.observer.rollback_model_attempt(request.request_id, attempt_number)

    def generate(
        self, messages, stop_sequences=None, response_format=None, tools_to_call_from=None,
        *, _defer_attempt_commit=False, _suppress_attempt_stream=False, _retry_empty_response=True,
        context_budget_snapshot=None, context_rebuild=None, **kwargs,
    ):
        if any(type(value) is not bool for value in (
            _defer_attempt_commit, _suppress_attempt_stream, _retry_empty_response
        )):
            raise ValueError("Attempt controls must be booleans")
        options = LegacyInvocationOptions(
            kwargs, stop_sequences, response_format,
            context_budget_snapshot if context_budget_snapshot is not None else self.context_budget_snapshot,
            self.capacity_snapshot,
        )
        events = self._events(
            messages, options, tools_to_call_from, suppress_stream=_suppress_attempt_stream,
            empty_response_policy="retry" if _retry_empty_response else "fail",
            context_rebuild=context_rebuild,
        )
        try:
            for event in events:
                if event.type != "message_completed":
                    continue
                message = event.message
                result = ChatMessage.from_dict(
                    {
                        "role": "assistant",
                        "content": "".join(
                            part["text"] for part in message.content_parts if part.get("type") == "text"
                        ),
                        "tool_calls": [
                            {
                                "id": call.provider_call_id,
                                "type": "function",
                                "function": {
                                    "name": call.name,
                                    "arguments": call.raw_arguments,
                                },
                            }
                            for call in message.tool_calls
                        ],
                    },
                    raw=message,
                )
                if message.usage.input_tokens is not None and message.usage.output_tokens is not None:
                    result.token_usage = TokenUsage(message.usage.input_tokens, message.usage.output_tokens)
                result.model_attempt_id = self.last_attempt_id
                result.model_attempt_number = event.attempt
                result.model_attempt_commit_deferred = _defer_attempt_commit and not _suppress_attempt_stream
                result.refusal = message.refusal
                if not _defer_attempt_commit and not _suppress_attempt_stream:
                    self.observer.commit_model_attempt(self.last_attempt_id, event.attempt)
                return result
            raise RuntimeError("Model stream ended without completion")
        finally:
            events.close()

    def generate_stream(
        self, messages, stop_sequences=None, response_format=None, tools_to_call_from=None,
        *, _suppress_attempt_stream=False, context_budget_snapshot=None, context_rebuild=None, **kwargs,
    ):
        if type(_suppress_attempt_stream) is not bool:
            raise ValueError("Attempt controls must be booleans")
        options = LegacyInvocationOptions(
            kwargs, stop_sequences, response_format,
            context_budget_snapshot if context_budget_snapshot is not None else self.context_budget_snapshot,
            self.capacity_snapshot,
        )
        events = self._events(
            messages, options, tools_to_call_from, suppress_stream=_suppress_attempt_stream, context_rebuild=context_rebuild,
        )
        try:
            for event in events:
                delta = self._stream_delta(event)
                if delta is not None:
                    yield delta
                if event.type == "message_completed":
                    if not _suppress_attempt_stream:
                        self.observer.commit_model_attempt(self.last_attempt_id, event.attempt)
        finally:
            events.close()

    @staticmethod
    def _stream_delta(event):
        if event.type == "text_delta" and event.content_kind != "refusal":
            return ChatMessageStreamDelta(content=event.delta)
        elif event.type == "tool_call_delta":
            delta = event.tool_call_delta
            return ChatMessageStreamDelta(
                tool_calls=[
                    ChatMessageToolCallStreamDelta(
                        index=delta.index,
                        id=delta.provider_call_id,
                        type="function",
                        function=ChatMessageToolCallFunction(
                            name=delta.name_delta or "", arguments=delta.arguments_delta or ""
                        ),
                    )
                ]
            )
        elif event.type == "usage":
            usage = event.usage
            if usage.input_tokens is not None and usage.output_tokens is not None:
                return ChatMessageStreamDelta(token_usage=TokenUsage(usage.input_tokens, usage.output_tokens))

    async def agenerate_stream(
        self, messages, stop_sequences=None, response_format=None, tools_to_call_from=None, **kwargs,
    ):
        """Compatibility deltas over the asynchronous transport; the caller owns iteration."""
        options = LegacyInvocationOptions(
            kwargs, stop_sequences, response_format, self.context_budget_snapshot, self.capacity_snapshot,
        )
        request, profile = self._request(messages, options, tools_to_call_from)
        try:
            async with self.service.astream(request, profile, scope=self.cancellation_scope) as events:
                async for event in events:
                    if event.type == "error":
                        raise self._terminal(event.error)
                    delta = self._stream_delta(event)
                    if delta is not None:
                        yield delta
        except ModelServiceError as error:
            raise self._terminal(error.error) from None
