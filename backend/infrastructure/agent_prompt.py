# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Normalize legacy prompt payloads at the persistence boundary."""

from collections.abc import Mapping
from typing import Any


PROMPT_FIELDS = ("duty_prompt", "constraint_prompt", "few_shots_prompt")


def normalize_agent_prompt_fields(fields: Mapping[str, Any], current_duty: str | None = None) -> dict[str, Any]:
    """Preserve partial updates and convert explicitly supplied legacy sections once."""
    patch = dict(fields)
    if not any(key in patch and patch[key] is not None for key in PROMPT_FIELDS):
        return patch
    duty = patch.get("duty_prompt")
    if duty is None:
        duty = current_duty
    constraint = patch.get("constraint_prompt") or ""
    examples = patch.get("few_shots_prompt") or ""
    if constraint.strip() or examples.strip():
        parts = []
        for title, content in (("Responsibilities", duty), ("Constraints", constraint), ("Examples", examples)):
            if content and content.strip():
                parts.append(f"# {title}\n{content}")
        duty = "\n\n".join(parts)
    patch.update(duty_prompt=duty or "", constraint_prompt="", few_shots_prompt="")
    return patch
