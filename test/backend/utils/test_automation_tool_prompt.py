from utils.automation_tool_prompt import build_automation_tool_policy


def test_automation_tool_policy_is_empty_when_tool_is_unavailable():
    assert build_automation_tool_policy("zh", ["other_tool"]) == ""


def test_automation_tool_policy_uses_requested_language():
    zh_policy = build_automation_tool_policy("zh", ["create_scheduled_task_proposal"])
    en_policy = build_automation_tool_policy("en", ["create_scheduled_task_proposal"])

    assert "定时任务工具策略" in zh_policy
    assert "必须原样复制" in zh_policy
    assert "Scheduled-task Tool Policy" in en_policy
    assert "verbatim" in en_policy
