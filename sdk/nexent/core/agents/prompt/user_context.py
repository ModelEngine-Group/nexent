"""Render locale-specific context added to user messages."""

import re
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from ...prompts import load_prompt, render_prompt_text


@lru_cache(maxsize=2)
def _template(language: str) -> dict[str, Any]:
    return load_prompt(language, "agent/user_context")


def render_user_context(language: str, key: str, values: Mapping[str, Any] | None = None) -> str:
    """Render one SDK-owned message fragment with explicit runtime values."""
    template = _template(language)
    values = dict(values or {})
    workspace = ""
    if key == "current_time" and "query" in values:
        query, separator, path = values["query"].rpartition("\n\nRun workspace:")
        if separator:
            values["query"] = query
            workspace = separator + path
    return render_prompt_text(template[key], values) + workspace


CURRENT_TIME_MARKER = re.compile(
    r"\n\n\[(?:当前时间|Current time): [^\]\n]+\](?=\n\nRun workspace:|$)"
)


def has_current_time_marker(message: str) -> bool:
    """Detect the runtime marker after the request and before its workspace."""
    return bool(CURRENT_TIME_MARKER.search(message))
