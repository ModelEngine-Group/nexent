from backend.utils.memory_tool_prompt import should_enable_memory_tool_policy


def test_policy_is_empty_without_store_memory():
    assert not should_enable_memory_tool_policy(["web_search"])
    assert not should_enable_memory_tool_policy(["search_memory"])


def test_ut_be_fps_013_store_memory_enables_policy():
    assert should_enable_memory_tool_policy(["search_memory", "store_memory"])


def test_memory_policy_is_independent_of_other_tool_names():
    assert should_enable_memory_tool_policy(["store_memory", "web_search"])
