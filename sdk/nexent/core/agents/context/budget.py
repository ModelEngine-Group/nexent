"""Small, representation-agnostic helpers for context rendering and summaries."""
from __future__ import annotations

import json
import logging
import re
from typing import Any


logger = logging.getLogger("agent_context.budget")

def format_summary_output(raw_output: str) -> str | None:
    cleaned = raw_output.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    if not cleaned:
        return None
    try:
        return json.dumps(json.loads(cleaned), ensure_ascii=False, indent=2)
    except json.JSONDecodeError:
        logger.warning("Summary output is not valid JSON; keeping it transient")
        return cleaned

def _is_context_length_error(error: Exception) -> bool:
    text = str(error).lower()
    return any(marker in text for marker in (
        "context_length", "context length", "maximum context", "prompt is too long",
        "reduce the length", "too many tokens", "token limit", "input is too long",
        "input length", "exceeds context",
    ))

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
