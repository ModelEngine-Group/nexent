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


def current_time_prefix(language: str) -> str:
    return render_user_context(language, "current_time_prefix")


def has_current_time_prefix(message: str) -> bool:
    """Recognize complete runtime time markers in legacy prefixes or suffixes."""
    return bool(re.search(r"(?m)^\[(?:当前时间|Current time): [^\]\n]+\](?:\n|$)", message))

