import pytest
import importlib
from types import ModuleType
from unittest.mock import MagicMock, patch
from threading import Event

# ---------------------------------------------------------------------------
# Prepare mocks for external dependencies that are not required for this test
# ---------------------------------------------------------------------------

# Create a real module object for smolagents so that submodule imports (e.g. smolagents.agents)
# succeed during the import machinery that expects the parent module to be a *package*.
mock_smolagents = ModuleType("smolagents")
mock_smolagents.__dict__.update({})  # ensure we can set attrs dynamically
# Mark as package so that importlib can load submodules like smolagents.agents
mock_smolagents.__path__ = []

# Mock Tool and smolagents.tools sub-module
mock_smolagents_tool_cls = MagicMock(name="Tool")
mock_smolagents_tools_mod = ModuleType("smolagents.tools")
mock_smolagents_tools_mod.Tool = mock_smolagents_tool_cls

# Attach tools sub-module to the parent module and to sys.modules via module_mocks later
setattr(mock_smolagents, "tools", mock_smolagents_tools_mod)

# Provide a dummy ToolCollection with a classmethod from_mcp that works as a
# context manager. The context manager returns the ToolCollection instance
# itself on __enter__ so it can be inspected from tests.
class _MockToolCollection(MagicMock):
    @classmethod
    def from_mcp(cls, *args, **kwargs):  # pylint: disable=unused-argument
        instance = cls()
        # Make the instance a context manager
        instance.__enter__ = MagicMock(return_value=instance)
        instance.__exit__ = MagicMock(return_value=None)
        return instance

setattr(mock_smolagents, "ToolCollection", _MockToolCollection)

# Create dummy smolagents sub-modules to satisfy indirect imports
for _sub in [
    "agents",
    "memory",
    "models",
    "monitoring",
    "utils",
    "local_python_executor",
]:
    sub_mod = ModuleType(f"smolagents.{_sub}")
    # Populate required attributes with MagicMocks to satisfy import-time `from smolagents.<sub> import ...`.
    if _sub == "agents":
        for _name in ["CodeAgent", "populate_template", "handle_agent_output_types", "AgentError", "AgentType"]:
            setattr(sub_mod, _name, MagicMock(name=f"smolagents.agents.{_name}"))
    elif _sub == "local_python_executor":
        setattr(sub_mod, "fix_final_answer_code", MagicMock(name="fix_final_answer_code"))
    elif _sub == "memory":
        for _name in ["ActionStep", "ToolCall", "TaskStep", "SystemPromptStep", "PlanningStep", "FinalAnswerStep"]:
            setattr(sub_mod, _name, MagicMock(name=f"smolagents.memory.{_name}"))
    elif _sub == "models":
        setattr(sub_mod, "ChatMessage", MagicMock(name="smolagents.models.ChatMessage"))
        setattr(sub_mod, "MessageRole", MagicMock(name="smolagents.models.MessageRole"))
        # Provide a simple base class so that OpenAIModel can inherit from it
        class _DummyOpenAIServerModel:
            def __init__(self, *args, **kwargs):
                pass

        setattr(sub_mod, "OpenAIServerModel", _DummyOpenAIServerModel)
    elif _sub == "monitoring":
        setattr(sub_mod, "LogLevel", MagicMock(name="smolagents.monitoring.LogLevel"))
    elif _sub == "utils":
        for _name in [
            "AgentExecutionError",
            "AgentGenerationError",
            "AgentParsingError",
            "parse_code_blobs",
            "truncate_content",
        ]:
            setattr(sub_mod, _name, MagicMock(name=f"smolagents.utils.{_name}"))
    setattr(mock_smolagents, _sub, sub_mod)
    # Will be added to module_mocks below

# Top-level exports expected directly from `smolagents` by nexent_agent.py
for _name in ["ActionStep", "TaskStep", "AgentText", "handle_agent_output_types"]:
    setattr(mock_smolagents, _name, MagicMock(name=f"smolagents.{_name}"))
# Also export Tool at top-level so that `from smolagents import Tool` works
setattr(mock_smolagents, "Tool", mock_smolagents_tool_cls)

# Mock langchain_core.tools.BaseTool
mock_langchain_core_tools_mod = MagicMock(name="langchain_core.tools")
mock_langchain_core_tools_mod.BaseTool = MagicMock(name="BaseTool")
mock_langchain_core_mod = MagicMock(name="langchain_core")
mock_langchain_core_mod.tools = mock_langchain_core_tools_mod

