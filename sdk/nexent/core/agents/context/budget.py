# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Small, representation-agnostic helpers for context rendering and summaries."""
from __future__ import annotations

import logging
import re
from typing import Any

from ...model_errors import ModelErrorCode
from ...models.context_overflow import is_provider_context_overflow


logger = logging.getLogger("agent_context.budget")

def format_summary_output(raw_output: str) -> str | None:
    """Strip code fences and return cleaned text, or None if empty."""
    cleaned = raw_output.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:markdown|md|json)?\s*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    return cleaned or None


def _is_context_length_error(error: Exception) -> bool:
    error_code = getattr(error, "error_code", None)
    if error_code is not None:
        return error_code == ModelErrorCode.CONTEXT_OVERFLOW
    if is_provider_context_overflow(error):
        return True
    # Legacy providers may omit a machine-readable code. Require explicit
    # input/prompt pressure; output length is not an input overflow signal.
    text = str(error).lower()
    return any(marker in text for marker in ("prompt is too long", "input is too long", "exceeds context"))


def message_role(message: Any) -> str:
    role = message.get("role") if isinstance(message, dict) else getattr(message, "role", "")
    return str(getattr(role, "value", role))

def extract_message_text(message: Any) -> str:
    content = message.get("content", "") if isinstance(message, dict) else getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return str(content or "")
