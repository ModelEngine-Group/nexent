# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""One-message OpenAI-compatible stream state, independent of HTTP execution."""

import json
from uuid import uuid4

from nexent.core.model_service.adapters.openai_chat import ModelAdapterError, OpenAIChatAdapter, _usage, parse_json
from nexent.core.model_service.contracts import ModelEvent, ModelRequest, ToolCallDelta
from nexent.core.model_service.http_contracts import RawHttpResponse
from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile
from nexent.core.model_service.sse import SSEEvent


class OpenAIStreamDecoder:
    """Accumulate complete calls only after a declared provider completion boundary."""

    def __init__(
        self,
        request: ModelRequest,
        profile: ResolvedModelProfile,
        *,
        require_done: bool = False,
        max_message_bytes: int = 32 * 1024 * 1024,
        max_tool_calls: int = 128,
    ):
        if type(require_done) is not bool or any(
            type(value) is not int or value <= 0 for value in (max_message_bytes, max_tool_calls)
        ):
            raise ValueError("Invalid model stream limits or completion declaration")
        if not request.stream:
            raise ModelAdapterError("MODEL_STREAM_REQUEST_REQUIRED")
        self._request, self._profile = request, profile
        self._require_done = require_done
        self._limit, self._tool_limit, self._size = max_message_bytes, max_tool_calls, 0
        self._message_id = uuid4()
        self._sequence = 0
        self._closed = False
        self._finish = None
        self._identity = {}
        self._content, self._reasoning, self._refusal = [], [], []
        self._calls = {}
        self._usage_raw = None
        self._unknown = []

    def _fail(self, category):
        self._closed = True
        raise ModelAdapterError(category)

    def _event(self, kind, **payload):
        self._sequence += 1
        return ModelEvent(
            request_id=self._request.request_id,
            message_id=self._message_id,
            sequence=self._sequence,
            type=kind,
            **payload,
        )

    def _complete(self):
        if self._finish is None:
            self._fail("MODEL_RESPONSE_INCOMPLETE")
        ordered = sorted(self._calls.items())
        message = {
            "role": "assistant",
            "content": "".join(self._content) if self._content else None,
            "reasoning_content": "".join(self._reasoning) if self._reasoning else None,
            "refusal": "".join(self._refusal) if self._refusal else None,
            "tool_calls": [
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {"name": "".join(call["name"]), "arguments": "".join(call["arguments"])},
                }
                for _, call in ordered
            ],
        }
        if self._finish == "tool_calls" and not ordered:
            self._fail("MODEL_TOOL_CALL_INVALID")
        body = {
            **self._identity,
            "choices": [{"index": 0, "message": message, "finish_reason": self._finish}],
            "usage": self._usage_raw,
        }
        raw = RawHttpResponse(200, {}, json.dumps(body, ensure_ascii=False).encode())
        complete = OpenAIChatAdapter().decode_response(raw, self._request, self._profile)
        calls = [
            call.model_copy(update={"index": index, "local_call_id": state["local_id"]})
            for call, (index, state) in zip(complete.tool_calls, ordered)
        ]
        complete = complete.model_copy(
            update={
                "message_id": self._message_id,
                "tool_calls": calls,
                "provider_metadata": {**complete.provider_metadata, "unmapped_delta_fields": self._unknown},
            }
        )
        self._closed = True
        return [self._event("message_completed", message=complete, finish_reason=complete.finish_reason)]

    def push(self, frame: SSEEvent) -> list[ModelEvent]:
        if self._closed:
            raise ModelAdapterError("MODEL_STREAM_CLOSED")
        try:
            self._size += len(frame.data.encode("utf-8"))
            if self._size > self._limit:
                self._fail("MODEL_RESPONSE_TOO_LARGE")
            if frame.data == "[DONE]":
                return self._complete()
            body = parse_json(frame.data)
            if isinstance(body, dict) and body.get("error") is not None:
                raise ModelAdapterError(
                    "MODEL_PROVIDER_ERROR", response=RawHttpResponse(200, {}, frame.data.encode("utf-8"), frame.sensitive_values)
                )
            if not isinstance(body, dict) or not isinstance(body.get("choices"), list):
                self._fail("MODEL_RESPONSE_INVALID")
            for key in ("id", "model"):
                if key in body:
                    value = body[key]
                    if (
                        not isinstance(value, str)
                        or not value.strip()
                        or key in self._identity
                        and self._identity[key] != value
                    ):
                        self._fail("MODEL_STREAM_IDENTITY_CONFLICT")
                    self._identity[key] = value
            events = []
            if body.get("usage") is not None:
                usage = _usage(body["usage"], self._profile.capabilities.usage.semantics_id)
                if self._usage_raw is not None and self._usage_raw != body["usage"]:
                    self._fail("MODEL_USAGE_CONFLICT")
                if self._usage_raw is None:
                    self._usage_raw = body["usage"]
                    events.append(self._event("usage", usage=usage))
            choices = body["choices"]
            if not choices:
                if body.get("usage") is None:
                    self._fail("MODEL_RESPONSE_INVALID")
                return events
            if len(choices) != 1:
                self._fail("MODEL_RESPONSE_INVALID")
            choice = choices[0]
            if not isinstance(choice, dict) or type(choice.get("index")) is not int or choice["index"] != 0:
                self._fail("MODEL_RESPONSE_INVALID")
            delta = choice.get("delta")
            if not isinstance(delta, dict) or delta.get("role", "assistant") != "assistant":
                self._fail("MODEL_RESPONSE_INVALID")
            if self._finish is not None:
                # A generation boundary can precede an empty usage/metadata trailer.
                for key in ("content", "reasoning_content", "refusal"):
                    value = delta.get(key)
                    if value is not None and not isinstance(value, str):
                        self._fail("MODEL_RESPONSE_INVALID")
                calls = delta.get("tool_calls")
                if calls is not None and not isinstance(calls, list):
                    self._fail("MODEL_TOOL_CALL_INVALID")
                if any(delta.get(key) for key in ("content", "reasoning_content", "refusal", "tool_calls")):
                    self._fail("MODEL_STREAM_AFTER_FINISH")
                finish = choice.get("finish_reason")
                if finish is not None:
                    if not isinstance(finish, str) or not finish.strip():
                        self._fail("MODEL_RESPONSE_INVALID")
                    if finish != self._finish:
                        self._fail("MODEL_STREAM_FINISH_CONFLICT")
                return events
            for key, target, kind in (
                ("reasoning_content", self._reasoning, "reasoning_delta"),
                ("content", self._content, "text_delta"),
                ("refusal", self._refusal, "text_delta"),
            ):
                value = delta.get(key)
                if value is None:
                    continue
                if not isinstance(value, str):
                    self._fail("MODEL_RESPONSE_INVALID")
                if value:
                    target.append(value)
                    payload = {"delta": value}
                    if kind == "text_delta":
                        payload["content_kind"] = "refusal" if key == "refusal" else "text"
                    events.append(self._event(kind, **payload))
            raw_calls = delta.get("tool_calls")
            if raw_calls is not None:
                if not isinstance(raw_calls, list):
                    self._fail("MODEL_TOOL_CALL_INVALID")
                for raw_call in raw_calls:
                    events.append(self._call_delta(raw_call))
            unknown = {
                key: value
                for key, value in delta.items()
                if key not in {"role", "content", "reasoning_content", "refusal", "tool_calls"}
            }
            if unknown:
                self._unknown.append(unknown)
            finish = choice.get("finish_reason")
            if finish is not None:
                if not isinstance(finish, str) or not finish.strip():
                    self._fail("MODEL_RESPONSE_INVALID")
                self._finish = finish
            return events
        except ModelAdapterError:
            self._closed = True
            raise
        except (ValueError, TypeError, UnicodeError, RecursionError):
            self._fail("MODEL_RESPONSE_INVALID")

    def _call_delta(self, raw):
        if not isinstance(raw, dict) or type(raw.get("index")) is not int or raw["index"] < 0:
            self._fail("MODEL_TOOL_CALL_INVALID")
        index = raw["index"]
        if index not in self._calls:
            if len(self._calls) >= self._tool_limit:
                self._fail("MODEL_TOOL_CALL_LIMIT")
            self._calls[index] = {"local_id": uuid4(), "id": None, "name": [], "arguments": []}
        state = self._calls[index]
        if "type" in raw and raw["type"] != "function":
            self._fail("MODEL_TOOL_CALL_INVALID")
        if raw.get("id") is not None:
            value = raw["id"]
            if not isinstance(value, str) or not value.strip() or state["id"] is not None and state["id"] != value:
                self._fail("MODEL_STREAM_IDENTITY_CONFLICT")
            state["id"] = value
        function = raw.get("function", {})
        if not isinstance(function, dict):
            self._fail("MODEL_TOOL_CALL_INVALID")
        for key in ("name", "arguments"):
            if key in function:
                if not isinstance(function[key], str):
                    self._fail("MODEL_TOOL_CALL_INVALID")
                state[key].append(function[key])
        return self._event(
            "tool_call_delta",
            tool_call_delta=ToolCallDelta(
                local_call_id=state["local_id"],
                index=index,
                provider_call_id=state["id"],
                name_delta=function.get("name"),
                arguments_delta=function.get("arguments"),
            ),
        )

    def finish(self) -> list[ModelEvent]:
        if self._closed:
            return []
        if self._require_done:
            self._fail("MODEL_RESPONSE_INCOMPLETE")
        try:
            return self._complete()
        except ModelAdapterError:
            self._closed = True
            raise
