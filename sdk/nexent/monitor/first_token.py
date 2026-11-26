# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Semantic first-output detection shared by model and client monitoring."""

import math
from collections.abc import Mapping
from typing import Any


def _field(value: Any, name: str) -> Any:
    return value.get(name) if isinstance(value, Mapping) else getattr(value, name, None)


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def stream_token_basis(chunk: Any) -> str | None:
    """Ignore role, usage, finish and tool identity chunks without output deltas."""
    choices = _field(chunk, "choices")
    if not isinstance(choices, (list, tuple)):
        return None
    for choice in choices:
        delta = _field(choice, "delta")
        if _nonempty(_field(delta, "content")):
            return "content"
        if any(_nonempty(_field(delta, key)) for key in ("reasoning", "reasoning_content")):
            return "reasoning"
        calls = _field(delta, "tool_calls")
        if isinstance(calls, (list, tuple)) and any(
            _nonempty(_field(_field(call, "function"), "arguments")) for call in calls
        ):
            return "tool_delta"
        if _nonempty(_field(_field(delta, "function_call"), "arguments")):
            return "tool_delta"
    return None


def valid_ttft(value: Any, duration: float | None = None) -> float | None:
    """Keep unknown and invalid timings separate from a measured zero."""
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        return None
    if duration is not None and (not math.isfinite(duration) or duration < value):
        return None
    return float(value)
