"""Compose requests for the existing memory workflows."""

from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from ...prompts import load_prompt
from .auxiliary import AuxiliaryPrompt


_MEMORY_RESOURCES = {
    "memory_extraction": "memory/fa_extraction",
    "memory_dreaming": "memory/dreaming_user",
}


def load_memory_template(operation: str) -> dict[str, Any]:
    """Read the English memory workflow template for validation and inspection."""
    return load_prompt("en", _MEMORY_RESOURCES[operation])


def compose_memory_prompt(
    operation: str, values: Mapping[str, Any],
    *, template_override: Mapping[str, Any] | None = None,
) -> AuxiliaryPrompt:
    """Render the memory templates' original Python-format placeholders."""
    if operation not in _MEMORY_RESOURCES:
        raise ValueError("Unsupported memory prompt operation")
    template = dict(template_override or load_memory_template(operation))
    return AuxiliaryPrompt(
        system=template["system"],
        user=template["user"].format(**values),
    )


def format_dreaming_source(field: str, values: Mapping[str, Any]) -> str:
    """Render one source block used by the backend's map/reduce chunker."""
    if field not in {"source_full", "source_prior", "source_evidence", "map_summary"}:
        raise ValueError("Unsupported dreaming source field")
    return _dreaming_source_fields()[field].format(**values)


@lru_cache(maxsize=1)
def _dreaming_source_fields() -> dict[str, Any]:
    return load_memory_template("memory_dreaming")
