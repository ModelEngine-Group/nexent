from backend.utils.memory_tool_prompt import build_memory_tool_policy


def test_policy_is_empty_without_store_memory():
    assert build_memory_tool_policy("en", ["web_search"]) == ""
    assert build_memory_tool_policy("en", ["search_memory"]) == ""


def test_chinese_policy_only_describes_store_memory():
    policy = build_memory_tool_policy(
        "zh",
        ["search_memory", "store_memory"],
    )

    assert "`search_memory`" not in policy
    assert "`store_memory`" in policy
    assert "用户偏好" in policy
    assert "任务目标" in policy
    assert "行动计划与最新进展" in policy
    assert "用户反馈或报错信息" in policy
    assert "中间行动步骤" in policy
    assert "生成最终回答时不要调用" in policy
    assert "固定检索历史记忆" in policy
    assert "不得再次调用 `store_memory`" in policy


def test_english_policy_excludes_search_and_requires_deduplication():
    policy = build_memory_tool_policy(
        "en",
        ["search_memory", "store_memory"],
    )

    assert "`search_memory`" not in policy
    assert "`content`" in policy
    assert "intermediate action steps" in policy
    assert "Do NOT call `store_memory` when generating the final answer" in policy
    assert "fixed memory retrieval" in policy
    assert "Do not call `store_memory`" in policy
    assert "nullable" not in policy
