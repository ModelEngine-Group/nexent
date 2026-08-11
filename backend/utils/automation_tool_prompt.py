from collections.abc import Iterable


AUTOMATION_TOOL_NAME = "create_scheduled_task_proposal"


def build_automation_tool_policy(language: str, tool_names: Iterable[str]) -> str:
    """Build platform policy only when the proposal tool is available."""
    if AUTOMATION_TOOL_NAME not in set(tool_names):
        return ""

    if language == "zh":
        return (
            "### 定时任务工具策略\n"
            "- 当用户明确要求任务在未来、延迟或周期性自动执行时，必须调用 "
            "`create_scheduled_task_proposal`，不要立即执行业务动作。\n"
            "- `request_text` 必须原样复制用户当前消息中的定时执行请求，不得补充 "
            "Agent、工具、知识库、数据源或实现步骤。\n"
            "- 创建提案时，`create_scheduled_task_proposal` 必须是本次代码中的唯一工具调用。"
            "不要同时调用其他工具或助手。\n"
            "- 工具只创建待确认提案。调用后直接用 `final_answer` 返回工具结果，"
            "并停止本轮执行。\n"
            "- 立即执行的普通请求、询问某个时间的数据、解释时间表达式、"
            "事实陈述和个人习惯"
            "不要调用此工具。"
        )

    return (
        "### Scheduled-task Tool Policy\n"
        "- When the user explicitly asks for a task to run later, after a delay, or repeatedly, "
        "call `create_scheduled_task_proposal`. Do not execute the business action now.\n"
        "- Copy the scheduling request from the current user message verbatim into `request_text`. "
        "Do not add Agent, tool, knowledge-base, data-source, or implementation details.\n"
        "- `create_scheduled_task_proposal` must be the only tool call in that code action. "
        "Do not call another tool or agent in the same action.\n"
        "- The tool creates a pending proposal only. Return its result immediately with "
        "`final_answer` and stop the turn.\n"
        "- Do not call this tool for immediate requests, questions about data at a time, "
        "schedule explanations, factual statements, or personal habits."
    )
