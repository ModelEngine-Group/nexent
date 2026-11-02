# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Provider-independent model messages, requests and complete responses."""

from typing import Annotated, Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, JsonValue, model_validator

from nexent.core.model_service.profiles.contracts import NonBlankString, ProfileContract


NonnegativeInt = Annotated[int, Field(ge=0)]


class ToolCall(ProfileContract):
    """Complete protocol call; parsing never constitutes execution permission."""

    local_call_id: UUID = Field(default_factory=uuid4)
    provider_call_id: NonBlankString
    index: NonnegativeInt
    name: NonBlankString
    raw_arguments: str = Field(repr=False)
    parsed_arguments: dict[str, JsonValue] | None = Field(default=None, repr=False)
    argument_error: Literal["INVALID_TOOL_ARGUMENTS"] | None = None


class ToolDefinition(ProfileContract):
    name: NonBlankString
    description: str
    input_schema: dict[str, JsonValue] = Field(repr=False)


class ModelMessage(ProfileContract):
    message_id: UUID = Field(default_factory=uuid4)
    semantic_role: NonBlankString
    content_parts: list[dict[str, JsonValue]] = Field(default_factory=list, repr=False)
    reasoning_parts: list[dict[str, JsonValue]] = Field(default_factory=list, repr=False)
    tool_calls: list[ToolCall] = Field(default_factory=list, repr=False)
    tool_call_id: NonBlankString | None = None
    source: NonBlankString | None = None


class ModelRequest(ProfileContract):
    request_id: NonBlankString
    outlet_id: Annotated[int, Field(gt=0)] | None
    config_revision: Annotated[int, Field(gt=0)]
    messages: list[ModelMessage] = Field(min_length=1, repr=False)
    tools: list[ToolDefinition] = Field(default_factory=list, repr=False)
    stream: bool = False
    purpose: NonBlankString = "agent"
    run_id: NonBlankString | None = None

    @model_validator(mode="after")
    def validate_identities(self) -> Self:
        if len({message.message_id for message in self.messages}) != len(self.messages):
            raise ValueError("Model message identities must be unique")
        if len({tool.name for tool in self.tools}) != len(self.tools):
            raise ValueError("Model tool names must be unique")
        return self


class TokenUsage(ProfileContract):
    input_tokens: NonnegativeInt | None = None
    output_tokens: NonnegativeInt | None = None
    total_tokens: NonnegativeInt | None = None
    cached_input_tokens: NonnegativeInt | None = None
    reasoning_tokens: NonnegativeInt | None = None
    origin: Literal["provider", "unknown"] = "unknown"
    semantics_id: NonBlankString | None = None


class AssistantMessage(ProfileContract):
    message_id: UUID = Field(default_factory=uuid4)
    content_parts: list[dict[str, JsonValue]] = Field(default_factory=list, repr=False)
    reasoning_parts: list[dict[str, JsonValue]] = Field(default_factory=list, repr=False)
    refusal: str | None = Field(default=None, repr=False)
    tool_calls: list[ToolCall] = Field(default_factory=list, repr=False)
    finish_reason: NonBlankString
    usage: TokenUsage = Field(default_factory=TokenUsage)
    provider_metadata: dict[str, JsonValue] = Field(default_factory=dict, repr=False)

    @model_validator(mode="after")
    def validate_call_identities(self) -> Self:
        for values in ([call.provider_call_id for call in self.tool_calls], [call.index for call in self.tool_calls]):
            if len(set(values)) != len(values):
                raise ValueError("Complete tool call identities must be unique")
        return self


class ToolCallDelta(ProfileContract):
    """Display/accumulation only: never contains parsed execution arguments."""

    local_call_id: UUID
    index: NonnegativeInt
    provider_call_id: NonBlankString | None = None
    name_delta: str | None = Field(default=None, repr=False)
    arguments_delta: str | None = Field(default=None, repr=False)


class ModelError(ProfileContract):
    diagnostic_code: NonBlankString | None = None
    message_source: Literal["system", "provider"] = "system"
    http_status: int | None = Field(default=None, exclude=True)
    parameter_name: str | None = Field(default=None, exclude=True)
    category: NonBlankString
    scope: Literal["transport", "provider", "protocol"]
    retryable: bool
    will_retry: bool = False
    attempt: Annotated[int, Field(gt=0)] = 1
    max_attempts: Annotated[int, Field(gt=0)] = 1
    provider_code: str | None = None
    safe_message: NonBlankString
    request_id: NonBlankString
    finish_reason: NonBlankString | None = None

    @model_validator(mode="after")
    def validate_attempt(self) -> Self:
        if self.attempt > self.max_attempts:
            raise ValueError("Model attempt exceeds its configured maximum")
        if self.will_retry and (not self.retryable or self.attempt >= self.max_attempts):
            raise ValueError("Model retry requires remaining attempts and a retryable error")
        return self


class ModelEvent(ProfileContract):
    request_id: NonBlankString
    message_id: UUID
    sequence: Annotated[int, Field(gt=0)]
    attempt: Annotated[int, Field(gt=0)] = 1
    type: Literal["text_delta", "reasoning_delta", "tool_call_delta", "message_completed", "usage", "error"]
    delta: str | None = Field(default=None, repr=False)
    content_kind: Literal["text", "refusal"] | None = None
    tool_call_delta: ToolCallDelta | None = Field(default=None, repr=False)
    message: AssistantMessage | None = Field(default=None, repr=False)
    usage: TokenUsage | None = None
    finish_reason: NonBlankString | None = None
    error: ModelError | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def validate_payload(self) -> Self:
        required = {
            "text_delta": "delta",
            "reasoning_delta": "delta",
            "tool_call_delta": "tool_call_delta",
            "message_completed": "message",
            "usage": "usage",
            "error": "error",
        }[self.type]
        payloads = {
            key for key in ("delta", "tool_call_delta", "message", "usage", "error") if getattr(self, key) is not None
        }
        if payloads != {required}:
            raise ValueError("Model event requires exactly its declared payload")
        if self.content_kind is not None and self.type != "text_delta":
            raise ValueError("Content kind applies only to text events")
        if self.type == "message_completed":
            if self.message.message_id != self.message_id or self.finish_reason != self.message.finish_reason:
                raise ValueError("Completion identity and finish reason must agree")
        elif self.finish_reason is not None:
            raise ValueError("Only completed messages carry finish reasons")
        if self.error is not None and self.error.request_id != self.request_id:
            raise ValueError("Model error request identity must agree")
        return self
