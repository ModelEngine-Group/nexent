# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Convert legacy prompt sections when decoding an exported Agent file."""

from collections.abc import Mapping
from typing import Any


def normalize_imported_agent_prompt(fields: Mapping[str, Any]) -> dict[str, Any]:
    """Consume old file fields once; current models and exports expose only duty_prompt."""
    values = dict(fields)
    for key in ("duty_prompt", "constraint_prompt", "few_shots_prompt"):
        if values.get(key) is not None and not isinstance(values[key], str):
            raise ValueError(f"{key} must be a string or null")
    constraint = values.pop("constraint_prompt", None) or ""
    examples = values.pop("few_shots_prompt", None) or ""
    if constraint.strip() or examples.strip():
        duty = values.get("duty_prompt") or ""
        sections = (("Responsibilities", duty), ("Constraints", constraint), ("Examples", examples))
        values["duty_prompt"] = "\n\n".join(
            f"# {title}\n{content}" for title, content in sections if content and content.strip()
        )
    return values
