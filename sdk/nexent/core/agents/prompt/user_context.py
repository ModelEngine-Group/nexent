"""Render locale-specific context added to user messages."""

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
    return render_prompt_text(template[key], values or {})


def current_time_prefix(language: str) -> str:
    return render_user_context(language, "current_time_prefix")


def has_current_time_prefix(message: str) -> bool:
    return any(message.startswith(current_time_prefix(lang)) for lang in ("zh", "en"))

