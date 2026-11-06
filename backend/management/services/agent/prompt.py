# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Default Agent prompt resources and visible-tool policy."""

from collections.abc import Iterable, Mapping

from nexent.core.agents.prompt import AgentPromptBundle
from nexent.core.agents.prompt.meta import load_generation_template


def load_agent_prompt_bundle(
    *,
    is_manager: bool,
    language: str,
    template_override: Mapping | None = None,
) -> AgentPromptBundle:
    """Select a YAML template and delegate its contract validation to the SDK."""
    role = "manager" if is_manager else "managed"
    if language not in {"zh", "en"}:
        raise ValueError("unsupported Agent prompt language")
    return AgentPromptBundle.from_resource(
        role=role,
        language=language,
        template_override=template_override,
    )


def load_default_generation_prompt(language: str) -> dict[str, str]:
    """Load the SDK default resource without tenant storage or private overrides."""
    selected_language = "en" if language == "en" else "zh"
    return {
        key.lower(): value
        for key, value in load_generation_template(selected_language).items()
        if isinstance(value, str)
    }


def should_enable_memory_tool_policy(tool_names: Iterable[str]) -> bool:
    """Enable memory guidance only for a final visible store tool."""
    return "store_memory" in set(tool_names)


AUTOMATION_TOOL_NAME = "create_scheduled_task_proposal"


def should_enable_automation_tool_policy(tool_names: Iterable[str]) -> bool:
    """Enable proposal guidance only for a final visible proposal tool."""
    return AUTOMATION_TOOL_NAME in set(tool_names)
