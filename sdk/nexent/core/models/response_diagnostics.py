# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Bounded, content-free evidence for provider response failures."""

import hashlib
import json
import re
from collections import deque
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from typing import Any


def _identifier(value: Any) -> str | None:
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:/-]{1,160}", value):
        return value
    return None


def _fingerprint_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _fingerprint_value(item) for key, item in value.items()
            if str(key).lower() not in {"api_key", "authorization", "headers", "password", "token"}
        }
    if isinstance(value, (list, tuple)):
        return [_fingerprint_value(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return _fingerprint_value(asdict(value))
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return type(value).__name__


class ResponseDiagnostics:
    """Keep identifiers and redacted chunk structure, never generated text."""

    def __init__(self, request: Mapping[str, Any], *, capture_chunks: bool = False):
        encoded = json.dumps(_fingerprint_value(request), sort_keys=True, ensure_ascii=True).encode()
        self.fingerprint = hashlib.sha256(encoded).hexdigest()
        self.capture_chunks = capture_chunks
        self.first: list[dict[str, Any]] = []
        self.last: deque[dict[str, Any]] = deque(maxlen=4)
        self.response_id = None
        self.response_model = None

    def add(self, chunk: Any) -> None:
        self.response_id = _identifier(getattr(chunk, "id", None)) or self.response_id
        self.response_model = _identifier(getattr(chunk, "model", None)) or self.response_model
        if not self.capture_chunks:
            return
        choices = getattr(chunk, "choices", None)
        record: dict[str, Any] = {"choices": []}
        for choice in choices[:4] if isinstance(choices, (list, tuple)) else ():
            delta = getattr(choice, "delta", None)
            content = getattr(delta, "content", None)
            reasoning = getattr(delta, "reasoning", None)
            if reasoning is None:
                reasoning = getattr(delta, "reasoning_content", None)
            calls = getattr(delta, "tool_calls", None)
            record["choices"].append({
                "content_chars": len(content) if isinstance(content, str) else 0,
                "reasoning_chars": len(reasoning) if isinstance(reasoning, str) else 0,
                "tool_call_count": len(calls) if isinstance(calls, (list, tuple)) else 0,
                "finish_reason": _identifier(getattr(choice, "finish_reason", None)),
            })
        if len(self.first) < 4:
            self.first.append(record)
        else:
            self.last.append(record)

    def summary(self, stream: Any = None) -> dict[str, Any]:
        request_id = None
        seen: set[int] = set()
        for _ in range(4):
            if stream is None or id(stream) in seen:
                break
            seen.add(id(stream))
            response = getattr(stream, "response", None)
            headers = getattr(response, "headers", None)
            if isinstance(headers, Mapping):
                request_id = _identifier(headers.get("x-request-id")) or _identifier(headers.get("x-tt-logid"))
                if request_id:
                    break
            stream = getattr(stream, "_stream", None)
        result = {
            "request_fingerprint": self.fingerprint,
            "response_id": self.response_id,
            "response_model": self.response_model,
            "provider_request_id": request_id,
        }
        if self.capture_chunks:
            result["chunks"] = [*self.first, *self.last]
        return result