# Re-use mocks from test_nexent_agent for langchain and openai to avoid real imports
mock_langchain_tools = MagicMock()
mock_langchain_tools.StructuredTool = MagicMock()
mock_langchain = MagicMock()
mock_langchain.tools = mock_langchain_tools

mock_openai_chat_completion_message = MagicMock()

# Mock memory_service to avoid importing mem0
mock_memory_service = MagicMock()
mock_memory_service.add_memory_in_levels = MagicMock()

module_mocks = {
    "smolagents": mock_smolagents,
    "smolagents.tools": mock_smolagents_tools_mod,
    "smolagents.ToolCollection": _MockToolCollection,
    # Add smolagents sub-modules created above to ensure importability
    **{f"smolagents.{_sub}": getattr(mock_smolagents, _sub) for _sub in [
        "agents",
        "memory",
        "models",
        "monitoring",
        "utils",
        "local_python_executor",
    ]},
    "langchain_core": mock_langchain_core_mod,
    "langchain_core.tools": mock_langchain_core_tools_mod,
    "langchain": mock_langchain,
    "langchain.tools": mock_langchain_tools,
    # Minimal openai mock needed by other modules
    "openai": MagicMock(),
    "openai.types": MagicMock(),
    "openai.types.chat": MagicMock(),
    "openai.types.chat.chat_completion_message": MagicMock(ChatCompletionMessage=mock_openai_chat_completion_message),
    "openai.types.chat.chat_completion_message_param": MagicMock(),
    # exa_py is imported by sdk.nexent.core.tools – provide dummy to skip real import
    "exa_py": MagicMock(Exa=MagicMock()),
    # Mock memory_service to avoid importing mem0
    "sdk.nexent.memory.memory_service": mock_memory_service,
}

# ---------------------------------------------------------------------------
# Import modules under test with patched dependencies in place
# ---------------------------------------------------------------------------
with patch.dict("sys.modules", module_mocks):
    from sdk.nexent.core.utils.observer import MessageObserver, ProcessType  # noqa: E402
    from sdk.nexent.core.agents.agent_model import (
        AgentRunInfo,
        ModelConfig,
        AgentConfig,
        ToolConfig,
    )  # noqa: E402
    import sdk.nexent.core.agents.run_agent as run_agent  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_observer():
    """Return a mocked MessageObserver instance."""
    observer = MagicMock(spec=MessageObserver)
    observer.lang = "en"
    return observer


@pytest.fixture
def mock_memory_context():
    """Return a mocked MemoryContext instance for tests."""
    mock_user_config = MagicMock()
    mock_user_config.memory_switch = False  # Disable memory by default for tests
    mock_user_config.agent_share_option = "always"
    mock_user_config.disable_agent_ids = []
    mock_user_config.disable_user_agent_ids = []
    
    mock_memory_context = MagicMock()
    mock_memory_context.user_config = mock_user_config
    mock_memory_context.memory_config = {}
    mock_memory_context.tenant_id = "test_tenant"
    mock_memory_context.user_id = "test_user"
    mock_memory_context.agent_id = "test_agent"
    
    return mock_memory_context


