# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Shared clarification policy and Core-specific wire examples."""

import json
import re

from nexent.core.prompts import load_prompt


CLARIFICATION_SCHEMA_GUIDANCE = load_prompt("en", "agent/human_interaction")["questions_description"]
CLARIFICATION_POLICY = load_prompt("en", "agent/human_interaction")["clarification_policy"]


def child_information_policy(language="en"):
    """Only the parent may turn missing child-task information into a user question."""
    if language == "zh":
        return (
            "你正在执行父智能体委派的子任务，不能直接向用户发起澄清或调用 ask_user。"
            "缺少必要信息时，不要猜测、重复提问或继续执行依赖该信息的操作；"
            "请在最终结果中明确返回缺失信息和阻塞原因，由父智能体统一决定是否向用户澄清。"
        )
    return (
        "You are executing a delegated subagent task. Do not ask the user directly or call ask_user. "
        "If essential information is missing, do not guess, repeat questions or perform dependent actions. "
        "Return the missing information and blocking reason in your final result to the parent agent; "
        "only the parent decides whether to ask the user for clarification."
    )


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
