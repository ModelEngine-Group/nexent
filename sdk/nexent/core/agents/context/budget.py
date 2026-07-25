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
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return _json_summary_to_markdown(parsed)
        # Non-dict JSON (rare) — return as plain text
        return cleaned
    except json.JSONDecodeError:
        logger.warning("Summary output is not valid JSON; keeping it transient")
        return cleaned


_SUMMARY_FIELD_HEADINGS: dict[str, str] = {
    "task_overview": "Task Overview",
    "completed_work": "Completed Work",
    "key_decisions": "Key Decisions",
    "pending_items": "Pending Items",
    "context_to_preserve": "Context to Preserve",
}


def _json_summary_to_markdown(data: dict) -> str:
    """Convert a structured JSON summary dict to Markdown with headings.

    Produces output like::

        # Compact Result of History

        ## Task Overview

        The user asked to ...

        ## Completed Work

        - Modified file A
        - Updated config B

    Unknown keys are rendered as ``## Pretty Key`` (title-cased).
    """
    sections: list[str] = []
    for key, value in data.items():
        heading = _SUMMARY_FIELD_HEADINGS.get(key, key.replace("_", " ").title())
        if isinstance(value, list):
            items = [str(v) for v in value if v]
            if not items:
                continue
            body = "\n".join(f"- {item}" for item in items)
        elif isinstance(value, str):
            body = value.strip()
            if not body:
                continue
        elif value is None:
            continue
        else:
            body = str(value)
        sections.append(f"## {heading}\n\n{body}")

    if not sections:
        # All fields empty — fall back to raw JSON so nothing is lost
        return json.dumps(data, ensure_ascii=False, indent=2)

    return "# Compact Result of History\n\n" + "\n\n".join(sections)

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
