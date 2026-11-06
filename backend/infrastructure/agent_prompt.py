# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Convert legacy prompt sections when decoding an exported Agent file."""

from collections.abc import Mapping
from typing import Any


LEGACY_PROMPT_FIELDS = (
    "duty_prompt", "constraint_prompt", "constraints_prompt", "few_shots_prompt", "few_shot_prompts",
)


def normalize_imported_agent_prompt(fields: Mapping[str, Any]) -> dict[str, Any]:
    """Consume old file fields once; current models and exports expose only prompt."""
    values = dict(fields)
    for key in ("prompt", *LEGACY_PROMPT_FIELDS):
        if values.get(key) is not None and not isinstance(values[key], str):
            raise ValueError(f"{key} must be a string or null")

    def consume_alias(canonical: str, legacy: str) -> Any:
        if legacy in values:
            value = values.pop(legacy)
            if canonical in values and values[canonical] != value:
                raise ValueError(f"{canonical} and legacy {legacy} must not conflict")
            values.setdefault(canonical, value)
        return values.get(canonical)

    consume_alias("prompt", "duty_prompt")
    constraint = consume_alias("constraint_prompt", "constraints_prompt") or ""
    examples = consume_alias("few_shots_prompt", "few_shot_prompts") or ""
    values.pop("constraint_prompt", None)
    values.pop("few_shots_prompt", None)
    if constraint.strip(" \t\n\r") or examples.strip(" \t\n\r"):
        duty = values.get("prompt") or ""
        sections = (("Responsibilities", duty), ("Constraints", constraint), ("Examples", examples))
        values["prompt"] = "\n\n".join(
            f"# {title}\n{content}" for title, content in sections if content and content.strip(" \t\n\r")
        )
    return values


def normalize_imported_agent_bundle(snapshot: Any) -> Any:
    """Normalize an external JSON import before canonical bundle validation."""
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("agent_info"), dict):
        return snapshot
    return {
        **snapshot,
        "agent_info": {
            agent_id: normalize_imported_agent_prompt(fields) if isinstance(fields, dict) else fields
            for agent_id, fields in snapshot["agent_info"].items()
        },
    }