@pytest.fixture
def basic_agent_run_info(mock_observer):
    """Return a minimal AgentRunInfo instance for tests (without MCP host)."""
    model_cfg = ModelConfig(
        cite_name="test_model",
        api_key="",
        model_name="model",
        url="http://example.com",
        temperature=0.1,
        top_p=0.95,
    )

    agent_cfg = AgentConfig(
        name="agent",
        description="desc",
        prompt_templates={},
        tools=[],
        model_name="test_model",
    )

    return AgentRunInfo(
        query="hello",
        model_config_list=[model_cfg],
        observer=mock_observer,
        agent_config=agent_cfg,
        stop_event=Event(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_agent_run_thread_local_flow(basic_agent_run_info, mock_memory_context, monkeypatch):
    """Verify local execution path when mcp_host is empty or None."""
    # Patch NexentAgent inside run_agent to a MagicMock instance
    mock_nexent_instance = MagicMock(name="NexentAgentInstance")
    monkeypatch.setattr(run_agent, "NexentAgent", MagicMock(return_value=mock_nexent_instance))

    # Call the function under test
    run_agent.agent_run_thread(basic_agent_run_info, mock_memory_context)

    # NexentAgent should be instantiated with observer, model_config_list, stop_event
    run_agent.NexentAgent.assert_called_once_with(
        observer=basic_agent_run_info.observer,
        model_config_list=basic_agent_run_info.model_config_list,
        stop_event=basic_agent_run_info.stop_event,
    )

    # Following methods on the NexentAgent instance should be invoked
    mock_nexent_instance.create_single_agent.assert_called_once_with(basic_agent_run_info.agent_config)
    mock_nexent_instance.set_agent.assert_called_once()
    mock_nexent_instance.add_history_to_agent.assert_called_once_with(basic_agent_run_info.history)
    mock_nexent_instance.agent_run_with_observer.assert_called_once_with(query=basic_agent_run_info.query, reset=False)

    # Ensure no MCP-specific behaviour occurred
    basic_agent_run_info.observer.add_message.assert_not_called()


def test_agent_run_thread_mcp_flow(basic_agent_run_info, mock_memory_context, monkeypatch):
    """Verify behaviour when an MCP host list is provided."""
    # Give the AgentRunInfo an MCP host list
    basic_agent_run_info.mcp_host = ["http://mcp.server"]

    # Prepare ToolCollection.from_mcp to return a context manager
    mock_tool_collection = MagicMock(name="ToolCollectionInstance")
    mock_context_manager = MagicMock(__enter__=MagicMock(return_value=mock_tool_collection), __exit__=MagicMock(return_value=None))
    monkeypatch.setattr(run_agent.ToolCollection, "from_mcp", MagicMock(return_value=mock_context_manager))

    # Patch NexentAgent
    mock_nexent_instance = MagicMock(name="NexentAgentInstance")
    monkeypatch.setattr(run_agent, "NexentAgent", MagicMock(return_value=mock_nexent_instance))

    # Execute
    run_agent.agent_run_thread(basic_agent_run_info, mock_memory_context)

    # Observer should receive <MCP_START> signal
    basic_agent_run_info.observer.add_message.assert_any_call("", ProcessType.AGENT_NEW_RUN, "<MCP_START>")

    # ToolCollection.from_mcp should be called with the expected client list and trust_remote_code=True
    expected_client_list = [{"url": "http://mcp.server"}]
    run_agent.ToolCollection.from_mcp.assert_called_once_with(expected_client_list, trust_remote_code=True)

    # NexentAgent should be instantiated with mcp_tool_collection
    run_agent.NexentAgent.assert_called_once_with(
        observer=basic_agent_run_info.observer,
        model_config_list=basic_agent_run_info.model_config_list,
        stop_event=basic_agent_run_info.stop_event,
        mcp_tool_collection=mock_tool_collection,
    )

    # Subsequent calls on NexentAgent instance should mirror the local flow
    mock_nexent_instance.create_single_agent.assert_called_once_with(basic_agent_run_info.agent_config)
    mock_nexent_instance.set_agent.assert_called_once()
    mock_nexent_instance.add_history_to_agent.assert_called_once_with(basic_agent_run_info.history)
    mock_nexent_instance.agent_run_with_observer.assert_called_once_with(query=basic_agent_run_info.query, reset=False)


def test_agent_run_thread_invalid_type():
    """Passing a non-AgentRunInfo instance should raise a TypeError."""
    mock_memory_context = MagicMock()
    with pytest.raises(TypeError):
        run_agent.agent_run_thread("not_an_agent_run_info", mock_memory_context)


def test_agent_run_thread_handles_internal_exception(basic_agent_run_info, mock_memory_context, monkeypatch):
    """If an internal error occurs, the observer should be notified and a ValueError propagated."""
    # Configure NexentAgent.create_single_agent to raise an exception
    failing_nexent_instance = MagicMock(name="NexentAgentInstance")
    failing_nexent_instance.create_single_agent.side_effect = Exception("Boom")

    monkeypatch.setattr(run_agent, "NexentAgent", MagicMock(return_value=failing_nexent_instance))

    # Execute and expect ValueError
    with pytest.raises(ValueError) as exc_info:
        run_agent.agent_run_thread(basic_agent_run_info, mock_memory_context)

    # Observer should have been informed of the failure via FINAL_ANSWER
    basic_agent_run_info.observer.add_message.assert_called_with("", ProcessType.FINAL_ANSWER, "Run Agent Error: Boom")

    # Ensure the raised error contains our message to confirm correct propagation
    assert "Error in agent_run_thread: Boom" in str(exc_info.value)
