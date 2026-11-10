# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Immutable completed-request observations for advisory context maintenance.

Only provider input usage is measured. Differences for a subsequent payload are
estimates, including new tool schemas and results; they never authorize rejection.
No request bodies or credentials are retained in an observation.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel


def normalized_chars_per_token(value: Any) -> float:
    """Keep an unavailable local estimation ratio from blocking inference."""
    return value if type(value) in (int, float) and math.isfinite(value) and value > 0 else 1.5


def _json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode='json')
    return str(value)


def request_characters(messages, tools) -> int:
    """Measure the entire caller payload, preserving native tool boundaries."""
    normalized = []
    for message in messages:
        if isinstance(message, dict):
            normalized.append({key: message[key] for key in ('role', 'content', 'tool_calls', 'tool_call_id')
                               if message.get(key) is not None})
        else:
            normalized.append({key: getattr(message, key) for key in ('role', 'content', 'tool_calls', 'tool_call_id')
                               if getattr(message, key, None) is not None})
    schemas = []
    for tool in tools or ():
        if isinstance(tool, dict):
            schemas.append(tool)
        else:
            from smolagents.models import get_tool_json_schema
            schemas.append(get_tool_json_schema(tool))
    return len(json.dumps({'messages': normalized, 'tools': schemas}, ensure_ascii=False,
                          sort_keys=True, default=_json_value))


def context_model_key(model) -> str:
    """Bind observations to the saved outlet and its configuration revision."""
    profile = getattr(model, 'profile', None)
    value = profile.model_dump(mode='json') if isinstance(profile, BaseModel) else {
        'model_id': getattr(model, 'model_id', None),
        'model_name': getattr(model, 'model_name', None),
        'model_factory': getattr(model, 'model_factory', None),
    }
    return hashlib.sha256(json.dumps({"instance": id(model), "configuration": value},
                                     sort_keys=True, default=_json_value).encode()).hexdigest()


@dataclass(frozen=True)
class InputUsageObservation:
    input_tokens: int
    input_characters: int
    model_key: str
    request_id: str
    attempt: int

    @classmethod
    def capture(cls, *, usage, messages, tools, model_key, request_id, attempt):
        """Accept only complete provider observations, retaining unknown as absent."""
        tokens = getattr(usage, 'input_tokens', None)
        if getattr(usage, 'origin', None) != 'provider' or type(tokens) is not int or tokens < 0:
            return None
        return cls(tokens, request_characters(messages, tools), model_key, request_id, attempt)

    def estimate(self, *, input_characters: int, chars_per_token: float) -> int:
        """Account for the whole changed payload without calling it measured usage."""
        delta = (input_characters - self.input_characters) / normalized_chars_per_token(chars_per_token)
        return max(0, math.ceil(self.input_tokens + delta))
