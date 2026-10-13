from collections.abc import Iterable

AUTOMATION_TOOL_NAME = "create_scheduled_task_proposal"


def should_enable_automation_tool_policy(tool_names: Iterable[str]) -> bool:
    """Enable proposal guidance only for a final visible proposal tool."""
    return AUTOMATION_TOOL_NAME in set(tool_names)
