import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from sdk.nexent.core.utils.observer import MessageObserver
from sdk.nexent.core.tools.store_memory_tool import StoreMemoryTool, _run_coroutine


@pytest.fixture
def mock_observer():
    observer = MagicMock()
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
def store_memory_tool(mock_observer, mock_user_config):
    return StoreMemoryTool(
        memory_config={"test": "config"},
        tenant_id="tenant_1",
        user_id="user_1",
        agent_id="agent_1",
        memory_user_config=mock_user_config,
        observer=mock_observer,
    )


def test_no_observer(store_memory_tool):
    store_memory_tool.observer = None
    with patch(
        "sdk.nexent.memory.memory_service.add_memory_in_levels",
        new_callable=AsyncMock,
        return_value={"results": [{"event": "ADD", "memory": "fact"}]},
    ):
        result = store_memory_tool.forward("some content")

    assert "Stored successfully" in result


def test_forward_add_event(store_memory_tool):
    with patch(
        "sdk.nexent.memory.memory_service.add_memory_in_levels",
        new_callable=AsyncMock,
        return_value={
            "results": [
                {"event": "ADD", "memory": "User prefers dark mode"},
                {"event": "ADD", "memory": "User works on Project X"},
            ]
        },
    ) as mock_add:
        result = store_memory_tool.forward("I prefer dark mode and work on Project X")

    assert "Stored successfully" in result
    assert "[ADD] User prefers dark mode" in result
    assert "[ADD] User works on Project X" in result
    assert store_memory_tool.store_count == 1

    mock_add.assert_called_once_with(
        messages=[{"role": "user", "content": "I prefer dark mode and work on Project X"}],
        memory_config={"test": "config"},
        tenant_id="tenant_1",
        user_id="user_1",
        agent_id="agent_1",
        memory_levels=["user_agent", "agent"],
    )


def test_forward_update_event(store_memory_tool):
    with patch(
        "sdk.nexent.memory.memory_service.add_memory_in_levels",
        new_callable=AsyncMock,
        return_value={
            "results": [
                {"event": "UPDATE", "memory": "User prefers dark mode and high contrast"},
            ]
        },
    ):
        result = store_memory_tool.forward("I also like high contrast")

    assert "Stored successfully" in result
    assert "[UPDATE] User prefers dark mode and high contrast" in result


def test_forward_mixed_events(store_memory_tool):
    with patch(
        "sdk.nexent.memory.memory_service.add_memory_in_levels",
        new_callable=AsyncMock,
        return_value={
            "results": [
                {"event": "ADD", "memory": "New fact"},
                {"event": "NONE", "memory": "Existing fact"},
                {"event": "DELETE", "memory": "Old fact"},
                {"event": "UPDATE", "memory": "Updated fact"},
            ]
        },
    ):
        result = store_memory_tool.forward("some content")

    assert "[ADD] New fact" in result
    assert "[UPDATE] Updated fact" in result
    assert "NONE" not in result
    assert "DELETE" not in result


def test_forward_no_results(store_memory_tool):
    with patch(
        "sdk.nexent.memory.memory_service.add_memory_in_levels",
        new_callable=AsyncMock,
        return_value={"results": []},
    ):
        result = store_memory_tool.forward("just a greeting")

    assert result == "No new facts were extracted from the content."


def test_forward_all_none_events(store_memory_tool):
    with patch(
        "sdk.nexent.memory.memory_service.add_memory_in_levels",
        new_callable=AsyncMock,
        return_value={
            "results": [
                {"event": "NONE", "memory": "Already known fact"},
            ]
        },
    ):
        result = store_memory_tool.forward("already known info")

    assert result == "The information was already present in memory (no changes needed)."


def test_cost_guard_limit_reached(store_memory_tool):
    store_memory_tool.store_count = 3

    result = store_memory_tool.forward("some content")

    assert "Memory storage limit reached" in result


def test_cost_guard_increments_counter(store_memory_tool):
    with patch(
        "sdk.nexent.memory.memory_service.add_memory_in_levels",
        new_callable=AsyncMock,
        return_value={"results": [{"event": "ADD", "memory": "fact"}]},
    ):
        store_memory_tool.forward("content 1")
        store_memory_tool.forward("content 2")

    assert store_memory_tool.store_count == 2


def test_cost_guard_increments_even_with_no_facts(store_memory_tool):
    with patch(
        "sdk.nexent.memory.memory_service.add_memory_in_levels",
        new_callable=AsyncMock,
        return_value={"results": []},
    ):
        store_memory_tool.forward("nothing useful")

    # store_count increments after asyncio.run succeeds, regardless of results
    assert store_memory_tool.store_count == 1


