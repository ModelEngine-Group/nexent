# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Load existing clarification prompts without changing their contents."""

import json
import re

from nexent.core.prompts import load_prompt


CLARIFICATION_SCHEMA_GUIDANCE = load_prompt("en", "agent/human_interaction")["questions_description"]
CLARIFICATION_POLICY = load_prompt("en", "agent/human_interaction")["clarification_policy"]


def clarification_policy(tool_name: str, language: str = "en") -> str:
    """Describe the selected terminal form name without registering a Python tool."""
    policy = load_prompt(language, "agent/human_interaction")["clarification_policy"]
    return policy.replace("ask_user", tool_name)


def native_clarification_policy(tool_name: str, language: str = "en") -> str:
    """Keep shared clarification decisions while adapting only the native wire example."""
    policy = clarification_policy(tool_name, language)
    example = {"questions": [{"id": "topic", "type": "text", "required": True,
                              "title": "请补充缺少的关键信息" if language == "zh"
                              else "Please provide the essential missing information"}]}
    policy = re.sub(r"<code>.*?</code>", lambda _: json.dumps(example, ensure_ascii=False),
                    policy, flags=re.DOTALL)
    return policy + (
        "\nUse the native " + tool_name + " function with a JSON questions array. "
        "Do not put this call in Python, code tags or nexent_execute_python. "
        "It is a terminal interaction: call it alone, without other tool calls in the same response."
    )
