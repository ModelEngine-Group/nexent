# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Load existing clarification prompts without changing their contents."""

from nexent.core.prompts import load_prompt


CLARIFICATION_SCHEMA_GUIDANCE = load_prompt("en", "agent/human_interaction")["questions_description"]
CLARIFICATION_POLICY = load_prompt("en", "agent/human_interaction")["clarification_policy"]


def clarification_policy(tool_name: str, language: str = "en") -> str:
    """Describe the selected terminal form name without registering a Python tool."""
    policy = load_prompt(language, "agent/human_interaction")["clarification_policy"]
    return policy.replace("ask_user", tool_name)