def test_levels_agent_share_never(store_memory_tool, mock_user_config):
    mock_user_config.agent_share_option = "never"

    with patch(
        "sdk.nexent.memory.memory_service.add_memory_in_levels",
        new_callable=AsyncMock,
        return_value={"results": [{"event": "ADD", "memory": "fact"}]},
    ) as mock_add:
        store_memory_tool.forward("some content")

    call_kwargs = mock_add.call_args[1]
    assert call_kwargs["memory_levels"] == ["user_agent"]
    assert "agent" not in call_kwargs["memory_levels"]


def test_levels_agent_share_always(store_memory_tool, mock_user_config):
    mock_user_config.agent_share_option = "always"

    with patch(
        "sdk.nexent.memory.memory_service.add_memory_in_levels",
        new_callable=AsyncMock,
        return_value={"results": [{"event": "ADD", "memory": "fact"}]},
    ) as mock_add:
        store_memory_tool.forward("some content")

    call_kwargs = mock_add.call_args[1]
    assert "user_agent" in call_kwargs["memory_levels"]
    assert "agent" in call_kwargs["memory_levels"]


def test_levels_disable_agent_ids(store_memory_tool, mock_user_config):
    mock_user_config.disable_agent_ids = ["agent_1"]

    with patch(
        "sdk.nexent.memory.memory_service.add_memory_in_levels",
        new_callable=AsyncMock,
        return_value={"results": [{"event": "ADD", "memory": "fact"}]},
    ) as mock_add:
        store_memory_tool.forward("some content")

    call_kwargs = mock_add.call_args[1]
    assert "agent" not in call_kwargs["memory_levels"]
    assert "user_agent" in call_kwargs["memory_levels"]


def test_levels_disable_user_agent_ids(store_memory_tool, mock_user_config):
    mock_user_config.disable_user_agent_ids = ["agent_1"]

    with patch(
        "sdk.nexent.memory.memory_service.add_memory_in_levels",
        new_callable=AsyncMock,
        return_value={"results": [{"event": "ADD", "memory": "fact"}]},
    ) as mock_add:
        store_memory_tool.forward("some content")

    call_kwargs = mock_add.call_args[1]
    assert "user_agent" not in call_kwargs["memory_levels"]
    assert "agent" in call_kwargs["memory_levels"]


def test_levels_all_disabled(store_memory_tool, mock_user_config):
    mock_user_config.disable_agent_ids = ["agent_1"]
    mock_user_config.disable_user_agent_ids = ["agent_1"]

    result = store_memory_tool.forward("some content")

    assert result == "No memory levels available (all disabled by user preferences)."


def test_forward_exception_returns_friendly_error(store_memory_tool):
    with patch(
        "sdk.nexent.memory.memory_service.add_memory_in_levels",
        new_callable=AsyncMock,
        side_effect=Exception("Elasticsearch connection refused"),
    ):
        result = store_memory_tool.forward("some content")

    assert "Failed to store memory" in result
    assert "Elasticsearch connection refused" in result
    assert "Continuing without saving" in result


def test_forward_exception_does_not_increment_counter(store_memory_tool):
    with patch(
        "sdk.nexent.memory.memory_service.add_memory_in_levels",
        new_callable=AsyncMock,
        side_effect=Exception("connection error"),
    ):
        store_memory_tool.forward("some content")

    assert store_memory_tool.store_count == 0


def test_levels_none_config_conservative_default(mock_observer):
    """When memory_user_config is None, apply conservative default (no agent-level sharing)."""
    tool = StoreMemoryTool(
        memory_config={"test": "config"},
        tenant_id="tenant_1",
        user_id="user_1",
        agent_id="agent_1",
        memory_user_config=None,
        observer=mock_observer,
    )

    with patch(
        "sdk.nexent.memory.memory_service.add_memory_in_levels",
        new_callable=AsyncMock,
        return_value={"results": [{"event": "ADD", "memory": "fact"}]},
    ) as mock_add:
        tool.forward("some content")

    call_kwargs = mock_add.call_args[1]
    assert call_kwargs["memory_levels"] == ["user_agent"]
    assert "agent" not in call_kwargs["memory_levels"]


def test_run_coroutine_no_running_loop():
    async def sample_coro():
        return "result"

    result = _run_coroutine(sample_coro())
    assert result == "result"


def test_run_coroutine_with_running_loop():
    async def sample_coro():
        return "result"

    async def run_with_loop():
        return _run_coroutine(sample_coro())

    import asyncio
    result = asyncio.run(run_with_loop())
    assert result == "result"
