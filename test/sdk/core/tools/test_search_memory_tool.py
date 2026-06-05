import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from sdk.nexent.core.utils.observer import MessageObserver, ProcessType
from sdk.nexent.core.tools.search_memory_tool import SearchMemoryTool


@pytest.fixture
def mock_observer():
    observer = MagicMock(spec=MessageObserver)
    observer.lang = "en"
    return observer


@pytest.fixture
def mock_user_config():
    config = MagicMock()
    config.agent_share_option = "always"
    config.disable_agent_ids = []
    config.disable_user_agent_ids = []
    return config


@pytest.fixture
def search_memory_tool(mock_observer, mock_user_config):
    return SearchMemoryTool(
        memory_config={"test": "config"},
        tenant_id="tenant_1",
        user_id="user_1",
        agent_id="agent_1",
        memory_user_config=mock_user_config,
        observer=mock_observer,
    )


def test_observer_english_message(search_memory_tool, mock_observer):
    mock_observer.lang = "en"
    with patch(
        "sdk.nexent.memory.memory_service.search_memory_in_levels",
        new_callable=AsyncMock,
        return_value={"results": []},
    ):
        search_memory_tool.forward("some query")

    mock_observer.add_message.assert_any_call("", ProcessType.TOOL, "Searching memory...")


def test_observer_chinese_message(search_memory_tool, mock_observer):
    mock_observer.lang = "zh"
    with patch(
        "sdk.nexent.memory.memory_service.search_memory_in_levels",
        new_callable=AsyncMock,
        return_value={"results": []},
    ):
        search_memory_tool.forward("some query")

    mock_observer.add_message.assert_any_call("", ProcessType.TOOL, "搜索记忆中...")


def test_no_observer(search_memory_tool):
    search_memory_tool.observer = None
    with patch(
        "sdk.nexent.memory.memory_service.search_memory_in_levels",
        new_callable=AsyncMock,
        return_value={"results": [{"memory": "fact", "score": 0.9, "memory_level": "user"}]},
    ):
        result = search_memory_tool.forward("some query")

    assert "Found 1 relevant memories" in result


def test_forward_with_results(search_memory_tool):
    with patch(
        "sdk.nexent.memory.memory_service.search_memory_in_levels",
        new_callable=AsyncMock,
        return_value={
            "results": [
                {"memory": "User prefers dark mode", "score": 0.92, "memory_level": "user_agent"},
                {"memory": "User timezone is UTC+8", "score": 0.85, "memory_level": "user"},
                {"memory": "Agent should confirm before executing", "score": 0.71, "memory_level": "agent"},
            ]
        },
    ) as mock_search:
        result = search_memory_tool.forward("user preferences", top_k=3)

    assert "Found 3 relevant memories" in result
    assert "(score: 0.92, level: user_agent) User prefers dark mode" in result
    assert "(score: 0.85, level: user) User timezone is UTC+8" in result
    assert "(score: 0.71, level: agent) Agent should confirm before executing" in result

    mock_search.assert_called_once_with(
        query_text="user preferences",
        memory_config={"test": "config"},
        tenant_id="tenant_1",
        user_id="user_1",
        agent_id="agent_1",
        top_k=3,
        memory_levels=["tenant", "user", "agent", "user_agent"],
    )


def test_forward_no_results(search_memory_tool):
    with patch(
        "sdk.nexent.memory.memory_service.search_memory_in_levels",
        new_callable=AsyncMock,
        return_value={"results": []},
    ):
        result = search_memory_tool.forward("nonexistent topic")

    assert result == "No relevant memories found."


def test_forward_default_top_k(search_memory_tool):
    with patch(
        "sdk.nexent.memory.memory_service.search_memory_in_levels",
        new_callable=AsyncMock,
        return_value={"results": []},
    ) as mock_search:
        search_memory_tool.forward("some query")

    call_kwargs = mock_search.call_args[1]
    assert call_kwargs["top_k"] == 5


def test_forward_custom_top_k(search_memory_tool):
    with patch(
        "sdk.nexent.memory.memory_service.search_memory_in_levels",
        new_callable=AsyncMock,
        return_value={"results": []},
    ) as mock_search:
        search_memory_tool.forward("some query", top_k=10)

    call_kwargs = mock_search.call_args[1]
    assert call_kwargs["top_k"] == 10


def test_forward_uses_content_field_fallback(search_memory_tool):
    with patch(
        "sdk.nexent.memory.memory_service.search_memory_in_levels",
        new_callable=AsyncMock,
        return_value={
            "results": [
                {"content": "Fallback content field", "score": 0.8, "memory_level": "user"},
            ]
        },
    ):
        result = search_memory_tool.forward("query")

    assert "Fallback content field" in result


def test_levels_agent_share_never(search_memory_tool, mock_user_config):
    mock_user_config.agent_share_option = "never"

    with patch(
        "sdk.nexent.memory.memory_service.search_memory_in_levels",
        new_callable=AsyncMock,
        return_value={"results": []},
    ) as mock_search:
        search_memory_tool.forward("query")

    call_kwargs = mock_search.call_args[1]
    assert "agent" not in call_kwargs["memory_levels"]
    assert "tenant" in call_kwargs["memory_levels"]
    assert "user" in call_kwargs["memory_levels"]
    assert "user_agent" in call_kwargs["memory_levels"]


def test_levels_disable_agent_ids(search_memory_tool, mock_user_config):
    mock_user_config.disable_agent_ids = ["agent_1"]

    with patch(
        "sdk.nexent.memory.memory_service.search_memory_in_levels",
        new_callable=AsyncMock,
        return_value={"results": []},
    ) as mock_search:
        search_memory_tool.forward("query")

    call_kwargs = mock_search.call_args[1]
    assert "agent" not in call_kwargs["memory_levels"]
    assert "tenant" in call_kwargs["memory_levels"]


def test_levels_disable_user_agent_ids(search_memory_tool, mock_user_config):
    mock_user_config.disable_user_agent_ids = ["agent_1"]

    with patch(
        "sdk.nexent.memory.memory_service.search_memory_in_levels",
        new_callable=AsyncMock,
        return_value={"results": []},
    ) as mock_search:
        search_memory_tool.forward("query")

    call_kwargs = mock_search.call_args[1]
    assert "user_agent" not in call_kwargs["memory_levels"]
    assert "agent" in call_kwargs["memory_levels"]


def test_forward_exception_returns_friendly_error(search_memory_tool):
    with patch(
        "sdk.nexent.memory.memory_service.search_memory_in_levels",
        new_callable=AsyncMock,
        side_effect=Exception("Elasticsearch timeout"),
    ):
        result = search_memory_tool.forward("query")

    assert "Memory search failed" in result
    assert "Elasticsearch timeout" in result
    assert "Continuing without memory results" in result
