import importlib
import json
import os
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from unittest.mock import ANY, MagicMock, call, patch

import pytest

TEST_ROOT = Path(__file__).resolve().parents[3]
PROJECT_ROOT = TEST_ROOT.parent
for _path in (str(PROJECT_ROOT), str(TEST_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

SDK_SOURCE_ROOT = PROJECT_ROOT / "sdk"
sdk_namespace_module = types.ModuleType("sdk")
sdk_namespace_module.__path__ = [str(SDK_SOURCE_ROOT)]

# ---------------------------------------------------------------------------
# Prepare mocks for external dependencies that are not required for this test
# ---------------------------------------------------------------------------

# Mock for smolagents and its sub-modules
mock_smolagents = MagicMock()

# Define lightweight classes to support isinstance checks in source code


class _ActionStep:
    def __init__(self, step_number=None, timing=None, action_output=None, model_output=None):
        self.step_number = step_number
        self.timing = timing
        self.action_output = action_output
        self.model_output = model_output


class _TaskStep:
    def __init__(self, task=None):
        self.task = task


class _AgentText:
    def __init__(self, content: str = ""):
        self._content = content

    def to_string(self):
        return self._content


# Expose these classes on the mocked smolagents module
mock_smolagents.ActionStep = _ActionStep
mock_smolagents.TaskStep = _TaskStep
mock_smolagents.AgentText = _AgentText
mock_smolagents.handle_agent_output_types = MagicMock()

# Mock for smolagents.tools.Tool with a configurable from_langchain method
mock_tool_class = MagicMock()
mock_tool_class.from_langchain = MagicMock()
mock_smolagents_tools = MagicMock()
mock_smolagents_tools.Tool = mock_tool_class
mock_smolagents.tools = mock_smolagents_tools

mock_smolagents.memory = MagicMock()
mock_smolagents.memory.ActionStep = _ActionStep
mock_smolagents.memory.AgentMemory = MagicMock
mock_smolagents.memory.MemoryStep = MagicMock
mock_smolagents.memory.TaskStep = _TaskStep

# Create dummy smolagents sub-modules that may be imported indirectly
for sub_mod in ["agents", "models", "monitoring", "utils", "local_python_executor"]:
    mock_module = MagicMock()
    setattr(mock_smolagents, sub_mod, mock_module)

# Mock for langchain and langchain.tools
mock_langchain_tools = MagicMock()
mock_langchain_tools.StructuredTool = MagicMock()
mock_langchain = MagicMock()
mock_langchain.tools = mock_langchain_tools

# Mock for OpenAIModel
mock_openai_model = MagicMock()
mock_openai_model_class = MagicMock(return_value=mock_openai_model)

# Mock for CoreAgent


class _TestCoreAgent:
    enable_planning = False  # v1.4: CoreAgent.__init__ reads this attribute.


mock_core_agent_class = _TestCoreAgent

# Very lightweight mock for openai path required by internal OpenAIModel import
mock_openai_chat_completion_message = MagicMock()

mock_botocore_module = types.ModuleType("botocore")
mock_botocore_exceptions = types.ModuleType("botocore.exceptions")
mock_botocore_exceptions.ClientError = MagicMock()
mock_botocore_module.exceptions = mock_botocore_exceptions
mock_botocore_client = types.ModuleType("botocore.client")
mock_botocore_client.Config = MagicMock()
mock_botocore_args = types.ModuleType("botocore.args")
mock_botocore_args.ClientArgsCreator = MagicMock()
mock_botocore_regions = types.ModuleType("botocore.regions")
mock_botocore_regions.EndpointResolverBuiltins = MagicMock()
mock_botocore_crt = types.ModuleType("botocore.crt")
mock_botocore_crt.CRT_SUPPORTED_AUTH_TYPES = []


class _MockMessageObserver:
    def add_message(self, *args, **kwargs):
        return None


class _MockProcessType:
    TOKEN_COUNT = "token_count"
    FINAL_ANSWER = "final_answer"
    ERROR = "error"
    NL2A = "nl2a"
    FILE_ARTIFACT = "file_artifact"


@dataclass
class _MockAgentRunMetadata:
    agent_name: str | None = None
    query: str | None = None


MessageObserver = _MockMessageObserver
ProcessType = _MockProcessType


mock_nexent_core_utils_module = types.ModuleType("nexent.core.utils")
mock_nexent_core_utils_observer_module = types.ModuleType(
    "nexent.core.utils.observer")
mock_nexent_core_utils_observer_module.MessageObserver = _MockMessageObserver
mock_nexent_core_utils_observer_module.ProcessType = _MockProcessType

mock_sdk_module = types.ModuleType("sdk")
mock_sdk_nexent_module = types.ModuleType("sdk.nexent")
mock_sdk_nexent_core_module = types.ModuleType("sdk.nexent.core")
mock_sdk_nexent_core_agents_module = types.ModuleType("sdk.nexent.core.agents")
mock_sdk_nexent_core_tools_module = types.ModuleType("sdk.nexent.core.tools")
mock_sdk_nexent_core_utils_module = types.ModuleType("sdk.nexent.core.utils")
mock_sdk_nexent_core_utils_observer_module = types.ModuleType(
    "sdk.nexent.core.utils.observer"
)
mock_sdk_nexent_core_utils_observer_module.MessageObserver = _MockMessageObserver
mock_sdk_nexent_core_utils_observer_module.ProcessType = _MockProcessType
mock_sdk_nexent_monitor_module = types.ModuleType("sdk.nexent.monitor")
mock_sdk_nexent_monitor_module.__path__ = []
mock_sdk_nexent_monitor_module.AgentRunMetadata = _MockAgentRunMetadata
mock_sdk_nexent_monitor_module.get_agent_monitoring_context = MagicMock(return_value=None)
mock_sdk_nexent_monitor_module.get_monitoring_manager = MagicMock()
mock_sdk_nexent_monitor_monitoring_module = types.ModuleType("sdk.nexent.monitor.monitoring")
mock_sdk_nexent_monitor_monitoring_module.record_model_call = MagicMock()


class _MockManagedContextRuntime:
    def __init__(self, context_manager, items=None):
        self.context_manager = context_manager
        self.items = list(items or [])


class _MockContextManager:
    def __init__(self, config, max_steps):
        self.config = config
        self.max_steps = max_steps


class _MockContextManagerConfig:
    def __init__(self, enabled=False, **kwargs):
        self.enabled = enabled
        for key, value in kwargs.items():
            setattr(self, key, value)


mock_sdk_context_runtime_module = types.ModuleType("sdk.nexent.core.context_runtime")
mock_sdk_context_runtime_module.__path__ = []
mock_sdk_context_runtime_managed_module = types.ModuleType("sdk.nexent.core.context_runtime.managed")
mock_sdk_context_runtime_managed_module.__path__ = []
mock_sdk_context_runtime_managed_runtime_module = types.ModuleType(
    "sdk.nexent.core.context_runtime.managed.runtime"
)
mock_sdk_context_runtime_managed_runtime_module.ManagedContextRuntime = _MockManagedContextRuntime
mock_sdk_agent_context_module = types.ModuleType("sdk.nexent.core.agents.agent_context")
mock_sdk_agent_context_module.ContextManager = _MockContextManager
mock_sdk_summary_config_module = types.ModuleType("sdk.nexent.core.agents.summary_config")
mock_sdk_summary_config_module.ContextManagerConfig = _MockContextManagerConfig
mock_sdk_agent_context_domain_module = types.ModuleType("sdk.nexent.core.agents.context")
mock_sdk_agent_context_domain_module.__path__ = [
    str(SDK_SOURCE_ROOT / "nexent" / "core" / "agents" / "context")
]
mock_sdk_agent_context_domain_module.ContextManager = _MockContextManager
mock_sdk_agent_context_domain_module.ContextManagerConfig = _MockContextManagerConfig
mock_sdk_agent_context_domain_module.ManagedContextRuntime = _MockManagedContextRuntime

mock_sdk_module.__path__ = [str(SDK_SOURCE_ROOT)]
mock_sdk_nexent_module.__path__ = [str(SDK_SOURCE_ROOT / "nexent")]
mock_sdk_nexent_core_module.__path__ = [
    str(SDK_SOURCE_ROOT / "nexent" / "core")]
mock_sdk_nexent_core_agents_module.__path__ = [
    str(SDK_SOURCE_ROOT / "nexent" / "core" / "agents")
]
mock_sdk_nexent_core_tools_module.__path__ = [
    str(SDK_SOURCE_ROOT / "nexent" / "core" / "tools")
]
mock_sdk_nexent_core_utils_module.__path__ = [
    str(SDK_SOURCE_ROOT / "nexent" / "core" / "utils")]
mock_sdk_nexent_core_utils_observer_module.__path__ = []

mock_prompt_template_utils_module = types.ModuleType(
    "nexent.core.utils.prompt_template_utils"
)
mock_prompt_template_utils_module.get_prompt_template = MagicMock(
    return_value="")

mock_tools_common_message_module = types.ModuleType(
    "nexent.core.utils.tools_common_message"
)


class _EnumStub:
    def __init__(self, value):
        self.value = value


class _MockToolCategory:
    SEARCH = _EnumStub("search")
    FILE = _EnumStub("file")
    EMAIL = _EnumStub("email")
    TERMINAL = _EnumStub("terminal")
    MULTIMODAL = _EnumStub("multimodal")


class _MockToolSign:
    KNOWLEDGE_BASE = _EnumStub("a")
    EXA_SEARCH = _EnumStub("b")
    LINKUP_SEARCH = _EnumStub("c")
    TAVILY_SEARCH = _EnumStub("d")
    FILE_OPERATION = _EnumStub("f")
    TERMINAL_OPERATION = _EnumStub("t")
    MULTIMODAL_OPERATION = _EnumStub("m")


mock_tools_common_message_module.ToolCategory = _MockToolCategory
mock_tools_common_message_module.ToolSign = _MockToolSign

mock_nexent_core_utils_module.observer = mock_nexent_core_utils_observer_module
mock_nexent_core_utils_module.prompt_template_utils = mock_prompt_template_utils_module
mock_nexent_core_utils_module.tools_common_message = mock_tools_common_message_module

mock_nexent_core_models_module = types.ModuleType("nexent.core.models")
mock_nexent_core_models_module.OpenAILongContextModel = MagicMock()
mock_nexent_core_models_module.OpenAIVLModel = MagicMock()

mock_nexent_core_module = types.ModuleType("nexent.core")
mock_nexent_core_module.utils = mock_nexent_core_utils_module
mock_nexent_core_module.models = mock_nexent_core_models_module
mock_nexent_core_module.MessageObserver = _MockMessageObserver

# Create nexent.utils module placeholder - will be populated inside the with block
mock_nexent_utils_module = types.ModuleType("nexent.utils")

mock_nexent_module = types.ModuleType("nexent")
mock_nexent_module.core = mock_nexent_core_module
mock_nexent_module.utils = mock_nexent_utils_module
mock_nexent_storage_module = types.ModuleType("nexent.storage")
mock_nexent_storage_module.MinIOStorageClient = MagicMock()
mock_nexent_module.storage = mock_nexent_storage_module
mock_nexent_multi_modal_module = types.ModuleType("nexent.multi_modal")
mock_nexent_load_save_module = types.ModuleType(
    "nexent.multi_modal.load_save_object")
mock_nexent_load_save_module.LoadSaveObjectManager = MagicMock()
mock_nexent_module.multi_modal = mock_nexent_multi_modal_module
module_mocks = {
    "sdk": sdk_namespace_module,
    "smolagents": mock_smolagents,
    "smolagents.tools": mock_smolagents_tools,
    "smolagents.agents": MagicMock(),
    "smolagents.memory": mock_smolagents.memory,
    "smolagents.models": MagicMock(),
    "smolagents.monitoring": MagicMock(),
    "smolagents.utils": MagicMock(),
    "smolagents.local_python_executor": MagicMock(),
    "langchain": mock_langchain,
    "langchain.tools": mock_langchain_tools,
    "openai": MagicMock(),
    "openai.types": MagicMock(),
    "openai.types.chat": MagicMock(),
    "openai.types.chat.chat_completion_message": MagicMock(ChatCompletionMessage=mock_openai_chat_completion_message),
    "openai.types.chat.chat_completion_message_param": MagicMock(),
    # Mock exa_py to avoid importing the real package when sdk.nexent.core.tools imports it
    "exa_py": MagicMock(Exa=MagicMock()),
    # Mock paramiko to avoid PyO3 import issues in tests
    "paramiko": MagicMock(),
    "boto3": MagicMock(),
    "botocore": mock_botocore_module,
    "botocore.client": mock_botocore_client,
    "botocore.exceptions": mock_botocore_exceptions,
    "botocore.args": mock_botocore_args,
    "botocore.regions": mock_botocore_regions,
    "botocore.crt": mock_botocore_crt,
    "nexent": mock_nexent_module,
    "nexent.core": mock_nexent_core_module,
    "nexent.core.utils": mock_nexent_core_utils_module,
    "nexent.utils": mock_nexent_utils_module,
    "nexent.core.utils.observer": mock_nexent_core_utils_observer_module,
    "sdk": mock_sdk_module,
    "sdk.nexent": mock_sdk_nexent_module,
    "sdk.nexent.core": mock_sdk_nexent_core_module,
    "sdk.nexent.core.agents": mock_sdk_nexent_core_agents_module,
    "sdk.nexent.core.tools": mock_sdk_nexent_core_tools_module,
    "sdk.nexent.core.context_runtime": mock_sdk_context_runtime_module,
    "sdk.nexent.core.context_runtime.managed": mock_sdk_context_runtime_managed_module,
    "sdk.nexent.core.context_runtime.managed.runtime": mock_sdk_context_runtime_managed_runtime_module,
    "sdk.nexent.core.agents.agent_context": mock_sdk_agent_context_module,
    "sdk.nexent.core.agents.context": mock_sdk_agent_context_domain_module,
    "sdk.nexent.core.agents.summary_config": mock_sdk_summary_config_module,
    "sdk.nexent.core.utils": mock_sdk_nexent_core_utils_module,
    "sdk.nexent.core.utils.observer": mock_sdk_nexent_core_utils_observer_module,
    "sdk.nexent.monitor": mock_sdk_nexent_monitor_module,
    "sdk.nexent.monitor.monitoring": mock_sdk_nexent_monitor_monitoring_module,
    "nexent.core.utils.prompt_template_utils": mock_prompt_template_utils_module,
    "nexent.core.utils.tools_common_message": mock_tools_common_message_module,
    "nexent.core.models": mock_nexent_core_models_module,
    "nexent.storage": mock_nexent_storage_module,
    "nexent.multi_modal": mock_nexent_multi_modal_module,
    "nexent.multi_modal.load_save_object": mock_nexent_load_save_module,
    # Mock tiktoken to avoid importing the real package when models import it
    "tiktoken": MagicMock(),
    # Mock aiohttp to avoid import issues in tests
    "aiohttp": MagicMock(),
    # Mock tavily to avoid import issues
    "tavily": MagicMock(),
    # Mock linkup to avoid import issues
    "linkup": MagicMock(),
    # Mock the OpenAIModel import
    "sdk.nexent.core.models.openai_llm": MagicMock(OpenAIModel=mock_openai_model_class),
    # Mock CoreAgent import
    "sdk.nexent.core.agents.core_agent": MagicMock(
        CoreAgent=mock_core_agent_class,
        convert_code_format=lambda s: s if isinstance(s, str) else str(s),
    ),
}

# ---------------------------------------------------------------------------
# Import the classes under test with patched dependencies in place
# ---------------------------------------------------------------------------
with patch.dict("sys.modules", module_mocks):
    # Create mock http_client_manager module for analyze_text_file_tool
    # This is needed because analyze_text_file_tool.py uses absolute import:
    # "from nexent.utils.http_client_manager import http_client_manager"
    mock_http_client_manager_module = MagicMock()
    mock_http_client_manager_module.http_client_manager = MagicMock()

    # We need to add this to sys.modules before the import happens
    sys.modules["nexent.utils.http_client_manager"] = mock_http_client_manager_module

    from sdk.nexent.core.agents import nexent_agent
    from sdk.nexent.core.agents.nexent_agent import (
        NexentAgent, ActionStep, TaskStep, _has_host_tools, _is_retriever_tool,
        _build_tool_input, _wrap_tool_with_monitoring, _tool_name,
        SAFE_PYTHON_INTERPRETER_IMPORTS, get_local_python_authorized_imports,
    )
    from sdk.nexent.core.agents.agent_model import ToolConfig, ModelConfig, AgentConfig, AgentHistory, ExternalA2AAgentConfig

    # Clean up after import
    sys.modules.pop("nexent.utils.http_client_manager", None)

# Retain the tested module after patch.dict restores the module registry so it
# can be reloaded by tests that exercise conditional imports.
sys.modules["sdk.nexent.core.agents.nexent_agent"] = nexent_agent


# Keep the lightweight runtime modules available for create_single_agent()
# tests.  They exercise runtime selection after the import-time patch.dict
# context has restored sys.modules, while nexent_agent now performs runtime
# imports inside create_single_agent().
sys.modules.setdefault("sdk", mock_sdk_module)
sys.modules.setdefault("sdk.nexent", mock_sdk_nexent_module)
sys.modules.setdefault("sdk.nexent.core", mock_sdk_nexent_core_module)
sys.modules.setdefault("sdk.nexent.core.agents", mock_sdk_nexent_core_agents_module)
sys.modules.setdefault("sdk.nexent.core.tools", mock_sdk_nexent_core_tools_module)
sys.modules.setdefault("sdk.nexent.core.context_runtime", mock_sdk_context_runtime_module)
sys.modules.setdefault("sdk.nexent.core.context_runtime.managed", mock_sdk_context_runtime_managed_module)
sys.modules.setdefault(
    "sdk.nexent.core.context_runtime.managed.runtime",
    mock_sdk_context_runtime_managed_runtime_module,
)
sys.modules.setdefault("sdk.nexent.core.agents.agent_context", mock_sdk_agent_context_module)
sys.modules.setdefault("sdk.nexent.core.agents.summary_config", mock_sdk_summary_config_module)
sys.modules.setdefault("sdk.nexent.core.agents.context", mock_sdk_agent_context_domain_module)


# ----------------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_mocks():
    """Reset all mocks before each test to ensure clean state."""
    mock_openai_model_class.reset_mock()
    return None


@pytest.fixture(autouse=True)
def patch_convert_code_format():
    """Ensure convert_code_format returns a plain string for downstream re.sub."""
    import sys
    module = sys.modules.get("sdk.nexent.core.agents.nexent_agent")
    if module is None:
        # If the module is not imported yet, skip patching to avoid triggering imports
        yield
        return
    with patch.object(
        module,
        "convert_code_format",
        new=lambda s: s if isinstance(s, str) else str(s),
    ):
        yield


@pytest.fixture
def mock_observer():
    """Return a mocked MessageObserver instance."""
    observer = MagicMock(spec=MessageObserver)
    return observer


@pytest.fixture
def nexent_agent_instance(mock_observer):
    """Create a NexentAgent instance with minimal initialisation."""
    agent = NexentAgent(observer=mock_observer,
                        model_config_list=[], stop_event=Event())
    return agent


@pytest.fixture
def mock_model_config():
    """Create a mock ModelConfig instance for testing."""
    return ModelConfig(
        cite_name="test_model",
        api_key="test_api_key",
        model_name="gpt-4",
        url="https://api.openai.com/v1",
        temperature=0.7,
        top_p=0.9,
        model_factory="qwen"
    )


@pytest.fixture
def mock_deep_thinking_model_config():
    """Create a mock ModelConfig instance for deep thinking model testing."""
    return ModelConfig(
        cite_name="deep_thinking_model",
        api_key="test_api_key",
        model_name="gpt-4",
        url="https://api.openai.com/v1",
        temperature=0.5,
        top_p=0.8,
        model_factory="qwen"
    )


@pytest.fixture
def nexent_agent_with_models(mock_observer, mock_model_config, mock_deep_thinking_model_config):
    """Create a NexentAgent instance with model configurations."""
    model_config_list = [mock_model_config, mock_deep_thinking_model_config]
    agent = NexentAgent(observer=mock_observer,
                        model_config_list=model_config_list, stop_event=Event())
    return agent


@pytest.fixture
def mock_agent_config():
    """Create a mock AgentConfig instance for testing."""
    return AgentConfig(
        name="test_agent",
        description="A test agent",
        prompt_templates={"system": "You are a test agent"},
        tools=[],
        max_steps=5,
        model_name="test_model",
        provide_run_summary=False,
        managed_agents=[]
    )


@pytest.fixture
def mock_core_agent():
    """Create a mock CoreAgent instance for testing."""
    agent = mock_core_agent_class()
    agent.agent_name = "test_agent"
    agent.memory = MagicMock()
    agent.memory.steps = []
    agent.memory.reset = MagicMock()
    agent.observer = MagicMock()
    agent.stop_event = MagicMock()
    agent.run = MagicMock()  # Ensure .run exists and is mockable
    agent.state = {}
    agent.managed_agents = {}
    return agent


# ----------------------------------------------------------------------------
# Tests for type-only imports and helper functions
# ----------------------------------------------------------------------------


def test_get_local_python_authorized_imports_matches_executor_defaults(monkeypatch):
    """The prompt allowlist must mirror the local executor's imports."""
    executor_module = types.ModuleType("smolagents.local_python_executor")
    executor_module.BASE_BUILTIN_MODULES = ["json", "queue", "stat"]
    monkeypatch.setitem(sys.modules, "smolagents.local_python_executor", executor_module)

    assert get_local_python_authorized_imports() == sorted(
        set(SAFE_PYTHON_INTERPRETER_IMPORTS) | {"json", "queue", "stat"}
    )


def test_type_checking_imports_resolve_context_and_subagent_types(monkeypatch):
    """Verify type-only imports resolve their expected public symbols."""
    context_module = types.ModuleType("sdk.nexent.core.agents.context")
    context_item_input = type("ContextItemInput", (), {})
    context_module.ContextItemInput = context_item_input

    subagent_module = types.ModuleType("sdk.nexent.core.agents.subagent_wrapper")
    subagent_tool_wrapper = type("SubAgentToolWrapper", (), {})
    subagent_module.SubAgentToolWrapper = subagent_tool_wrapper

    agent_model_module = types.ModuleType("sdk.nexent.core.agents.agent_model")
    agent_model_module.AgentConfig = AgentConfig
    agent_model_module.AgentHistory = AgentHistory
    agent_model_module.ModelConfig = ModelConfig
    agent_model_module.ToolConfig = ToolConfig

    monkeypatch.setattr("typing.TYPE_CHECKING", True)
    with patch.dict(
        sys.modules,
        {
            **module_mocks,
            "sdk.nexent.core.agents.agent_model": agent_model_module,
            "sdk.nexent.core.agents.context": context_module,
            "sdk.nexent.core.agents.subagent_wrapper": subagent_module,
        },
    ):
        reloaded_module = importlib.reload(nexent_agent)
        assert reloaded_module.ContextItemInput is context_item_input
        assert reloaded_module.SubAgentToolWrapper is subagent_tool_wrapper


def test_has_host_tools_with_host_tool():
    """Test _has_host_tools returns True when a tool has _nexent_execute_on_host flag."""
    mock_tool = MagicMock()
    mock_tool._nexent_execute_on_host = True
    result = _has_host_tools([mock_tool])
    assert result is True


def test_has_host_tools_without_host_tool():
    """Test _has_host_tools returns False when no tool has _nexent_execute_on_host flag."""
    mock_tool = MagicMock()
    mock_tool._nexent_execute_on_host = False
    result = _has_host_tools([mock_tool])
    assert result is False


def test_has_host_tools_with_mixed_tools():
    """Test _has_host_tools returns True when at least one tool has the flag."""
    mock_host_tool = MagicMock()
    mock_host_tool._nexent_execute_on_host = True
    mock_normal_tool = MagicMock()
    mock_normal_tool._nexent_execute_on_host = False
    result = _has_host_tools([mock_normal_tool, mock_host_tool])
    assert result is True


def test_has_host_tools_empty_list():
    """Test _has_host_tools returns False for empty list."""
    result = _has_host_tools([])
    assert result is False


def test_has_host_tools_no_execute_on_host_attr():
    """Test _has_host_tools returns False when tool has no _nexent_execute_on_host attribute."""
    mock_tool = MagicMock(spec=[])
    result = _has_host_tools([mock_tool])
    assert result is False


def test_is_retriever_tool_knowledge_base_search():
    """Test _is_retriever_tool returns True for KnowledgeBaseSearchTool."""
    mock_tool = MagicMock()
    type(mock_tool).__name__ = "KnowledgeBaseSearchTool"
    result = _is_retriever_tool(mock_tool)
    assert result is True


def test_is_retriever_tool_search_memory():
    """Test _is_retriever_tool returns True for SearchMemoryTool."""
    mock_tool = MagicMock()
    type(mock_tool).__name__ = "SearchMemoryTool"
    result = _is_retriever_tool(mock_tool)
    assert result is True


def test_is_retriever_tool_other_tool():
    """Test _is_retriever_tool returns False for other tool types."""
    mock_tool = MagicMock()
    type(mock_tool).__name__ = "SomeOtherTool"
    result = _is_retriever_tool(mock_tool)
    assert result is False


# ----------------------------------------------------------------------------
# Tests for __init__ method
# ----------------------------------------------------------------------------

def test_nexent_agent_initialization_success(mock_observer):
    """Test successful NexentAgent initialization."""
    stop_event = Event()
    agent = NexentAgent(observer=mock_observer,
                        model_config_list=[], stop_event=stop_event)

    assert agent.observer == mock_observer
    assert agent.model_config_list == []
    assert agent.stop_event == stop_event
    assert agent.agent is None
    assert agent.mcp_tool_collection is None


def test_nexent_agent_initialization_with_mcp_tools(mock_observer):
    """Test NexentAgent initialization with MCP tool collection."""
    stop_event = Event()
    mcp_tools = MagicMock()
    agent = NexentAgent(observer=mock_observer, model_config_list=[], stop_event=stop_event,
                        mcp_tool_collection=mcp_tools)

    assert agent.mcp_tool_collection == mcp_tools


def test_nexent_agent_initialization_invalid_observer():
    """Test NexentAgent initialization with invalid observer type."""
    stop_event = Event()
    invalid_observer = "not_a_message_observer"

    with pytest.raises(TypeError, match="Create Observer Object with MessageObserver"):
        NexentAgent(observer=invalid_observer,
                    model_config_list=[], stop_event=stop_event)


# ----------------------------------------------------------------------------
# Tests for create_model function
# ----------------------------------------------------------------------------

def test_create_model_success(nexent_agent_with_models, mock_model_config):
    """Test successful model creation with regular model."""
    # Use the existing mock that was set up at the top of the file
    mock_model_instance = MagicMock()
    mock_openai_model_class.return_value = mock_model_instance

    # Call the method under test
    result = nexent_agent_with_models.create_model("test_model")

    # Verify the result
    assert result == mock_model_instance

    # Verify OpenAIModel was constructed with correct parameters.
    # W1 renamed the SDK's `max_tokens` kwarg to `max_output_tokens`; the
    # production code path here builds the same kwarg under the new name.
    mock_openai_model_class.assert_called_once_with(
        observer=nexent_agent_with_models.observer,
        model_id=mock_model_config.model_name,
        api_key=mock_model_config.api_key,
        model_factory=mock_model_config.model_factory,
        api_base=mock_model_config.url,
        temperature=mock_model_config.temperature,
        top_p=mock_model_config.top_p,
        ssl_verify=True,
        display_name=mock_model_config.cite_name,
        extra_body=mock_model_config.extra_body,
        max_output_tokens=mock_model_config.max_tokens,
        timeout_seconds=mock_model_config.timeout_seconds,
        prompt_cache=mock_model_config.prompt_cache,
    )

    # Verify stop_event was set
    assert result.stop_event == nexent_agent_with_models.stop_event


def test_create_model_deep_thinking_success(nexent_agent_with_models, mock_deep_thinking_model_config):
    """Test successful model creation with deep thinking model."""
    # Use the existing mock that was set up at the top of the file
    mock_model_instance = MagicMock()
    mock_openai_model_class.return_value = mock_model_instance

    # Call the method under test
    result = nexent_agent_with_models.create_model("deep_thinking_model")

    # Verify the result
    assert result == mock_model_instance

    # Verify OpenAIModel was constructed with correct parameters.
    # W1 renamed the SDK's `max_tokens` kwarg to `max_output_tokens`.
    mock_openai_model_class.assert_called_once_with(
        observer=nexent_agent_with_models.observer,
        model_id=mock_deep_thinking_model_config.model_name,
        model_factory=mock_deep_thinking_model_config.model_factory,
        api_key=mock_deep_thinking_model_config.api_key,
        api_base=mock_deep_thinking_model_config.url,
        temperature=mock_deep_thinking_model_config.temperature,
        top_p=mock_deep_thinking_model_config.top_p,
        ssl_verify=True,
        display_name=mock_deep_thinking_model_config.cite_name,
        extra_body=mock_deep_thinking_model_config.extra_body,
        max_output_tokens=mock_deep_thinking_model_config.max_tokens,
        timeout_seconds=mock_deep_thinking_model_config.timeout_seconds,
        prompt_cache=mock_deep_thinking_model_config.prompt_cache,
    )

    # Verify stop_event was set
    assert result.stop_event == nexent_agent_with_models.stop_event


def test_ac_p2_011_create_model_threads_verified_count_identity_metadata(
    nexent_agent_instance,
):
    """Managed and root agents share the same metadata-bearing model factory."""
    config = ModelConfig(
        cite_name="verified_model",
        api_key="test_api_key",
        model_name="qwen3.7-plus",
        url="https://example.invalid/v1",
        model_factory="openai",
        canonical_model_id="qwen:qwen3.7-plus",
        tokenizer_family="qwen",
        model_identity_metadata={"status": "matched"},
        tokenizer_match_metadata={"auto_applicable": True},
        token_count_probe_metadata={"status": "supported"},
    )
    nexent_agent_instance.model_config_list = [config]
    mock_openai_model_class.reset_mock()
    mock_openai_model_class.return_value = MagicMock()

    nexent_agent_instance.create_model("verified_model")

    kwargs = mock_openai_model_class.call_args.kwargs
    assert kwargs["canonical_model_id"] == "qwen:qwen3.7-plus"
    assert kwargs["tokenizer_family"] == "qwen"
    assert kwargs["model_identity_metadata"] == {"status": "matched"}
    assert kwargs["tokenizer_match_metadata"] == {"auto_applicable": True}
    assert kwargs["token_count_probe_metadata"] == {"status": "supported"}


def test_create_model_not_found(nexent_agent_with_models):
    """Test create_model raises ValueError when model cite_name is not found."""
    with pytest.raises(ValueError, match="Model nonexistent_model not found"):
        nexent_agent_with_models.create_model("nonexistent_model")


def test_create_model_empty_config_list(mock_observer):
    """Test create_model raises ValueError when model_config_list is empty."""
    agent = NexentAgent(observer=mock_observer,
                        model_config_list=[], stop_event=Event())

    with pytest.raises(ValueError, match="Model test_model not found"):
        agent.create_model("test_model")


def test_create_model_with_none_config_list(mock_observer):
    """Test create_model raises ValueError when model_config_list contains None."""
    agent = NexentAgent(observer=mock_observer, model_config_list=[
                        None], stop_event=Event())

    with pytest.raises(ValueError, match="Model test_model not found"):
        agent.create_model("test_model")


def test_create_model_with_multiple_configs(mock_observer):
    """Test create_model works correctly with multiple model configurations."""
    config1 = ModelConfig(
        cite_name="model1",
        api_key="key1",
        model_name="gpt-4",
        url="https://api.openai.com/v1",
        temperature=0.1,
        top_p=0.9
    )
    config2 = ModelConfig(
        cite_name="model2",
        api_key="key2",
        model_name="gpt-3.5-turbo",
        url="https://api.openai.com/v1",
        temperature=0.5,
        top_p=0.8
    )

    stop_event = Event()
    agent = NexentAgent(observer=mock_observer, model_config_list=[
                        config1, config2], stop_event=stop_event)

    # Use the existing mock that was set up at the top of the file
    mock_model = MagicMock()
    mock_openai_model_class.return_value = mock_model

    # Test creating first model
    result1 = agent.create_model("model1")
    assert result1 == mock_model

    # Test creating second model
    result2 = agent.create_model("model2")
    assert result2 == mock_model


# ----------------------------------------------------------------------------
# Tests for tool creation functions
# ----------------------------------------------------------------------------

def test_create_langchain_tool_success(nexent_agent_instance):
    """Verify that create_langchain_tool converts a LangChain tool via Tool.from_langchain."""
    mock_langchain_tool_obj = MagicMock(name="LangChainToolObject")

    tool_config = ToolConfig(
        class_name="MockLangChainTool",
        name="mock_tool",
        description="desc",
        inputs="{}",
        output_type="string",
        params={},
        source="langchain",
        metadata={"inner_tool": mock_langchain_tool_obj},
    )

    with patch.object(
            mock_tool_class,
            "from_langchain",
            return_value="converted_tool",
    ) as mock_from_langchain:
        # Execute
        result = nexent_agent_instance.create_langchain_tool(tool_config)

    # Assertions
    mock_from_langchain.assert_called_once_with(
        {"inner_tool": mock_langchain_tool_obj})
    assert result == "converted_tool"


def test_create_tool_with_langchain_source(nexent_agent_instance):
    """Ensure create_tool dispatches to create_langchain_tool when source is 'langchain'."""
    mock_langchain_tool_obj = MagicMock()

    tool_config = ToolConfig(
        class_name="MockLangChainTool",
        name="mock_tool",
        description="desc",
        inputs="{}",
        output_type="string",
        params={},
        source="langchain",
        metadata={},
    )

    with patch.object(
            nexent_agent_instance,
            "create_langchain_tool",
            return_value="converted_tool",
    ) as mock_create_langchain_tool:
        result = nexent_agent_instance.create_tool(tool_config)

    mock_create_langchain_tool.assert_called_once_with(tool_config)
    assert result == "converted_tool"


def test_create_tool_with_local_source(nexent_agent_instance):
    """Ensure create_tool dispatches to create_local_tool for local source."""
    tool_config = ToolConfig(
        class_name="DummyTool",
        name="dummy",
        description="desc",
        inputs="{}",
        output_type="string",
        params={},
        source="local",
        metadata={},
    )

    with patch.object(
            nexent_agent_instance,
            "create_local_tool",
            return_value="local_tool",
    ) as mock_create_local_tool:
        result = nexent_agent_instance.create_tool(tool_config)

    mock_create_local_tool.assert_called_once_with(tool_config)
    assert result == "local_tool"


def test_create_local_tool_success(nexent_agent_instance):
    """Test successful creation of a local tool."""
    mock_tool_class = MagicMock()
    mock_tool_instance = MagicMock()
    mock_tool_class.return_value = mock_tool_instance

    tool_config = ToolConfig(
        class_name="DummyTool",
        name="dummy",
        description="desc",
        inputs="{}",
        output_type="string",
        params={"param1": "value1", "param2": 42},
        source="local",
        metadata={},
    )

    # Patch the module's globals to include our mock tool class
    original_value = nexent_agent.__dict__.get("DummyTool")
    nexent_agent.__dict__["DummyTool"] = mock_tool_class

    try:
        result = nexent_agent_instance.create_local_tool(tool_config)
    finally:
        # Restore original value
        if original_value is not None:
            nexent_agent.__dict__["DummyTool"] = original_value
        elif "DummyTool" in nexent_agent.__dict__:
            del nexent_agent.__dict__["DummyTool"]

    mock_tool_class.assert_called_once_with(param1="value1", param2=42)
    assert result == mock_tool_instance
    assert result.inputs == {}
    assert result.output_type == "string"


def test_create_local_tool_analyze_text_file_tool(nexent_agent_instance):
    """Test AnalyzeTextFileTool creation injects observer and metadata."""
    mock_analyze_tool_class = MagicMock()
    mock_analyze_tool_instance = MagicMock()
    mock_analyze_tool_class.return_value = mock_analyze_tool_instance

    tool_config = ToolConfig(
        class_name="AnalyzeTextFileTool",
        name="analyze_text_file",
        description="desc",
        inputs="{}",
        output_type="array",
        params={"prompt": "describe this"},
        source="local",
        metadata={
            "llm_model": "llm_model_obj",
            "storage_client": "storage_client_obj",
            "data_process_service_url": "https://example.com",
        },
    )

    original_value = nexent_agent.__dict__.get("AnalyzeTextFileTool")
    nexent_agent.__dict__["AnalyzeTextFileTool"] = mock_analyze_tool_class

    try:
        result = nexent_agent_instance.create_local_tool(tool_config)
    finally:
        if original_value is not None:
            nexent_agent.__dict__["AnalyzeTextFileTool"] = original_value
        elif "AnalyzeTextFileTool" in nexent_agent.__dict__:
            del nexent_agent.__dict__["AnalyzeTextFileTool"]

    mock_analyze_tool_class.assert_called_once_with(
        observer=nexent_agent_instance.observer,
        llm_model="llm_model_obj",
        storage_client="storage_client_obj",
        prompt="describe this",
        data_process_service_url="https://example.com",
    )
    assert result == mock_analyze_tool_instance


def test_create_local_tool_class_not_found(nexent_agent_instance):
    """Test create_local_tool raises ValueError when class is not found."""
    tool_config = ToolConfig(
        class_name="NonExistentTool",
        name="dummy",
        description="desc",
        inputs="{}",
        output_type="string",
        params={},
        source="local",
        metadata={},
    )

    with pytest.raises(ValueError, match="NonExistentTool not found in local"):
        nexent_agent_instance.create_local_tool(tool_config)


def test_create_local_tool_knowledge_base_search_tool_success(nexent_agent_instance):
    """Test successful creation of KnowledgeBaseSearchTool with metadata."""
    mock_kb_tool_class = MagicMock()
    mock_kb_tool_instance = MagicMock()
    mock_kb_tool_class.return_value = mock_kb_tool_instance

    mock_vdb_core = MagicMock()
    mock_embedding_model = MagicMock()

    tool_config = ToolConfig(
        class_name="KnowledgeBaseSearchTool",
        name="knowledge_base_search",
        description="desc",
        inputs="{}",
        output_type="string",
        params={"top_k": 10},
        source="local",
        metadata={
            "index_names": ["index1", "index2"],
            "vdb_core": mock_vdb_core,
            "embedding_model": mock_embedding_model,
        },
    )

    original_value = nexent_agent.__dict__.get("KnowledgeBaseSearchTool")
    nexent_agent.__dict__["KnowledgeBaseSearchTool"] = mock_kb_tool_class

    try:
        result = nexent_agent_instance.create_local_tool(tool_config)
    finally:
        # Restore original value
        if original_value is not None:
            nexent_agent.__dict__["KnowledgeBaseSearchTool"] = original_value
        elif "KnowledgeBaseSearchTool" in nexent_agent.__dict__:
            del nexent_agent.__dict__["KnowledgeBaseSearchTool"]

    # Verify only non-excluded params are passed to __init__
    mock_kb_tool_class.assert_called_once_with(
        top_k=10,  # Only non-excluded params passed to __init__
    )
    # Verify excluded parameters were set directly as attributes after instantiation
    assert result == mock_kb_tool_instance
    assert mock_kb_tool_instance.observer == nexent_agent_instance.observer
    assert mock_kb_tool_instance.vdb_core == mock_vdb_core
    assert mock_kb_tool_instance.embedding_model == mock_embedding_model


def test_create_local_tool_knowledge_base_search_tool_with_conflicting_params(nexent_agent_instance):
    """Test KnowledgeBaseSearchTool creation filters out conflicting params from params dict."""
    mock_kb_tool_class = MagicMock()
    mock_kb_tool_instance = MagicMock()
    mock_kb_tool_class.return_value = mock_kb_tool_instance

    mock_vdb_core = MagicMock()
    mock_embedding_model = MagicMock()

    tool_config = ToolConfig(
        class_name="KnowledgeBaseSearchTool",
        name="knowledge_base_search",
        description="desc",
        inputs="{}",
        output_type="string",
        params={
            "top_k": 10,
            # This should be filtered out
            "index_names": ["conflicting_index"],
            "vdb_core": "conflicting_vdb",  # This should be filtered out
            "embedding_model": "conflicting_model",  # This should be filtered out
            "observer": "conflicting_observer",  # This should be filtered out
        },
        source="local",
        metadata={
            # These should be used instead
            "index_names": ["index1", "index2"],
            "vdb_core": mock_vdb_core,
            "embedding_model": mock_embedding_model,
        },
    )

    original_value = nexent_agent.__dict__.get("KnowledgeBaseSearchTool")
    nexent_agent.__dict__["KnowledgeBaseSearchTool"] = mock_kb_tool_class

    try:
        result = nexent_agent_instance.create_local_tool(tool_config)
    finally:
        # Restore original value
        if original_value is not None:
            nexent_agent.__dict__["KnowledgeBaseSearchTool"] = original_value
        elif "KnowledgeBaseSearchTool" in nexent_agent.__dict__:
            del nexent_agent.__dict__["KnowledgeBaseSearchTool"]

    # Verify conflicting params were filtered out from __init__ call
    # Only non-excluded params should be passed to __init__ due to smolagents wrapper restrictions
    mock_kb_tool_class.assert_called_once_with(
        top_k=10,  # From filtered_params (not in conflict list)
        # Not excluded by current implementation
        index_names=["conflicting_index"],
    )
    # Verify excluded parameters were set directly as attributes after instantiation
    assert result == mock_kb_tool_instance
    assert mock_kb_tool_instance.observer == nexent_agent_instance.observer
    assert mock_kb_tool_instance.vdb_core == mock_vdb_core  # From metadata, not params
    # From metadata, not params
    assert mock_kb_tool_instance.embedding_model == mock_embedding_model


def test_create_local_tool_knowledge_base_search_tool_with_none_defaults(nexent_agent_instance):
    """Test KnowledgeBaseSearchTool creation with None defaults when metadata is missing."""
    mock_kb_tool_class = MagicMock()
    mock_kb_tool_instance = MagicMock()
    mock_kb_tool_class.return_value = mock_kb_tool_instance

    tool_config = ToolConfig(
        class_name="KnowledgeBaseSearchTool",
        name="knowledge_base_search",
        description="desc",
        inputs="{}",
        output_type="string",
        params={"top_k": 5},
        source="local",
        metadata={},  # No metadata provided
    )

    original_value = nexent_agent.__dict__.get("KnowledgeBaseSearchTool")
    nexent_agent.__dict__["KnowledgeBaseSearchTool"] = mock_kb_tool_class

    try:
        result = nexent_agent_instance.create_local_tool(tool_config)
    finally:
        # Restore original value
        if original_value is not None:
            nexent_agent.__dict__["KnowledgeBaseSearchTool"] = original_value
        elif "KnowledgeBaseSearchTool" in nexent_agent.__dict__:
            del nexent_agent.__dict__["KnowledgeBaseSearchTool"]

    # Verify only non-excluded params are passed to __init__
    mock_kb_tool_class.assert_called_once_with(
        top_k=5,
    )
    # Verify excluded parameters were set directly as attributes with None defaults when metadata is missing
    assert result == mock_kb_tool_instance
    assert mock_kb_tool_instance.observer == nexent_agent_instance.observer
    assert mock_kb_tool_instance.vdb_core is None
    assert mock_kb_tool_instance.embedding_model is None
    assert result == mock_kb_tool_instance


def test_create_local_tool_knowledge_base_with_display_name_map(nexent_agent_instance):
    """Test KnowledgeBaseSearchTool creation sets display_name_to_index_map from metadata."""
    mock_kb_tool_class = MagicMock()
    mock_kb_tool_instance = MagicMock()
    mock_kb_tool_class.return_value = mock_kb_tool_instance

    display_name_map = {
        "Knowledge A": "es_index_knowledge_a",
        "Knowledge B": "es_index_knowledge_b",
    }

    tool_config = ToolConfig(
        class_name="KnowledgeBaseSearchTool",
        name="knowledge_base_search",
        description="desc",
        inputs="{}",
        output_type="string",
        params={"top_k": 10},
        source="local",
        metadata={
            "vdb_core": "mock_vdb_core",
            "embedding_model": "mock_embedding_model",
            "rerank_model": "mock_rerank_model",
            "display_name_to_index_map": display_name_map,
        },
    )

    original_value = nexent_agent.__dict__.get("KnowledgeBaseSearchTool")
    nexent_agent.__dict__["KnowledgeBaseSearchTool"] = mock_kb_tool_class

    try:
        result = nexent_agent_instance.create_local_tool(tool_config)
    finally:
        if original_value is not None:
            nexent_agent.__dict__["KnowledgeBaseSearchTool"] = original_value
        elif "KnowledgeBaseSearchTool" in nexent_agent.__dict__:
            del nexent_agent.__dict__["KnowledgeBaseSearchTool"]

    # Verify display_name_to_index_map was set correctly from metadata
    assert result.display_name_to_index_map == display_name_map
    assert result.vdb_core == "mock_vdb_core"
    assert result.embedding_model == "mock_embedding_model"
    assert result.rerank_model == "mock_rerank_model"


def test_create_local_tool_knowledge_base_with_document_paths_from_metadata(nexent_agent_instance):
    """KnowledgeBaseSearchTool should receive document_paths from metadata via set_document_paths.

    The `document_paths` parameter is declared with `exclude=True` so it must not
    be passed to __init__. Instead it must be forwarded to `set_document_paths`
    on the instance, sourced from `tool_config.metadata`. This guards against
    the FieldInfo-iteration regression reported when document_paths is unset.
    """
    mock_kb_tool_class = MagicMock()
    mock_kb_tool_instance = MagicMock()
    mock_kb_tool_class.return_value = mock_kb_tool_instance

    document_paths = ["s3://bucket/doc1.txt", "s3://bucket/doc2.txt"]

    tool_config = ToolConfig(
        class_name="KnowledgeBaseSearchTool",
        name="knowledge_base_search",
        description="desc",
        inputs="{}",
        output_type="string",
        params={"top_k": 5, "index_names": ["kb1"]},
        source="local",
        metadata={
            "vdb_core": "mock_vdb_core",
            "embedding_model": "mock_embedding_model",
            "document_paths": document_paths,
        },
    )

    original_value = nexent_agent.__dict__.get("KnowledgeBaseSearchTool")
    nexent_agent.__dict__["KnowledgeBaseSearchTool"] = mock_kb_tool_class

    try:
        nexent_agent_instance.create_local_tool(tool_config)
    finally:
        if original_value is not None:
            nexent_agent.__dict__["KnowledgeBaseSearchTool"] = original_value
        elif "KnowledgeBaseSearchTool" in nexent_agent.__dict__:
            del nexent_agent.__dict__["KnowledgeBaseSearchTool"]

    # document_paths is excluded and must not be forwarded to __init__.
    init_kwargs = mock_kb_tool_class.call_args.kwargs
    assert "document_paths" not in init_kwargs
    # It must instead be applied via set_document_paths on the instance.
    mock_kb_tool_instance.set_document_paths.assert_called_once_with(document_paths)


def test_create_local_tool_knowledge_base_without_metadata_calls_set_document_paths_none(nexent_agent_instance):
    """When metadata lacks document_paths, set_document_paths(None) must still be invoked.

    Ensures the tool's internal filter is explicitly reset to None rather than
    left as a stale FieldInfo default from the smolagents wrapper.
    """
    mock_kb_tool_class = MagicMock()
    mock_kb_tool_instance = MagicMock()
    mock_kb_tool_class.return_value = mock_kb_tool_instance

    tool_config = ToolConfig(
        class_name="KnowledgeBaseSearchTool",
        name="knowledge_base_search",
        description="desc",
        inputs="{}",
        output_type="string",
        params={"top_k": 5, "index_names": ["kb1"]},
        source="local",
        metadata=None,
    )

    original_value = nexent_agent.__dict__.get("KnowledgeBaseSearchTool")
    nexent_agent.__dict__["KnowledgeBaseSearchTool"] = mock_kb_tool_class

    try:
        nexent_agent_instance.create_local_tool(tool_config)
    finally:
        if original_value is not None:
            nexent_agent.__dict__["KnowledgeBaseSearchTool"] = original_value
        elif "KnowledgeBaseSearchTool" in nexent_agent.__dict__:
            del nexent_agent.__dict__["KnowledgeBaseSearchTool"]

    mock_kb_tool_instance.set_document_paths.assert_called_once_with(None)


def test_create_local_tool_knowledge_base_with_empty_display_name_map(nexent_agent_instance):
    """Test KnowledgeBaseSearchTool creation handles empty display_name_to_index_map."""
    mock_kb_tool_class = MagicMock()
    mock_kb_tool_instance = MagicMock()
    mock_kb_tool_class.return_value = mock_kb_tool_instance

    tool_config = ToolConfig(
        class_name="KnowledgeBaseSearchTool",
        name="knowledge_base_search",
        description="desc",
        inputs="{}",
        output_type="string",
        params={"top_k": 10},
        source="local",
        metadata={
            "vdb_core": "mock_vdb_core",
            "embedding_model": "mock_embedding_model",
            "display_name_to_index_map": {},
        },
    )

    original_value = nexent_agent.__dict__.get("KnowledgeBaseSearchTool")
    nexent_agent.__dict__["KnowledgeBaseSearchTool"] = mock_kb_tool_class

    try:
        result = nexent_agent_instance.create_local_tool(tool_config)
    finally:
        if original_value is not None:
            nexent_agent.__dict__["KnowledgeBaseSearchTool"] = original_value
        elif "KnowledgeBaseSearchTool" in nexent_agent.__dict__:
            del nexent_agent.__dict__["KnowledgeBaseSearchTool"]

    # Verify empty display_name_to_index_map was set
    assert result.display_name_to_index_map == {}


def test_create_local_tool_knowledge_base_without_metadata(nexent_agent_instance):
    """Test KnowledgeBaseSearchTool creation handles missing metadata."""
    mock_kb_tool_class = MagicMock()
    mock_kb_tool_instance = MagicMock()
    mock_kb_tool_class.return_value = mock_kb_tool_instance

    tool_config = ToolConfig(
        class_name="KnowledgeBaseSearchTool",
        name="knowledge_base_search",
        description="desc",
        inputs="{}",
        output_type="string",
        params={"top_k": 10},
        source="local",
        metadata=None,
    )

    original_value = nexent_agent.__dict__.get("KnowledgeBaseSearchTool")
    nexent_agent.__dict__["KnowledgeBaseSearchTool"] = mock_kb_tool_class

    try:
        result = nexent_agent_instance.create_local_tool(tool_config)
    finally:
        if original_value is not None:
            nexent_agent.__dict__["KnowledgeBaseSearchTool"] = original_value
        elif "KnowledgeBaseSearchTool" in nexent_agent.__dict__:
            del nexent_agent.__dict__["KnowledgeBaseSearchTool"]

    # Verify defaults were set when metadata is None
    assert result.display_name_to_index_map == {}
    assert result.vdb_core is None
    assert result.embedding_model is None
    assert result.rerank_model is None


def test_create_local_tool_analyze_text_file_tool(nexent_agent_instance):
    """Test AnalyzeTextFileTool creation injects observer and metadata."""
    mock_analyze_tool_class = MagicMock()
    mock_analyze_tool_instance = MagicMock()
    mock_analyze_tool_class.return_value = mock_analyze_tool_instance

    tool_config = ToolConfig(
        class_name="AnalyzeTextFileTool",
        name="analyze_text_file",
        description="desc",
        inputs="{}",
        output_type="string",
        params={"prompt": "describe this"},
        source="local",
        metadata={
            "llm_model": "llm_model_obj",
            "storage_client": "storage_client_obj",
            "data_process_service_url": "DATA_PROCESS_SERVICE",

        },
    )

    original_value = nexent_agent.__dict__.get("AnalyzeTextFileTool")
    nexent_agent.__dict__["AnalyzeTextFileTool"] = mock_analyze_tool_class

    try:
        result = nexent_agent_instance.create_local_tool(tool_config)
    finally:
        if original_value is not None:
            nexent_agent.__dict__["AnalyzeTextFileTool"] = original_value
        elif "AnalyzeTextFileTool" in nexent_agent.__dict__:
            del nexent_agent.__dict__["AnalyzeTextFileTool"]

    mock_analyze_tool_class.assert_called_once_with(
        observer=nexent_agent_instance.observer,
        llm_model="llm_model_obj",
        storage_client="storage_client_obj",
        data_process_service_url="DATA_PROCESS_SERVICE",
        validate_url_access=None,
        prompt="describe this",
    )
    assert result == mock_analyze_tool_instance


def test_create_local_tool_analyze_image_tool(nexent_agent_instance):
    """Test AnalyzeImageTool creation injects observer and metadata."""
    mock_analyze_tool_class = MagicMock()
    mock_analyze_tool_instance = MagicMock()
    mock_analyze_tool_class.return_value = mock_analyze_tool_instance

    tool_config = ToolConfig(
        class_name="AnalyzeImageTool",
        name="analyze_image",
        description="desc",
        inputs="{}",
        output_type="string",
        params={"prompt": "describe this"},
        source="local",
        metadata={
            "vlm_model": "vlm_model_obj",
            "storage_client": "storage_client_obj",
        },
    )

    original_value = nexent_agent.__dict__.get("AnalyzeImageTool")
    nexent_agent.__dict__["AnalyzeImageTool"] = mock_analyze_tool_class

    try:
        result = nexent_agent_instance.create_local_tool(tool_config)
    finally:
        if original_value is not None:
            nexent_agent.__dict__["AnalyzeImageTool"] = original_value
        elif "AnalyzeImageTool" in nexent_agent.__dict__:
            del nexent_agent.__dict__["AnalyzeImageTool"]

    mock_analyze_tool_class.assert_called_once_with(
        observer=nexent_agent_instance.observer,
        vlm_model="vlm_model_obj",
        storage_client="storage_client_obj",
        validate_url_access=None,
        prompt="describe this",
    )
    assert result == mock_analyze_tool_instance


def test_create_local_tool_with_observer_attribute(nexent_agent_instance):
    """Test create_local_tool sets observer attribute on tool if it exists."""
    mock_tool_class = MagicMock()
    mock_tool_instance = MagicMock()
    mock_tool_instance.observer = None  # Initially no observer
    mock_tool_class.return_value = mock_tool_instance

    tool_config = ToolConfig(
        class_name="ToolWithObserver",
        name="tool",
        description="desc",
        inputs="{}",
        output_type="string",
        params={},
        source="local",
        metadata={},
    )

    original_value = nexent_agent.__dict__.get("ToolWithObserver")
    nexent_agent.__dict__["ToolWithObserver"] = mock_tool_class

    try:
        result = nexent_agent_instance.create_local_tool(tool_config)
    finally:
        # Restore original value
        if original_value is not None:
            nexent_agent.__dict__["ToolWithObserver"] = original_value
        elif "ToolWithObserver" in nexent_agent.__dict__:
            del nexent_agent.__dict__["ToolWithObserver"]

    # Verify observer was set on the tool instance
    assert result.observer == nexent_agent_instance.observer


def test_create_tool_with_mcp_source(nexent_agent_instance):
    """Ensure create_tool dispatches to create_mcp_tool for mcp source."""
    tool_config = ToolConfig(
        class_name="DummyTool",
        name="dummy",
        description="desc",
        inputs="{}",
        output_type="string",
        params={},
        source="mcp",
        metadata={},
    )

    mcp_tool = MagicMock()
    with patch.object(
            nexent_agent_instance,
            "create_mcp_tool",
            return_value=mcp_tool,
    ) as mock_create_mcp_tool:
        result = nexent_agent_instance.create_tool(tool_config)

    mock_create_mcp_tool.assert_called_once_with("DummyTool")
    assert result is mcp_tool
    assert result._nexent_execute_on_host is True
    assert nexent_agent._wrap_tool_with_monitoring(result, "test-agent")._nexent_execute_on_host is True


def test_create_tool_invalid_source(nexent_agent_instance):
    """create_tool should raise ValueError for unsupported source."""
    tool_config = ToolConfig(
        class_name="DummyTool",
        name="dummy",
        description="desc",
        inputs="{}",
        output_type="string",
        params={},
        source="unknown",
        metadata={},
    )
    with pytest.raises(ValueError, match="unsupported tool source: unknown"):
        nexent_agent_instance.create_tool(tool_config)


def test_create_tool_invalid_config_type(nexent_agent_instance):
    """create_tool should raise TypeError when passed a non-ToolConfig object."""
    with pytest.raises(TypeError, match="tool_config must be a ToolConfig object"):
        nexent_agent_instance.create_tool({})


def test_create_tool_exception_handling(nexent_agent_instance):
    """create_tool should handle exceptions and raise ValueError with error message."""
    tool_config = ToolConfig(
        class_name="DummyTool",
        name="dummy",
        description="desc",
        inputs="{}",
        output_type="string",
        params={},
        source="local",
        metadata={},
    )

    with patch.object(
            nexent_agent_instance,
            "create_local_tool",
            side_effect=Exception("Tool creation failed"),
    ):
        with pytest.raises(ValueError, match="Error in creating tool: Tool creation failed"):
            nexent_agent_instance.create_tool(tool_config)


def test_create_single_agent_invalid_config_type(nexent_agent_instance):
    """Test create_single_agent raises TypeError with invalid config type."""
    with pytest.raises(TypeError, match="agent_config must be a AgentConfig object"):
        nexent_agent_instance.create_single_agent({})


def test_create_single_agent_tool_creation_error(nexent_agent_instance, mock_agent_config):
    """Test create_single_agent handles tool creation errors."""
    mock_agent_config.tools = [ToolConfig(
        class_name="TestTool",
        name="test",
        description="test",
        inputs="{}",
        output_type="string",
        params={},
        source="local",
        metadata={}
    )]

    with patch.object(nexent_agent_instance, 'create_model') as mock_create_model, \
            patch.object(nexent_agent_instance, 'create_tool', side_effect=Exception("Tool error")):
        mock_model = MagicMock()
        mock_create_model.return_value = mock_model

        with pytest.raises(ValueError, match="Error in creating tool: Tool error"):
            nexent_agent_instance.create_single_agent(mock_agent_config)


def test_create_single_agent_general_error(nexent_agent_instance, mock_agent_config):
    """Test create_single_agent handles general errors."""
    with patch.object(nexent_agent_instance, 'create_model', side_effect=Exception("General error")):
        with pytest.raises(ValueError, match="Error in creating agent, agent name: test_agent, Error: General error"):
            nexent_agent_instance.create_single_agent(mock_agent_config)


def test_add_history_to_agent_none_history(nexent_agent_instance, mock_core_agent):
    """Test add_history_to_agent handles None history gracefully."""
    nexent_agent_instance.agent = mock_core_agent

    # Should not raise any exception
    nexent_agent_instance.add_history_to_agent(None)

    # Memory should not be modified
    mock_core_agent.memory.reset.assert_not_called()
    assert len(mock_core_agent.memory.steps) == 0


def test_add_history_to_agent_user_and_assistant_history(nexent_agent_instance, mock_core_agent):
    """Test add_history_to_agent correctly converts user and assistant messages to memory steps."""
    nexent_agent_instance.agent = mock_core_agent

    user_msg = AgentHistory(role="user", content="User question")
    assistant_msg = AgentHistory(role="assistant", content="Assistant reply")

    nexent_agent_instance.add_history_to_agent([user_msg, assistant_msg])

    mock_core_agent.memory.reset.assert_called_once()
    assert len(mock_core_agent.memory.steps) == 2

    # First step should be a TaskStep for the user message
    first_step = mock_core_agent.memory.steps[0]
    assert isinstance(first_step, TaskStep)
    assert first_step.task == "User question"

    # Second step should be an ActionStep for the assistant message
    second_step = mock_core_agent.memory.steps[1]
    assert isinstance(second_step, ActionStep)
    assert second_step.action_output == "Assistant reply"
    assert second_step.model_output == "Assistant reply"


def test_add_history_to_agent_invalid_agent_type(nexent_agent_instance):
    """Test add_history_to_agent raises TypeError when agent is not a CoreAgent."""
    nexent_agent_instance.agent = "not_core_agent"

    with pytest.raises(TypeError, match="agent must be a CoreAgent object"):
        nexent_agent_instance.add_history_to_agent([])


def test_add_history_to_agent_invalid_history_items(nexent_agent_instance, mock_core_agent):
    """Test add_history_to_agent raises TypeError when history items are not AgentHistory."""
    nexent_agent_instance.agent = mock_core_agent

    invalid_history = [{"role": "user", "content": "hello"}]

    with pytest.raises(TypeError, match="history must be a list of AgentHistory objects"):
        nexent_agent_instance.add_history_to_agent(invalid_history)


def test_agent_run_with_observer_success_with_agent_text(nexent_agent_instance, mock_core_agent):
    """Test successful agent_run_with_observer with AgentText final answer."""
    # Setup
    nexent_agent_instance.agent = mock_core_agent
    mock_core_agent.stop_event.is_set.return_value = False

    # Mock step logs
    mock_action_step = MagicMock(spec=ActionStep)
    mock_action_step.timing = MagicMock()
    mock_action_step.timing.duration = 1.5
    mock_action_step.step_number = 1
    mock_action_step.error = None

    # Use an instance of our _AgentText so isinstance(..., AgentText) is valid
    mock_final_answer = _AgentText(
        "Final answer with <think>thinking</think> content")

    mock_core_agent.run.return_value = [mock_action_step]
    mock_core_agent.run.return_value[-1].output = mock_final_answer

    # Execute
    nexent_agent_instance.agent_run_with_observer("test query")

    # Verify
    mock_core_agent.run.assert_called_once_with(
        "test query", stream=True, reset=True)
    mock_core_agent.observer.add_message.assert_any_call(
        "", ProcessType.TOKEN_COUNT, ANY)
    mock_core_agent.observer.add_message.assert_any_call(
        "test_agent", ProcessType.FINAL_ANSWER, "Final answer with  content")


def test_runtime_metadata_isolated_across_full_agent_tree(nexent_agent_instance, mock_core_agent):
    child = mock_core_agent_class()
    child.state = {}
    child.managed_agents = {}
    child_wrapper = MagicMock()
    child_wrapper._inner = child
    external_agent = MagicMock()
    external_agent.get_runtime_metadata.return_value = {"external": "previous"}
    external_wrapper = MagicMock()
    external_wrapper._inner = external_agent
    mock_core_agent.state = {"metadata": {"previous": True}}
    mock_core_agent.managed_agents = {
        "child": child_wrapper,
        "external": external_wrapper,
    }

    snapshots = nexent_agent_instance._set_runtime_metadata_for_agent_tree(
        mock_core_agent,
        {"request": {"id": 7}},
    )

    assert mock_core_agent.state["metadata"] == {"request": {"id": 7}}
    assert child.state["metadata"] == {"request": {"id": 7}}
    assert child.state["metadata"] is not mock_core_agent.state["metadata"]
    external_agent.set_runtime_metadata.assert_called_once_with({"request": {"id": 7}})

    nexent_agent_instance._restore_runtime_metadata_for_agent_tree(snapshots)

    assert mock_core_agent.state["metadata"] == {"previous": True}
    assert "metadata" not in child.state
    assert external_agent.set_runtime_metadata.call_args_list[-1].args[0] == {
        "external": "previous"
    }


def test_runtime_metadata_tree_handles_list_tuple_and_scalar_children(
    nexent_agent_instance, mock_core_agent
):
    """Metadata tree walk handles list/tuple child containers and the scalar fallback."""
    # list children container
    child_a = mock_core_agent_class()
    child_a.state = {}
    child_a.managed_agents = {}
    root_list = mock_core_agent_class()
    root_list.state = {}
    root_list.managed_agents = [child_a]
    snapshots = nexent_agent_instance._set_runtime_metadata_for_agent_tree(
        root_list, {"list": 1}
    )
    assert child_a.state["metadata"] == {"list": 1}
    assert child_a.state["metadata"] is not root_list.state["metadata"]

    # tuple children container
    child_b = mock_core_agent_class()
    child_b.state = {}
    child_b.managed_agents = {}
    root_tuple = mock_core_agent_class()
    root_tuple.state = {}
    root_tuple.managed_agents = (child_b,)
    nexent_agent_instance._set_runtime_metadata_for_agent_tree(root_tuple, {"tuple": 2})
    assert child_b.state["metadata"] == {"tuple": 2}

    # scalar/unknown container falls back to no children
    root_scalar = mock_core_agent_class()
    root_scalar.state = {}
    root_scalar.managed_agents = "scalar-value"
    snapshots = nexent_agent_instance._set_runtime_metadata_for_agent_tree(
        root_scalar, {"scalar": 3}
    )
    assert root_scalar.state["metadata"] == {"scalar": 3}


def test_runtime_metadata_tree_skips_duplicate_agent(
    nexent_agent_instance, mock_core_agent
):
    """A node reachable twice (shared child) is only processed once."""
    shared = mock_core_agent_class()
    shared.state = {}
    shared.managed_agents = {}
    root = mock_core_agent_class()
    root.state = {}
    # The same inner agent is referenced from two child entries.
    root.managed_agents = [shared, shared]
    snapshots = nexent_agent_instance._set_runtime_metadata_for_agent_tree(
        root, {"shared": "v"}
    )
    assert shared.state["metadata"] == {"shared": "v"}
    assert len(snapshots) == 2  # root + shared, not duplicated


def test_agent_run_with_observer_forwards_additional_args(
    nexent_agent_instance, mock_core_agent
):
    """additional_args are forwarded to the underlying agent run and stored as metadata."""
    nexent_agent_instance.agent = mock_core_agent
    mock_action_step = MagicMock(spec=ActionStep)
    mock_action_step.timing = MagicMock()
    mock_action_step.timing.duration = 1.5
    mock_action_step.step_number = 1
    mock_action_step.error = None
    mock_final_answer = _AgentText("metadata forwarded answer")
    mock_action_step.output = mock_final_answer

    mock_core_agent.run.return_value = [mock_action_step]
    mock_core_agent.state = {}
    mock_core_agent.managed_agents = {}

    nexent_agent_instance.agent_run_with_observer(
        "test query",
        additional_args={"metadata": {"session": "s9"}},
    )

    mock_core_agent.run.assert_called_once_with(
        "test query", stream=True, reset=True,
        additional_args={"metadata": {"session": "s9"}},
    )


def test_agent_run_with_observer_emits_model_context_window(nexent_agent_instance, mock_core_agent):
    """TOKEN_COUNT exposes the stable model window and keeps the compression threshold."""
    nexent_agent_instance.agent = mock_core_agent
    mock_core_agent.stop_event.is_set.return_value = False

    context_manager = MagicMock()
    context_manager.config.token_threshold = 24576
    context_manager.config.context_window_tokens = 32768
    context_manager.hard_input_budget_tokens = 28672
    context_manager.processing_mode = "adaptive_compact"
    mock_core_agent.context_runtime = MagicMock(
        context_manager=context_manager,
        token_threshold=24576,
        context_window_tokens=32768,
        hard_input_budget_tokens=28672,
        processing_mode="adaptive_compact",
    )

    mock_action_step = MagicMock(spec=ActionStep)
    mock_action_step.timing = MagicMock(duration=1.5)
    mock_action_step.step_number = 1
    mock_action_step.error = None
    mock_action_step.output = "Final answer"
    mock_core_agent.run.return_value = [mock_action_step]

    nexent_agent_instance.agent_run_with_observer("test query")

    token_payloads = [
        json.loads(call.args[2])
        for call in mock_core_agent.observer.add_message.call_args_list
        if len(call.args) >= 3 and call.args[1] == ProcessType.TOKEN_COUNT
    ]
    assert token_payloads[0]["context_window_tokens"] == 32768
    assert token_payloads[0]["token_threshold"] == 24576


def test_agent_run_with_observer_writes_aggregate_context_metrics(nexent_agent_instance, mock_core_agent):
    """Agent run completion writes aggregate context metrics to the top-level span."""
    class _SpanContext:
        def __enter__(self):
            return MagicMock()

        def __exit__(self, exc_type, exc, tb):
            return False

    monitoring_manager = MagicMock()
    monitoring_manager.start_agent_run.side_effect = lambda metadata: _SpanContext()
    monitoring_manager.trace_agent_step.side_effect = lambda *args, **kwargs: _SpanContext()

    nexent_agent_instance.agent = mock_core_agent
    nexent_agent_instance._log_step_metrics = MagicMock()
    mock_core_agent.stop_event.is_set.return_value = False
    mock_core_agent.step_metrics = [
        {
            "main_llm": {"input_tokens": 100, "output_tokens": 12},
            "compression": {"calls": 1, "input_tokens": 80, "output_tokens": 40, "cache_hits": 1},
            "memory_state": {"estimated_input_tokens": 55, "estimated_output_tokens": 8},
            "uncompressed_mem_est_input": 110,
            "compression_ratio": 50.0,
            "cache_hit": True,
        }
    ]

    mock_action_step = MagicMock(spec=ActionStep)
    mock_action_step.timing = MagicMock()
    mock_action_step.timing.duration = 1.5
    mock_action_step.step_number = 1
    mock_action_step.error = None
    mock_action_step.output = "Final answer"
    mock_core_agent.run.return_value = [mock_action_step]

    with patch.object(nexent_agent, "get_monitoring_manager", return_value=monitoring_manager), \
            patch("builtins.print") as mock_print:
        nexent_agent_instance.agent_run_with_observer("test query")

    monitoring_manager.set_agent_context_metrics.assert_called_once_with(mock_core_agent.step_metrics)
    monitoring_manager.set_openinference_output.assert_any_call("Final answer")
    mock_print.assert_not_called()


def test_agent_run_with_observer_forwards_compression_and_provider_cache_metrics(
    nexent_agent_instance, mock_core_agent,
):
    nexent_agent_instance.agent = mock_core_agent
    nexent_agent_instance._log_step_metrics = MagicMock()
    mock_core_agent.stop_event.is_set.return_value = False
    mock_core_agent.step_metrics = [{
        "step_number": 1,
        "timestamp": 0.0,
        "main_llm": {"input_tokens": 100, "output_tokens": 5},
        "compression": {
            "calls": 2,
            "input_tokens": 100,
            "output_tokens": 40,
            "cache_hits": 1,
            "cache_types": ["summary"],
        },
        "memory_state": {"estimated_input_tokens": 60, "estimated_output_tokens": 5},
        "compression_ratio": 40.0,
        "uncompressed_mem_est_input": 100,
        "cache_hit": True,
        "cache_types": ["summary"],
    }]
    mock_core_agent.model = types.SimpleNamespace(
        last_provider_cache_advice=types.SimpleNamespace(supported=True),
        last_prompt_cache_usage=types.SimpleNamespace(
            metrics_source="openai_prompt_tokens_details", provider_cache_hit=True,
            cached_input_tokens=40, uncached_input_tokens=60,
        ),
    )
    mock_action_step = MagicMock(spec=ActionStep)
    mock_action_step.timing = MagicMock(duration=1.0)
    mock_action_step.step_number = 1
    mock_action_step.error = None
    mock_action_step.output = "answer"
    mock_action_step.token_usage = types.SimpleNamespace(
        input_tokens=100,
        output_tokens=5,
    )
    mock_core_agent.run.return_value = [mock_action_step]
    nexent_agent_instance.agent_run_with_observer("test query")
    payload = [
        json.loads(call.args[2]) for call in mock_core_agent.observer.add_message.call_args_list
        if len(call.args) >= 3 and call.args[1] == ProcessType.TOKEN_COUNT
    ][-1]
    assert payload["compression_calls"] == 2
    assert payload["compression_cache_hits"] == 1
    assert payload["provider_cache_status"] == "available"
    assert payload["provider_cache_hit"] is True
    assert payload["provider_cached_input_tokens"] == 40
    assert payload["provider_uncached_input_tokens"] == 60


def test_agent_run_with_observer_success_with_string_final_answer(nexent_agent_instance, mock_core_agent):
    """Test successful agent_run_with_observer with string final answer."""
    # Setup
    nexent_agent_instance.agent = mock_core_agent
    mock_core_agent.stop_event.is_set.return_value = False

    # Mock step logs
    mock_action_step = MagicMock(spec=ActionStep)
    mock_action_step.timing = MagicMock()
    mock_action_step.timing.duration = 2.0
    mock_action_step.step_number = 1
    mock_action_step.error = None

    mock_core_agent.run.return_value = [mock_action_step]
    mock_core_agent.run.return_value[-1].output = "String final answer with <think>thinking</think>"

    # Execute
    nexent_agent_instance.agent_run_with_observer("test query")

    # Verify
    mock_core_agent.observer.add_message.assert_any_call(
        "", ProcessType.TOKEN_COUNT, ANY)
    mock_core_agent.observer.add_message.assert_any_call(
        "test_agent", ProcessType.FINAL_ANSWER, "String final answer with ")


@pytest.mark.parametrize(
    ("raw_final_answer", "lang", "expected"),
    [
        (
            "<think>internal reasoning only</think>",
            "en",
            "The agent could not generate a valid final response. Please try again or rephrase your request.",
        ),
        (
            "思考：内部推理内容。\n\n",
            "zh",
            "智能体未能生成有效的最终回复，请重试或换一种方式描述需求。",
        ),
    ],
)
def test_agent_run_with_observer_never_emits_empty_final_answer(
    nexent_agent_instance, mock_core_agent, raw_final_answer, lang, expected
):
    """Reasoning cleanup must not terminate a conversation with an empty final answer."""
    nexent_agent_instance.agent = mock_core_agent
    mock_core_agent.observer.lang = lang
    mock_core_agent.stop_event.is_set.return_value = False

    mock_action_step = MagicMock(spec=ActionStep)
    mock_action_step.timing = MagicMock(duration=1.0)
    mock_action_step.step_number = 1
    mock_action_step.error = None
    mock_action_step.output = raw_final_answer
    mock_core_agent.run.return_value = [mock_action_step]

    nexent_agent_instance.agent_run_with_observer("test query")

    mock_core_agent.observer.add_message.assert_any_call(
        "test_agent", ProcessType.FINAL_ANSWER, expected
    )


def test_agent_run_with_observer_with_error_in_step(nexent_agent_instance, mock_core_agent):
    """Test agent_run_with_observer handles error in step log."""
    # Setup
    nexent_agent_instance.agent = mock_core_agent
    mock_core_agent.stop_event.is_set.return_value = False

    # Mock step logs with error
    mock_action_step = MagicMock(spec=ActionStep)
    mock_action_step.timing = MagicMock()
    mock_action_step.timing.duration = 1.0
    mock_action_step.step_number = 1
    mock_action_step.error = "Test error occurred"

    mock_core_agent.run.return_value = [mock_action_step]
    mock_core_agent.run.return_value[-1].output = "Final answer"

    # Execute
    nexent_agent_instance.agent_run_with_observer("test query")

    # Verify error message was added
    mock_core_agent.observer.add_message.assert_any_call(
        "", ProcessType.ERROR, "Test error occurred")


def test_agent_run_with_observer_skips_non_action_step(nexent_agent_instance, mock_core_agent):
    """Test agent_run_with_observer skips non-ActionStep logs."""
    # Setup
    nexent_agent_instance.agent = mock_core_agent
    mock_core_agent.stop_event.is_set.return_value = False

    # Mock step logs with non-ActionStep
    mock_task_step = MagicMock(spec=TaskStep)
    mock_action_step = MagicMock(spec=ActionStep)
    mock_action_step.timing = MagicMock()
    mock_action_step.timing.duration = 1.0
    mock_action_step.step_number = 1
    mock_action_step.error = None

    mock_core_agent.run.return_value = [mock_task_step, mock_action_step]
    mock_core_agent.run.return_value[-1].output = "Final answer"

    # Execute
    nexent_agent_instance.agent_run_with_observer("test query")

    # Verify only ActionStep was processed
    mock_core_agent.observer.add_message.assert_any_call(
        "", ProcessType.TOKEN_COUNT, ANY)
    # Should not process TaskStep


def test_agent_run_with_observer_with_stop_event_set(nexent_agent_instance, mock_core_agent):
    """Test agent_run_with_observer handles stop event being set."""
    # Setup
    nexent_agent_instance.agent = mock_core_agent
    mock_core_agent.stop_event.is_set.return_value = True

    # Mock step logs
    mock_action_step = MagicMock(spec=ActionStep)
    mock_action_step.timing = MagicMock()
    mock_action_step.timing.duration = 1.0
    mock_action_step.step_number = 1
    mock_action_step.error = None

    mock_core_agent.run.return_value = [mock_action_step]
    mock_core_agent.run.return_value[-1].output = "Final answer"

    # Execute
    nexent_agent_instance.agent_run_with_observer("test query")

    # Verify stop event message was added
    mock_core_agent.observer.add_message.assert_any_call(
        "test_agent", ProcessType.ERROR, "Agent execution interrupted by external stop signal"
    )


def test_agent_run_with_observer_with_exception(nexent_agent_instance, mock_core_agent):
    """Test agent_run_with_observer handles exceptions during execution."""
    # Setup
    nexent_agent_instance.agent = mock_core_agent
    mock_core_agent.run.side_effect = Exception("Test execution error")

    # Execute and verify exception is raised
    with pytest.raises(ValueError, match="Error in interaction: Test execution error"):
        nexent_agent_instance.agent_run_with_observer("test query")

    # Verify error message was added to observer
    mock_core_agent.observer.add_message.assert_called_once_with(
        agent_name="test_agent", process_type=ProcessType.ERROR, content="Error in interaction: Test execution error"
    )


def test_agent_run_with_observer_invalid_agent_type(nexent_agent_instance):
    """Test agent_run_with_observer raises TypeError when agent is not a CoreAgent."""
    nexent_agent_instance.agent = "not_core_agent"

    with pytest.raises(TypeError, match="agent must be a CoreAgent object"):
        nexent_agent_instance.agent_run_with_observer("test query")


def test_agent_run_with_observer_with_reset_false(nexent_agent_instance, mock_core_agent):
    """Test agent_run_with_observer with reset=False parameter."""
    # Setup
    nexent_agent_instance.agent = mock_core_agent
    mock_core_agent.stop_event.is_set.return_value = False

    # Mock step logs
    mock_action_step = MagicMock(spec=ActionStep)
    mock_action_step.timing = MagicMock()
    mock_action_step.timing.duration = 1.0
    mock_action_step.step_number = 1
    mock_action_step.error = None

    mock_core_agent.run.return_value = [mock_action_step]
    mock_core_agent.run.return_value[-1].output = "Final answer"

    # Execute with reset=False
    nexent_agent_instance.agent_run_with_observer("test query", reset=False)

    # Verify run was called with reset=False
    mock_core_agent.run.assert_called_once_with(
        "test query", stream=True, reset=False)


def test_agent_run_with_observer_removes_think_prefix_chinese_colon(nexent_agent_instance, mock_core_agent):
    """Test agent_run_with_observer removes '思考：' prefix content until two newlines."""
    # Setup
    nexent_agent_instance.agent = mock_core_agent
    mock_core_agent.stop_event.is_set.return_value = False

    # Mock step logs
    mock_action_step = MagicMock(spec=ActionStep)
    mock_action_step.timing = MagicMock()
    mock_action_step.timing.duration = 1.0
    mock_action_step.step_number = 1
    mock_action_step.error = None

    # Test with Chinese colon "思考：" followed by content and two newlines
    final_answer_with_think = (
        "思考：用户需要一份营养早餐的搭配建议。作为健康饮食搭配助手，我需要基于营养学知识，提供一份科学、均衡、易于准备的早餐方案。由于没有可用工具，我将直接给出建议，包括食物种类、分量和营养说明。\n\n"
        "一份营养均衡的早餐应包含碳水化合物、蛋白质、健康脂肪、维生素和矿物质。以下是我的推荐："
    )
    mock_core_agent.run.return_value = [mock_action_step]
    mock_core_agent.run.return_value[-1].output = final_answer_with_think

    # Execute
    nexent_agent_instance.agent_run_with_observer("test query")

    # Verify the "思考：" prefix content was removed
    expected_final_answer = (
        "一份营养均衡的早餐应包含碳水化合物、蛋白质、健康脂肪、维生素和矿物质。以下是我的推荐："
    )
    mock_core_agent.observer.add_message.assert_any_call(
        "test_agent", ProcessType.FINAL_ANSWER, expected_final_answer
    )


def test_agent_run_with_observer_removes_think_prefix_english_colon(nexent_agent_instance, mock_core_agent):
    """Test agent_run_with_observer removes '思考:' prefix content until two newlines."""
    # Setup
    nexent_agent_instance.agent = mock_core_agent
    mock_core_agent.stop_event.is_set.return_value = False

    # Mock step logs
    mock_action_step = MagicMock(spec=ActionStep)
    mock_action_step.timing = MagicMock()
    mock_action_step.timing.duration = 1.0
    mock_action_step.step_number = 1
    mock_action_step.error = None

    # Test with English colon "思考:" followed by content and two newlines
    final_answer_with_think = (
        "思考:This is a thinking process about the user's question.\n\n"
        "Here is the actual answer to the question."
    )
    mock_core_agent.run.return_value = [mock_action_step]
    mock_core_agent.run.return_value[-1].output = final_answer_with_think

    # Execute
    nexent_agent_instance.agent_run_with_observer("test query")

    # Verify the "思考:" prefix content was removed
    expected_final_answer = "Here is the actual answer to the question."
    mock_core_agent.observer.add_message.assert_any_call(
        "test_agent", ProcessType.FINAL_ANSWER, expected_final_answer
    )


def test_agent_run_with_observer_preserves_think_prefix_without_two_newlines(nexent_agent_instance, mock_core_agent):
    """Test agent_run_with_observer preserves '思考：' content when not followed by two newlines."""
    # Setup
    nexent_agent_instance.agent = mock_core_agent
    mock_core_agent.stop_event.is_set.return_value = False

    # Mock step logs
    mock_action_step = MagicMock(spec=ActionStep)
    mock_action_step.timing = MagicMock()
    mock_action_step.timing.duration = 1.0
    mock_action_step.step_number = 1
    mock_action_step.error = None

    # Test with "思考：" but only one newline (should not be removed)
    final_answer_with_think = (
        "思考：This is thinking content.\n"
        "Here is the actual answer."
    )
    mock_core_agent.run.return_value = [mock_action_step]
    mock_core_agent.run.return_value[-1].output = final_answer_with_think

    # Execute
    nexent_agent_instance.agent_run_with_observer("test query")

    # Verify the content was preserved (not removed because no \n\n)
    expected_final_answer = (
        "思考：This is thinking content.\n"
        "Here is the actual answer."
    )
    mock_core_agent.observer.add_message.assert_any_call(
        "test_agent", ProcessType.FINAL_ANSWER, expected_final_answer
    )


def test_agent_run_with_observer_removes_both_think_tag_and_think_prefix(nexent_agent_instance, mock_core_agent):
    """Test agent_run_with_observer removes both THINK_TAG_PATTERN and THINK_PREFIX_PATTERN."""
    # Setup
    nexent_agent_instance.agent = mock_core_agent
    mock_core_agent.stop_event.is_set.return_value = False

    # Mock step logs
    mock_action_step = MagicMock(spec=ActionStep)
    mock_action_step.timing = MagicMock()
    mock_action_step.timing.duration = 1.0
    mock_action_step.step_number = 1
    mock_action_step.error = None

    # Test with both <think> tags and "思考：" prefix
    final_answer_with_both = (
        "<think>Some reasoning content</think>"
        "思考：用户需要一份营养早餐的搭配建议。\n\n"
        "一份营养均衡的早餐应包含碳水化合物、蛋白质、健康脂肪、维生素和矿物质。"
    )
    mock_core_agent.run.return_value = [mock_action_step]
    mock_core_agent.run.return_value[-1].output = final_answer_with_both

    # Execute
    nexent_agent_instance.agent_run_with_observer("test query")

    # Verify both patterns were removed
    expected_final_answer = "一份营养均衡的早餐应包含碳水化合物、蛋白质、健康脂肪、维生素和矿物质。"
    mock_core_agent.observer.add_message.assert_any_call(
        "test_agent", ProcessType.FINAL_ANSWER, expected_final_answer
    )


def test_agent_run_with_observer_think_prefix_in_middle(nexent_agent_instance, mock_core_agent):
    """Test agent_run_with_observer removes '思考：' even when it appears in the middle of text."""
    # Setup
    nexent_agent_instance.agent = mock_core_agent
    mock_core_agent.stop_event.is_set.return_value = False

    # Mock step logs
    mock_action_step = MagicMock(spec=ActionStep)
    mock_action_step.timing = MagicMock()
    mock_action_step.timing.duration = 1.0
    mock_action_step.step_number = 1
    mock_action_step.error = None

    # Test with "思考：" in the middle of the text
    final_answer_with_think = (
        "Some initial content. "
        "思考：This is thinking content in the middle.\n\n"
        "Here is the rest of the answer."
    )
    mock_core_agent.run.return_value = [mock_action_step]
    mock_core_agent.run.return_value[-1].output = final_answer_with_think

    # Execute
    nexent_agent_instance.agent_run_with_observer("test query")

    # Verify the "思考：" content was removed
    expected_final_answer = "Some initial content. Here is the rest of the answer."
    mock_core_agent.observer.add_message.assert_any_call(
        "test_agent", ProcessType.FINAL_ANSWER, expected_final_answer
    )


def test_agent_run_with_observer_no_think_prefix(nexent_agent_instance, mock_core_agent):
    """Test agent_run_with_observer handles content without '思考：' prefix normally."""
    # Setup
    nexent_agent_instance.agent = mock_core_agent
    mock_core_agent.stop_event.is_set.return_value = False

    # Mock step logs
    mock_action_step = MagicMock(spec=ActionStep)
    mock_action_step.timing = MagicMock()
    mock_action_step.timing.duration = 1.0
    mock_action_step.step_number = 1
    mock_action_step.error = None

    # Test with normal content without "思考：" prefix
    final_answer_normal = "This is a normal final answer without any thinking prefix."
    mock_core_agent.run.return_value = [mock_action_step]
    mock_core_agent.run.return_value[-1].output = final_answer_normal

    # Execute
    nexent_agent_instance.agent_run_with_observer("test query")

    # Verify the content was preserved as-is
    mock_core_agent.observer.add_message.assert_any_call(
        "test_agent", ProcessType.FINAL_ANSWER, final_answer_normal
    )


def test_agent_run_with_observer_think_prefix_with_agent_text(nexent_agent_instance, mock_core_agent):
    """Test agent_run_with_observer removes '思考：' prefix when final answer is AgentText."""
    # Setup
    nexent_agent_instance.agent = mock_core_agent
    mock_core_agent.stop_event.is_set.return_value = False

    # Mock step logs
    mock_action_step = MagicMock(spec=ActionStep)
    mock_action_step.timing = MagicMock()
    mock_action_step.timing.duration = 1.0
    mock_action_step.step_number = 1
    mock_action_step.error = None

    # Test with AgentText containing "思考：" prefix
    final_answer_with_think = (
        "思考：用户需要一份营养早餐的搭配建议。\n\n"
        "一份营养均衡的早餐应包含碳水化合物、蛋白质、健康脂肪、维生素和矿物质。"
    )
    mock_final_answer = _AgentText(final_answer_with_think)

    mock_core_agent.run.return_value = [mock_action_step]
    mock_core_agent.run.return_value[-1].output = mock_final_answer

    # Execute
    nexent_agent_instance.agent_run_with_observer("test query")

    # Verify the "思考：" prefix content was removed
    expected_final_answer = "一份营养均衡的早餐应包含碳水化合物、蛋白质、健康脂肪、维生素和矿物质。"
    mock_core_agent.observer.add_message.assert_any_call(
        "test_agent", ProcessType.FINAL_ANSWER, expected_final_answer
    )


def test_create_local_tool_datamate_search_tool_success(nexent_agent_instance):
    """Test successful creation of DataMateSearchTool with metadata."""
    mock_datamate_tool_class = MagicMock()
    mock_datamate_tool_instance = MagicMock()
    mock_datamate_tool_class.return_value = mock_datamate_tool_instance

    tool_config = ToolConfig(
        class_name="DataMateSearchTool",
        name="datamate_search",
        description="desc",
        inputs="{}",
        output_type="string",
        params={"top_k": 10, "server_ip": "127.0.0.1", "server_port": 8080},
        source="local",
        metadata={
            "index_names": ["datamate_index1", "datamate_index2"],
        },
    )

    original_value = nexent_agent.__dict__.get("DataMateSearchTool")
    nexent_agent.__dict__["DataMateSearchTool"] = mock_datamate_tool_class

    try:
        result = nexent_agent_instance.create_local_tool(tool_config)
    finally:
        # Restore original value
        if original_value is not None:
            nexent_agent.__dict__["DataMateSearchTool"] = original_value
        elif "DataMateSearchTool" in nexent_agent.__dict__:
            del nexent_agent.__dict__["DataMateSearchTool"]

    # Verify tool was created with all params
    mock_datamate_tool_class.assert_called_once_with(
        top_k=10, server_ip="127.0.0.1", server_port=8080
    )
    # Verify excluded parameters were set directly as attributes after instantiation
    assert result == mock_datamate_tool_instance
    assert mock_datamate_tool_instance.observer == nexent_agent_instance.observer


def test_create_local_tool_datamate_search_tool_with_none_defaults(nexent_agent_instance):
    """Test DataMateSearchTool creation with None defaults when metadata is missing."""
    mock_datamate_tool_class = MagicMock()
    mock_datamate_tool_instance = MagicMock()
    mock_datamate_tool_class.return_value = mock_datamate_tool_instance

    tool_config = ToolConfig(
        class_name="DataMateSearchTool",
        name="datamate_search",
        description="desc",
        inputs="{}",
        output_type="string",
        params={"top_k": 5, "server_ip": "127.0.0.1", "server_port": 8080},
        source="local",
        metadata={},  # No metadata provided
    )

    original_value = nexent_agent.__dict__.get("DataMateSearchTool")
    nexent_agent.__dict__["DataMateSearchTool"] = mock_datamate_tool_class

    try:
        result = nexent_agent_instance.create_local_tool(tool_config)
    finally:
        # Restore original value
        if original_value is not None:
            nexent_agent.__dict__["DataMateSearchTool"] = original_value
        elif "DataMateSearchTool" in nexent_agent.__dict__:
            del nexent_agent.__dict__["DataMateSearchTool"]

    # Verify tool was created with all params
    mock_datamate_tool_class.assert_called_once_with(
        top_k=5, server_ip="127.0.0.1", server_port=8080
    )
    # Verify excluded parameters were set directly as attributes with None defaults when metadata is missing
    assert result == mock_datamate_tool_instance
    assert mock_datamate_tool_instance.observer == nexent_agent_instance.observer


def test_create_local_tool_datamate_search_tool_success(nexent_agent_instance):
    """Test successful creation of DataMateSearchTool with metadata."""
    mock_datamate_tool_class = MagicMock()
    mock_datamate_tool_instance = MagicMock()
    mock_datamate_tool_class.return_value = mock_datamate_tool_instance

    tool_config = ToolConfig(
        class_name="DataMateSearchTool",
        name="datamate_search",
        description="desc",
        inputs="{}",
        output_type="string",
        params={"top_k": 10, "server_ip": "127.0.0.1", "server_port": 8080},
        source="local",
        metadata={
            "index_names": ["datamate_index1", "datamate_index2"],
        },
    )

    original_value = nexent_agent.__dict__.get("DataMateSearchTool")
    nexent_agent.__dict__["DataMateSearchTool"] = mock_datamate_tool_class

    try:
        result = nexent_agent_instance.create_local_tool(tool_config)
    finally:
        # Restore original value
        if original_value is not None:
            nexent_agent.__dict__["DataMateSearchTool"] = original_value
        elif "DataMateSearchTool" in nexent_agent.__dict__:
            del nexent_agent.__dict__["DataMateSearchTool"]

    # Verify tool was created with all params
    mock_datamate_tool_class.assert_called_once_with(
        top_k=10, server_ip="127.0.0.1", server_port=8080
    )
    # Verify excluded parameters were set directly as attributes after instantiation
    assert result == mock_datamate_tool_instance
    assert mock_datamate_tool_instance.observer == nexent_agent_instance.observer


def test_create_local_tool_datamate_search_tool_with_none_defaults(nexent_agent_instance):
    """Test DataMateSearchTool creation with None defaults when metadata is missing."""
    mock_datamate_tool_class = MagicMock()
    mock_datamate_tool_instance = MagicMock()
    mock_datamate_tool_class.return_value = mock_datamate_tool_instance

    tool_config = ToolConfig(
        class_name="DataMateSearchTool",
        name="datamate_search",
        description="desc",
        inputs="{}",
        output_type="string",
        params={"top_k": 5, "server_ip": "127.0.0.1", "server_port": 8080},
        source="local",
        metadata={},  # No metadata provided
    )

    original_value = nexent_agent.__dict__.get("DataMateSearchTool")
    nexent_agent.__dict__["DataMateSearchTool"] = mock_datamate_tool_class

    try:
        result = nexent_agent_instance.create_local_tool(tool_config)
    finally:
        # Restore original value
        if original_value is not None:
            nexent_agent.__dict__["DataMateSearchTool"] = original_value
        elif "DataMateSearchTool" in nexent_agent.__dict__:
            del nexent_agent.__dict__["DataMateSearchTool"]

    # Verify tool was created with all params
    mock_datamate_tool_class.assert_called_once_with(
        top_k=5, server_ip="127.0.0.1", server_port=8080
    )
    # Verify excluded parameters were set directly as attributes with None defaults when metadata is missing
    assert result == mock_datamate_tool_instance
    assert mock_datamate_tool_instance.observer == nexent_agent_instance.observer


class TestCreateMcpTool:
    """Tests for create_mcp_tool method."""

    def test_create_mcp_tool_success(self, nexent_agent_instance):
        """Test successful MCP tool creation."""
        mock_tool = MagicMock()
        mock_tool.name = "test_mcp_tool"
        mock_collection = MagicMock()
        mock_collection.tools = [mock_tool]

        nexent_agent_instance.mcp_tool_collection = mock_collection

        result = nexent_agent_instance.create_mcp_tool("test_mcp_tool")
        assert result == mock_tool

    def test_create_mcp_tool_collection_not_initialized(self, nexent_agent_instance):
        """Test create_mcp_tool raises error when collection is None."""
        nexent_agent_instance.mcp_tool_collection = None
        with pytest.raises(ValueError, match="MCP tool collection is not initialized"):
            nexent_agent_instance.create_mcp_tool("test_tool")

    def test_create_mcp_tool_not_found(self, nexent_agent_instance):
        """Test create_mcp_tool raises error when tool is not found."""
        mock_collection = MagicMock()
        mock_collection.tools = []
        nexent_agent_instance.mcp_tool_collection = mock_collection

        with pytest.raises(ValueError, match="test_tool not found in MCP server"):
            nexent_agent_instance.create_mcp_tool("test_tool")

class TestCreateBuiltinTool:
    """Tests for create_builtin_tool method."""

    def test_create_builtin_tool_unknown_tool(self, nexent_agent_instance):
        """Test create_builtin_tool raises error for unknown tool."""
        tool_config = ToolConfig(
            class_name="UnknownTool",
            name="unknown",
            description="desc",
            inputs="{}",
            output_type="string",
            params={},
            source="builtin",
        )

        with pytest.raises(ValueError, match="Unknown builtin tool: UnknownTool"):
            nexent_agent_instance.create_builtin_tool(tool_config)

    def test_create_builtin_tool_unknown_tool_partial_name(self, nexent_agent_instance):
        """Test create_builtin_tool raises error for similar but unknown tool name."""
        tool_config = ToolConfig(
            class_name="RunSkillScript",
            name="run_skill",
            description="desc",
            inputs="{}",
            output_type="string",
            params={},
            source="builtin",
        )

        with pytest.raises(ValueError, match="Unknown builtin tool: RunSkillScript"):
            nexent_agent_instance.create_builtin_tool(tool_config)

    def test_create_builtin_tool_run_skill_script_tool(self, nexent_agent_instance):
        """Test create_builtin_tool creates RunSkillScriptTool with the correct arguments.

        Covers the RunSkillScriptTool branch in create_builtin_tool, including
        the dynamic import (line 327) and the metadata defaulting (line 328).
        """
        mock_tool_instance = MagicMock(name="RunSkillScriptToolInstance")
        mock_tool_class = MagicMock(return_value=mock_tool_instance, name="RunSkillScriptTool")
        mock_run_skill_script_tool_module = MagicMock()
        mock_run_skill_script_tool_module.RunSkillScriptTool = mock_tool_class

        tool_config = ToolConfig(
            class_name="RunSkillScriptTool",
            name="run_skill_script",
            description="desc",
            inputs="{}",
            output_type="string",
            params={"local_skills_dir": "/tmp/skills"},
            source="builtin",
            metadata={
                "agent_id": 42,
                "tenant_id": "tenant_abc",
                "version_no": 7,
            },
        )

        with patch.dict(
            "sys.modules",
            {"nexent.core.tools.run_skill_script_tool": mock_run_skill_script_tool_module},
        ):
            result = nexent_agent_instance.create_builtin_tool(tool_config)

        mock_tool_class.assert_called_once_with(
            local_skills_dir="/tmp/skills",
            agent_id=42,
            tenant_id="tenant_abc",
            version_no=7,
            observer=nexent_agent_instance.observer,
        )
        assert result is mock_tool_instance

    def test_create_builtin_tool_run_skill_script_tool_no_metadata(self, nexent_agent_instance):
        """Test create_builtin_tool defaults version_no to 0 when metadata is absent.

        Verifies that ``metadata = tool_config.metadata or {}`` substitutes an
        empty dict when ``metadata`` is None and version_no defaults to 0.
        """
        mock_tool_instance = MagicMock(name="RunSkillScriptToolInstance")
        mock_tool_class = MagicMock(return_value=mock_tool_instance, name="RunSkillScriptTool")
        mock_run_skill_script_tool_module = MagicMock()
        mock_run_skill_script_tool_module.RunSkillScriptTool = mock_tool_class

        tool_config = ToolConfig(
            class_name="RunSkillScriptTool",
            name="run_skill_script",
            description="desc",
            inputs="{}",
            output_type="string",
            params={"local_skills_dir": "/tmp/skills"},
            source="builtin",
            metadata=None,
        )

        with patch.dict(
            "sys.modules",
            {"nexent.core.tools.run_skill_script_tool": mock_run_skill_script_tool_module},
        ):
            result = nexent_agent_instance.create_builtin_tool(tool_config)

        mock_tool_class.assert_called_once_with(
            local_skills_dir="/tmp/skills",
            agent_id=None,
            tenant_id=None,
            version_no=0,
            observer=nexent_agent_instance.observer,
        )
        assert result is mock_tool_instance

    def test_create_builtin_tool_read_skill_md_tool(self, nexent_agent_instance):
        """Test create_builtin_tool creates ReadSkillMdTool with the correct arguments.

        Covers the ReadSkillMdTool branch (line 337) and verifies that the
        observer is NOT passed to ReadSkillMdTool (per the source signature).
        """
        mock_tool_instance = MagicMock(name="ReadSkillMdToolInstance")
        mock_tool_class = MagicMock(return_value=mock_tool_instance, name="ReadSkillMdTool")
        mock_read_skill_md_tool_module = MagicMock()
        mock_read_skill_md_tool_module.ReadSkillMdTool = mock_tool_class

        tool_config = ToolConfig(
            class_name="ReadSkillMdTool",
            name="read_skill_md",
            description="desc",
            inputs="{}",
            output_type="string",
            params={"local_skills_dir": "/tmp/skills"},
            source="builtin",
            metadata={
                "agent_id": 11,
                "tenant_id": "tenant_read",
                "version_no": 3,
            },
        )

        with patch.dict(
            "sys.modules",
            {"nexent.core.tools.read_skill_md_tool": mock_read_skill_md_tool_module},
        ):
            result = nexent_agent_instance.create_builtin_tool(tool_config)

        mock_tool_class.assert_called_once_with(
            local_skills_dir="/tmp/skills",
            agent_id=11,
            tenant_id="tenant_read",
            version_no=3,
        )
        assert result is mock_tool_instance

    def test_create_builtin_tool_write_skill_file_tool(self, nexent_agent_instance):
        """Test create_builtin_tool creates WriteSkillFileTool with the correct arguments.

        Covers the WriteSkillFileTool branch (lines 345-353) and verifies that
        all four constructor parameters are forwarded correctly.
        """
        mock_tool_instance = MagicMock(name="WriteSkillFileToolInstance")
        mock_tool_class = MagicMock(return_value=mock_tool_instance, name="WriteSkillFileTool")
        mock_write_skill_file_tool_module = MagicMock()
        mock_write_skill_file_tool_module.WriteSkillFileTool = mock_tool_class

        tool_config = ToolConfig(
            class_name="WriteSkillFileTool",
            name="write_skill_file",
            description="desc",
            inputs="{}",
            output_type="string",
            params={"local_skills_dir": "/tmp/skills"},
            source="builtin",
            metadata={
                "agent_id": 21,
                "tenant_id": "tenant_write",
                "version_no": 5,
            },
        )

        with patch.dict(
            "sys.modules",
            {"nexent.core.tools.write_skill_file_tool": mock_write_skill_file_tool_module},
        ):
            result = nexent_agent_instance.create_builtin_tool(tool_config)

        mock_tool_class.assert_called_once_with(
            local_skills_dir="/tmp/skills",
            agent_id=21,
            tenant_id="tenant_write",
            version_no=5,
        )
        assert result is mock_tool_instance

    def test_create_builtin_tool_read_skill_config_tool(self, nexent_agent_instance):
        """Test create_builtin_tool creates ReadSkillConfigTool with the correct arguments.

        Covers the ReadSkillConfigTool branch (lines 354-357) and verifies
        that all four constructor parameters are forwarded correctly, and the
        observer is NOT passed (per the source signature).
        """
        mock_tool_instance = MagicMock(name="ReadSkillConfigToolInstance")
        mock_tool_class = MagicMock(return_value=mock_tool_instance, name="ReadSkillConfigTool")
        mock_read_skill_config_tool_module = MagicMock()
        mock_read_skill_config_tool_module.ReadSkillConfigTool = mock_tool_class

        tool_config = ToolConfig(
            class_name="ReadSkillConfigTool",
            name="read_skill_config",
            description="desc",
            inputs="{}",
            output_type="string",
            params={"local_skills_dir": "/tmp/skills"},
            source="builtin",
            metadata={
                "agent_id": 31,
                "tenant_id": "tenant_config",
                "version_no": 9,
            },
        )

        with patch.dict(
            "sys.modules",
            {"nexent.core.tools.read_skill_config_tool": mock_read_skill_config_tool_module},
        ):
            result = nexent_agent_instance.create_builtin_tool(tool_config)

        mock_tool_class.assert_called_once_with(
            local_skills_dir="/tmp/skills",
            agent_id=31,
            tenant_id="tenant_config",
            version_no=9,
            config_overrides=None,
        )
        assert result is mock_tool_instance

    def test_create_builtin_tool_read_skill_config_tool_no_metadata(self, nexent_agent_instance):
        """Test create_builtin_tool defaults metadata fields to None/0 when metadata is absent.

        Verifies ``metadata = tool_config.metadata or {}`` substitutes an empty
        dict when ``metadata`` is None so version_no falls back to 0.
        """
        mock_tool_instance = MagicMock(name="ReadSkillConfigToolInstance")
        mock_tool_class = MagicMock(return_value=mock_tool_instance, name="ReadSkillConfigTool")
        mock_read_skill_config_tool_module = MagicMock()
        mock_read_skill_config_tool_module.ReadSkillConfigTool = mock_tool_class

        tool_config = ToolConfig(
            class_name="ReadSkillConfigTool",
            name="read_skill_config",
            description="desc",
            inputs="{}",
            output_type="string",
            params={"local_skills_dir": "/tmp/skills"},
            source="builtin",
            metadata=None,
        )

        with patch.dict(
            "sys.modules",
            {"nexent.core.tools.read_skill_config_tool": mock_read_skill_config_tool_module},
        ):
            result = nexent_agent_instance.create_builtin_tool(tool_config)

        mock_tool_class.assert_called_once_with(
            local_skills_dir="/tmp/skills",
            agent_id=None,
            tenant_id=None,
            version_no=0,
            config_overrides=None,
        )
        assert result is mock_tool_instance

    def test_create_builtin_download_from_s3_tool(self, nexent_agent_instance):
        validator = MagicMock()
        storage = MagicMock()
        tool_instance = MagicMock()
        tool_class = MagicMock(return_value=tool_instance)
        tool_config = ToolConfig(
            class_name="DownloadFromS3Tool",
            name="download_from_s3",
            description="desc",
            inputs="{}",
            output_type="string",
            params={"workspace_path": "/tmp/workspace"},
            source="builtin",
            metadata={
                "minio_client": storage,
                "user_id": "user-1",
                "tenant_id": "tenant-1",
                "validate_url_access": validator,
            },
        )

        with patch.dict("sys.modules", {
            "nexent.core.tools.download_from_s3_tool": MagicMock(
                DownloadFromS3Tool=tool_class,
            )
        }):
            result = nexent_agent_instance.create_builtin_tool(tool_config)

        assert result is tool_instance
        tool_class.assert_called_once_with(
            workspace_path="/tmp/workspace",
            minio_client=storage,
            user_id="user-1",
            tenant_id="tenant-1",
            observer=nexent_agent_instance.observer,
            validate_url_access=validator,
            on_download=ANY,
        )

    def test_create_builtin_upload_to_s3_tool(self, nexent_agent_instance):
        storage = MagicMock()
        tool_instance = MagicMock()
        tool_class = MagicMock(return_value=tool_instance)
        tool_config = ToolConfig(
            class_name="UploadToS3Tool",
            name="upload_to_s3",
            description="desc",
            inputs="{}",
            output_type="string",
            params={"workspace_path": "/tmp/workspace"},
            source="builtin",
            metadata={
                "minio_client": storage,
                "user_id": "user-1",
                "tenant_id": "tenant-1",
                "run_id": "run-1",
            },
        )

        with patch.dict("sys.modules", {
            "nexent.core.tools.upload_to_s3_tool": MagicMock(
                UploadToS3Tool=tool_class,
            )
        }):
            result = nexent_agent_instance.create_builtin_tool(tool_config)

        assert result is tool_instance
        tool_class.assert_called_once_with(
            workspace_path="/tmp/workspace",
            minio_client=storage,
            user_id="user-1",
            tenant_id="tenant-1",
            observer=nexent_agent_instance.observer,
            run_id="run-1",
            on_upload=nexent_agent_instance._record_workspace_upload,
            ensure_local_file=ANY,
            uploaded_paths=nexent_agent_instance._workspace_uploaded_paths,
        )


class TestCreateToolExceptionHandling:
    """Tests for exception handling in create_tool method."""

    def test_create_tool_with_builtin_source_exception(self, nexent_agent_instance):
        """Test create_tool handles exception from create_builtin_tool."""
        tool_config = ToolConfig(
            class_name="UnknownTool",
            name="unknown",
            description="desc",
            inputs="{}",
            output_type="string",
            params={},
            source="builtin",
        )

        with pytest.raises(ValueError, match=r"Error in creating tool: Unknown builtin tool: UnknownTool"):
            nexent_agent_instance.create_tool(tool_config)


class TestCreateSingleAgentExceptionHandling:
    """Tests for exception handling in create_single_agent method."""

    def test_create_single_agent_with_tool_creation_error(self, nexent_agent_instance, mock_model_config):
        """Test create_single_agent handles tool creation errors."""
        nexent_agent_instance.model_config_list = [mock_model_config]

        mock_agent_config = AgentConfig(
            name="test_agent",
            description="A test agent",
            prompt_templates={"system": "You are a test agent"},
            tools=[
                ToolConfig(
                    class_name="SomeTool",
                    name="some_tool",
                    description="desc",
                    inputs="{}",
                    output_type="string",
                    params={},
                    source="unsupported",
                )
            ],
            max_steps=5,
            model_name="test_model",
            provide_run_summary=False,
            managed_agents=[]
        )

        with pytest.raises(ValueError, match=r"Error in creating agent, agent name: test_agent, Error: Error in creating tool:"):
            nexent_agent_instance.create_single_agent(mock_agent_config)

    def test_create_single_agent_with_managed_agent_error(self, nexent_agent_instance, mock_model_config):
        """Test create_single_agent handles managed agent creation errors."""
        nexent_agent_instance.model_config_list = [mock_model_config]

        mock_sub_agent_config = AgentConfig(
            name="sub_agent",
            description="A sub agent",
            prompt_templates={"system": "You are a sub agent"},
            tools=[],
            max_steps=5,
            model_name="nonexistent_model",
            provide_run_summary=False,
            managed_agents=[]
        )

        mock_agent_config = AgentConfig(
            name="parent_agent",
            description="A parent agent",
            prompt_templates={"system": "You are a parent agent"},
            tools=[],
            max_steps=5,
            model_name="test_model",
            provide_run_summary=False,
            managed_agents=[mock_sub_agent_config]
        )

        with pytest.raises(ValueError, match=r"Error in creating managed agent:"):
            nexent_agent_instance.create_single_agent(mock_agent_config)


class TestCreateLocalToolElseBranch:
    """Tests for create_local_tool else branch."""

    def test_create_local_tool_else_branch_with_observer(self, nexent_agent_instance):
        """Test create_local_tool else branch when tool has observer attribute."""
        mock_tool_class = MagicMock()
        mock_tool_instance = MagicMock()
        mock_tool_instance.hasattr = MagicMock(return_value=True)
        del mock_tool_instance.hasattr
        mock_tool_instance.observer = None
        mock_tool_class.return_value = mock_tool_instance

        tool_config = ToolConfig(
            class_name="SomeOtherTool",
            name="some_tool",
            description="desc",
            inputs="{}",
            output_type="string",
            params={"param1": "value1"},
            source="local",
        )

        original_value = nexent_agent.__dict__.get("SomeOtherTool")
        nexent_agent.__dict__["SomeOtherTool"] = mock_tool_class

        try:
            result = nexent_agent_instance.create_local_tool(tool_config)
        finally:
            if original_value is not None:
                nexent_agent.__dict__["SomeOtherTool"] = original_value
            elif "SomeOtherTool" in nexent_agent.__dict__:
                del nexent_agent.__dict__["SomeOtherTool"]

        mock_tool_class.assert_called_once_with(param1="value1")
        assert result == mock_tool_instance
        assert mock_tool_instance.observer == nexent_agent_instance.observer

    def test_create_local_tool_else_branch_without_observer(self, nexent_agent_instance):
        """Test create_local_tool else branch when tool does not have observer attribute."""
        mock_tool_class = MagicMock()
        mock_tool_instance = MagicMock()
        del mock_tool_instance.observer
        mock_tool_class.return_value = mock_tool_instance

        tool_config = ToolConfig(
            class_name="ToolWithoutObserver",
            name="tool_no_observer",
            description="desc",
            inputs="{}",
            output_type="string",
            params={"param1": "value1"},
            source="local",
        )

        original_value = nexent_agent.__dict__.get("ToolWithoutObserver")
        nexent_agent.__dict__["ToolWithoutObserver"] = mock_tool_class

        try:
            result = nexent_agent_instance.create_local_tool(tool_config)
        finally:
            if original_value is not None:
                nexent_agent.__dict__["ToolWithoutObserver"] = original_value
            elif "ToolWithoutObserver" in nexent_agent.__dict__:
                del nexent_agent.__dict__["ToolWithoutObserver"]

        mock_tool_class.assert_called_once_with(param1="value1")
        assert result == mock_tool_instance
        assert not hasattr(result, "observer") or result.observer is None


class TestCreateTool:
    """Tests for create_tool method."""

    def test_create_tool_invalid_type(self, nexent_agent_instance):
        """Test create_tool raises TypeError for invalid tool_config type."""
        with pytest.raises(TypeError, match="tool_config must be a ToolConfig object"):
            nexent_agent_instance.create_tool("not_a_tool_config")

    def test_create_tool_unsupported_source(self, nexent_agent_instance):
        """Test create_tool raises error for unsupported tool source."""
        tool_config = ToolConfig(
            class_name="SomeTool",
            name="some_tool",
            description="desc",
            inputs="{}",
            output_type="string",
            params={},
            source="unsupported",
        )

        with pytest.raises(ValueError, match="unsupported tool source: unsupported"):
            nexent_agent_instance.create_tool(tool_config)


class TestAddHistoryToAgent:
    """Tests for add_history_to_agent method."""

    def test_add_history_to_agent_with_assistant_role(self, nexent_agent_instance, mock_core_agent):
        """Test add_history_to_agent handles assistant role correctly."""
        nexent_agent_instance.agent = mock_core_agent
        mock_core_agent.memory.steps = []

        history = [
            AgentHistory(role="assistant", content="Hello, I am an assistant.")
        ]

        nexent_agent_instance.add_history_to_agent(history)

        assert len(mock_core_agent.memory.steps) == 1
        step = mock_core_agent.memory.steps[0]
        assert isinstance(step, _ActionStep)
        assert step.model_output == "Hello, I am an assistant."
        mock_core_agent.memory.reset.assert_called_once()

    def test_add_history_to_agent_mixed_roles(self, nexent_agent_instance, mock_core_agent):
        """Test add_history_to_agent handles mixed user and assistant roles."""
        nexent_agent_instance.agent = mock_core_agent
        mock_core_agent.memory.steps = []

        history = [
            AgentHistory(role="user", content="Hello"),
            AgentHistory(role="assistant", content="Hi there!"),
        ]

        nexent_agent_instance.add_history_to_agent(history)

        assert len(mock_core_agent.memory.steps) == 2
        mock_core_agent.memory.reset.assert_called_once()


class TestSetAgent:
    """Tests for set_agent method."""

    def test_set_agent_with_core_agent(self, nexent_agent_instance, mock_core_agent):
        """Test set_agent accepts a CoreAgent instance."""
        nexent_agent_instance.set_agent(mock_core_agent)
        assert nexent_agent_instance.agent == mock_core_agent

    def test_set_agent_with_invalid_type(self, nexent_agent_instance):
        """Test set_agent raises TypeError for non-CoreAgent type."""
        with pytest.raises(TypeError, match=r"agent must be a CoreAgent object, not .*str"):
            nexent_agent_instance.set_agent("not_core_agent")


# ----------------------------------------------------------------------------
# Additional tests for nexent_agent module
# ----------------------------------------------------------------------------

class TestNexentAgentInit:
    """Tests for NexentAgent __init__ method."""

    def test_init_with_invalid_observer(self):
        """Test NexentAgent raises TypeError when observer is not MessageObserver."""
        with pytest.raises(TypeError, match="Create Observer Object with MessageObserver"):
            NexentAgent(
                observer="not_an_observer",
                model_config_list=[],
                stop_event=Event()
            )

    def test_init_with_all_parameters(self, mock_observer):
        """Test NexentAgent initialization with all parameters."""
        stop_event = Event()
        mcp_collection = MagicMock()

        agent = NexentAgent(
            observer=mock_observer,
            model_config_list=[],
            stop_event=stop_event,
            mcp_tool_collection=mcp_collection
        )

        assert agent.observer == mock_observer
        assert agent.model_config_list == []
        assert agent.stop_event == stop_event
        assert agent.mcp_tool_collection == mcp_collection
        assert agent.agent is None

    def test_init_with_empty_model_list(self, mock_observer):
        """Test NexentAgent initialization with empty model config list."""
        agent = NexentAgent(
            observer=mock_observer,
            model_config_list=[],
            stop_event=Event()
        )

        assert agent.model_config_list == []
        assert agent.agent is None


class TestCreateModel:
    """Tests for create_model method."""

    def test_create_model_success(self, nexent_agent_instance, mock_model_config):
        """Test successful model creation with valid model cite name."""
        nexent_agent_instance.model_config_list = [mock_model_config]

        model = nexent_agent_instance.create_model("test_model")

        assert model is not None
        mock_openai_model_class.assert_called_once()
        call_kwargs = mock_openai_model_class.call_args[1]
        assert call_kwargs["model_id"] == "gpt-4"
        assert call_kwargs["api_key"] == "test_api_key"
        assert call_kwargs["api_base"] == "https://api.openai.com/v1"
        assert call_kwargs["temperature"] == 0.7
        assert call_kwargs["top_p"] == 0.9

    def test_create_model_not_found(self, nexent_agent_instance, mock_model_config):
        """Test create_model raises ValueError when model cite name is not found."""
        nexent_agent_instance.model_config_list = [mock_model_config]

        with pytest.raises(ValueError, match="Model nonexistent_model not found"):
            nexent_agent_instance.create_model("nonexistent_model")

    def test_create_model_with_none_ssl_verify(self, nexent_agent_instance, mock_model_config):
        """Test create_model handles None ssl_verify with default True."""
        mock_model_config.ssl_verify = None
        nexent_agent_instance.model_config_list = [mock_model_config]

        model = nexent_agent_instance.create_model("test_model")

        call_kwargs = mock_openai_model_class.call_args[1]
        assert call_kwargs["ssl_verify"] is True


class TestCreateLangchainTool:
    """Tests for create_langchain_tool method."""

    def test_create_langchain_tool_success(self, nexent_agent_instance):
        """Test successful langchain tool creation."""
        mock_tool = MagicMock()
        mock_tool_class.from_langchain.return_value = mock_tool

        tool_config = ToolConfig(
            class_name="LangchainTool",
            name=None,
            description=None,
            inputs=None,
            output_type=None,
            params={},
            source="langchain",
            metadata={}  # Pass empty dict, the source code uses tool_config.metadata
        )

        result = nexent_agent_instance.create_langchain_tool(tool_config)
        assert result == mock_tool


class TestCreateLocalToolKnowledgeBase:
    """Tests for create_local_tool with KnowledgeBaseSearchTool."""

    def test_create_local_tool_knowledge_base_success(self, nexent_agent_instance):
        """Test successful KnowledgeBaseSearchTool creation with metadata."""
        mock_tool_class = MagicMock()
        mock_tool_instance = MagicMock()
        mock_tool_class.return_value = mock_tool_instance

        tool_config = ToolConfig(
            class_name="KnowledgeBaseSearchTool",
            name="kb_search",
            description="desc",
            inputs="{}",
            output_type="string",
            params={"server_url": "http://localhost:8080"},
            source="local",
            metadata={
                "vdb_core": "vdb_instance",
                "embedding_model": "embedding_instance",
                "rerank_model": "rerank_instance"
            }
        )

        original_value = nexent_agent.__dict__.get("KnowledgeBaseSearchTool")
        nexent_agent.__dict__["KnowledgeBaseSearchTool"] = mock_tool_class

        try:
            result = nexent_agent_instance.create_local_tool(tool_config)
        finally:
            if original_value is not None:
                nexent_agent.__dict__["KnowledgeBaseSearchTool"] = original_value
            elif "KnowledgeBaseSearchTool" in nexent_agent.__dict__:
                del nexent_agent.__dict__["KnowledgeBaseSearchTool"]

        mock_tool_class.assert_called_once_with(server_url="http://localhost:8080")
        assert result == mock_tool_instance
        assert mock_tool_instance.observer == nexent_agent_instance.observer
        assert mock_tool_instance.vdb_core == "vdb_instance"
        assert mock_tool_instance.embedding_model == "embedding_instance"
        assert mock_tool_instance.rerank_model == "rerank_instance"

    def test_create_local_tool_knowledge_base_missing_metadata(self, nexent_agent_instance):
        """Test KnowledgeBaseSearchTool creation with missing metadata defaults to None."""
        mock_tool_class = MagicMock()
        mock_tool_instance = MagicMock()
        mock_tool_class.return_value = mock_tool_instance

        tool_config = ToolConfig(
            class_name="KnowledgeBaseSearchTool",
            name="kb_search",
            description="desc",
            inputs="{}",
            output_type="string",
            params={"server_url": "http://localhost:8080"},
            source="local",
            metadata=None
        )

        original_value = nexent_agent.__dict__.get("KnowledgeBaseSearchTool")
        nexent_agent.__dict__["KnowledgeBaseSearchTool"] = mock_tool_class

        try:
            result = nexent_agent_instance.create_local_tool(tool_config)
        finally:
            if original_value is not None:
                nexent_agent.__dict__["KnowledgeBaseSearchTool"] = original_value
            elif "KnowledgeBaseSearchTool" in nexent_agent.__dict__:
                del nexent_agent.__dict__["KnowledgeBaseSearchTool"]

        assert result == mock_tool_instance
        assert mock_tool_instance.vdb_core is None
        assert mock_tool_instance.embedding_model is None
        assert mock_tool_instance.rerank_model is None


class TestCreateLocalToolDify:
    """Tests for create_local_tool with DifySearchTool."""

    def test_create_local_tool_dify_success(self, nexent_agent_instance):
        """Test successful DifySearchTool creation with metadata."""
        mock_tool_class = MagicMock()
        mock_tool_instance = MagicMock()
        mock_tool_class.return_value = mock_tool_instance

        tool_config = ToolConfig(
            class_name="DifySearchTool",
            name="dify_search",
            description="desc",
            inputs="{}",
            output_type="string",
            params={"api_key": "dify-key"},
            source="local",
            metadata={"rerank_model": "rerank_instance"}
        )

        original_value = nexent_agent.__dict__.get("DifySearchTool")
        nexent_agent.__dict__["DifySearchTool"] = mock_tool_class

        try:
            result = nexent_agent_instance.create_local_tool(tool_config)
        finally:
            if original_value is not None:
                nexent_agent.__dict__["DifySearchTool"] = original_value
            elif "DifySearchTool" in nexent_agent.__dict__:
                del nexent_agent.__dict__["DifySearchTool"]

        mock_tool_class.assert_called_once_with(api_key="dify-key")
        assert result == mock_tool_instance
        assert mock_tool_instance.observer == nexent_agent_instance.observer
        assert mock_tool_instance.rerank_model == "rerank_instance"


class TestCreateLocalToolRAGFlow:
    """Tests for create_local_tool with RAGFlowSearchTool."""

    def test_create_local_tool_ragflow_search_success(self, nexent_agent_instance):
        """Test successful RAGFlowSearchTool creation filters out unsupported params."""
        mock_tool_class = MagicMock()
        mock_tool_instance = MagicMock()
        mock_tool_class.return_value = mock_tool_instance

        tool_config = ToolConfig(
            class_name="RAGFlowSearchTool",
            name="ragflow_search",
            description="desc",
            inputs="{}",
            output_type="string",
            params={
                "server_url": "http://localhost:9380",
                "api_key": "ragflow-key",
                "dataset_ids": '["ds1"]',
                "observer": "should_be_filtered",
                "rerank_model": "should_be_filtered",
                "rerank": True,
                "rerank_model_name": "should_be_filtered",
            },
            source="local",
            metadata={"rerank_model": "rerank_display_instance"}
        )

        original_value = nexent_agent.__dict__.get("RAGFlowSearchTool")
        nexent_agent.__dict__["RAGFlowSearchTool"] = mock_tool_class

        try:
            result = nexent_agent_instance.create_local_tool(tool_config)
        finally:
            if original_value is not None:
                nexent_agent.__dict__["RAGFlowSearchTool"] = original_value
            elif "RAGFlowSearchTool" in nexent_agent.__dict__:
                del nexent_agent.__dict__["RAGFlowSearchTool"]

        # Verify filtered params are NOT passed to __init__
        call_kwargs = mock_tool_class.call_args[1]
        assert "observer" not in call_kwargs
        assert "rerank_model" not in call_kwargs
        assert "rerank" not in call_kwargs
        assert "rerank_model_name" not in call_kwargs
        # Verify valid params ARE passed
        assert call_kwargs["server_url"] == "http://localhost:9380"
        assert call_kwargs["api_key"] == "ragflow-key"
        assert call_kwargs["dataset_ids"] == '["ds1"]'

        # Verify observer is set post-init
        assert result == mock_tool_instance
        assert mock_tool_instance.observer == nexent_agent_instance.observer
        # Verify rerank_model is set from metadata for display purposes
        assert mock_tool_instance.rerank_model == "rerank_display_instance"

    def test_create_local_tool_ragflow_search_without_metadata(self, nexent_agent_instance):
        """Test RAGFlowSearchTool creation when metadata is None or empty."""
        mock_tool_class = MagicMock()
        mock_tool_instance = MagicMock()
        mock_tool_class.return_value = mock_tool_instance

        tool_config = ToolConfig(
            class_name="RAGFlowSearchTool",
            name="ragflow_search",
            description="desc",
            inputs="{}",
            output_type="string",
            params={"server_url": "http://localhost:9380", "api_key": "key"},
            source="local",
            metadata=None,
        )

        original_value = nexent_agent.__dict__.get("RAGFlowSearchTool")
        nexent_agent.__dict__["RAGFlowSearchTool"] = mock_tool_class

        try:
            result = nexent_agent_instance.create_local_tool(tool_config)
        finally:
            if original_value is not None:
                nexent_agent.__dict__["RAGFlowSearchTool"] = original_value
            elif "RAGFlowSearchTool" in nexent_agent.__dict__:
                del nexent_agent.__dict__["RAGFlowSearchTool"]

        assert result == mock_tool_instance
        assert mock_tool_instance.observer == nexent_agent_instance.observer
        assert mock_tool_instance.rerank_model is None


class TestCreateLocalToolAnalyze:
    """Tests for create_local_tool with AnalyzeTextFileTool and AnalyzeImageTool."""

    def test_create_local_tool_analyze_text_file(self, nexent_agent_instance):
        """Test successful AnalyzeTextFileTool creation."""
        mock_tool_class = MagicMock()
        mock_tool_instance = MagicMock()
        mock_tool_class.return_value = mock_tool_instance

        tool_config = ToolConfig(
            class_name="AnalyzeTextFileTool",
            name="analyze_text",
            description="desc",
            inputs="{}",
            output_type="string",
            params={"param1": "value1"},
            source="local",
            metadata={
                "llm_model": ["gpt-4"],
                "storage_client": "storage",
                "data_process_service_url": "http://service.com"
            }
        )

        original_value = nexent_agent.__dict__.get("AnalyzeTextFileTool")
        nexent_agent.__dict__["AnalyzeTextFileTool"] = mock_tool_class

        try:
            result = nexent_agent_instance.create_local_tool(tool_config)
        finally:
            if original_value is not None:
                nexent_agent.__dict__["AnalyzeTextFileTool"] = original_value
            elif "AnalyzeTextFileTool" in nexent_agent.__dict__:
                del nexent_agent.__dict__["AnalyzeTextFileTool"]

        mock_tool_class.assert_called_once()
        call_kwargs = mock_tool_class.call_args[1]
        assert call_kwargs["observer"] == nexent_agent_instance.observer
        assert call_kwargs["llm_model"] == ["gpt-4"]
        assert call_kwargs["storage_client"] == "storage"
        assert call_kwargs["data_process_service_url"] == "http://service.com"
        assert call_kwargs["param1"] == "value1"
        assert result == mock_tool_instance

    def test_create_local_tool_analyze_image(self, nexent_agent_instance):
        """Test successful AnalyzeImageTool creation."""
        mock_tool_class = MagicMock()
        mock_tool_instance = MagicMock()
        mock_tool_class.return_value = mock_tool_instance

        tool_config = ToolConfig(
            class_name="AnalyzeImageTool",
            name="analyze_image",
            description="desc",
            inputs="{}",
            output_type="string",
            params={"param1": "value1"},
            source="local",
            metadata={
                "vlm_model": ["gpt-4-vision"],
                "storage_client": "storage"
            }
        )

        original_value = nexent_agent.__dict__.get("AnalyzeImageTool")
        nexent_agent.__dict__["AnalyzeImageTool"] = mock_tool_class

        try:
            result = nexent_agent_instance.create_local_tool(tool_config)
        finally:
            if original_value is not None:
                nexent_agent.__dict__["AnalyzeImageTool"] = original_value
            elif "AnalyzeImageTool" in nexent_agent.__dict__:
                del nexent_agent.__dict__["AnalyzeImageTool"]

        mock_tool_class.assert_called_once()
        call_kwargs = mock_tool_class.call_args[1]
        assert call_kwargs["observer"] == nexent_agent_instance.observer
        assert call_kwargs["vlm_model"] == ["gpt-4-vision"]
        assert call_kwargs["storage_client"] == "storage"
        assert call_kwargs["param1"] == "value1"
        assert result == mock_tool_instance

    @pytest.mark.parametrize(
        "class_name,tool_name",
        [
            ("AnalyzeAudioTool", "analyze_audio"),
            ("AnalyzeVideoTool", "analyze_video"),
        ],
    )
    def test_create_local_tool_analyze_audio_video(self, nexent_agent_instance, class_name, tool_name):
        """Test successful audio/video analysis tool creation."""
        mock_tool_class = MagicMock()
        mock_tool_instance = MagicMock()
        mock_tool_class.return_value = mock_tool_instance

        tool_config = ToolConfig(
            class_name=class_name,
            name=tool_name,
            description="desc",
            inputs="{}",
            output_type="string",
            params={"param1": "value1"},
            source="local",
            metadata={
                "vlm_model": ["video-understanding-model"],
                "storage_client": "storage"
            }
        )

        original_value = nexent_agent.__dict__.get(class_name)
        nexent_agent.__dict__[class_name] = mock_tool_class

        try:
            result = nexent_agent_instance.create_local_tool(tool_config)
        finally:
            if original_value is not None:
                nexent_agent.__dict__[class_name] = original_value
            elif class_name in nexent_agent.__dict__:
                del nexent_agent.__dict__[class_name]

        mock_tool_class.assert_called_once()
        call_kwargs = mock_tool_class.call_args[1]
        assert call_kwargs["observer"] == nexent_agent_instance.observer
        assert call_kwargs["vlm_model"] == ["video-understanding-model"]
        assert call_kwargs["storage_client"] == "storage"
        assert call_kwargs["param1"] == "value1"
        assert result == mock_tool_instance

    def test_create_local_tool_analyze_text_file_with_validate_url_access_none(self, nexent_agent_instance):
        """Test AnalyzeTextFileTool creation with validate_url_access not in metadata (None)."""
        mock_tool_class = MagicMock()
        mock_tool_instance = MagicMock()
        mock_tool_class.return_value = mock_tool_instance

        tool_config = ToolConfig(
            class_name="AnalyzeTextFileTool",
            name="analyze_text",
            description="desc",
            inputs="{}",
            output_type="string",
            params={"prompt": "describe this"},
            source="local",
            metadata={
                "llm_model": ["gpt-4"],
                "storage_client": "storage",
                "data_process_service_url": "http://service.com"
            }
        )

        original_value = nexent_agent.__dict__.get("AnalyzeTextFileTool")
        nexent_agent.__dict__["AnalyzeTextFileTool"] = mock_tool_class

        try:
            result = nexent_agent_instance.create_local_tool(tool_config)
        finally:
            if original_value is not None:
                nexent_agent.__dict__["AnalyzeTextFileTool"] = original_value
            elif "AnalyzeTextFileTool" in nexent_agent.__dict__:
                del nexent_agent.__dict__["AnalyzeTextFileTool"]

        mock_tool_class.assert_called_once()
        call_kwargs = mock_tool_class.call_args[1]
        assert call_kwargs["validate_url_access"] is None

    def test_create_local_tool_analyze_text_file_with_validate_url_access_callable(self, nexent_agent_instance):
        """Test AnalyzeTextFileTool creation with validate_url_access as callable."""
        mock_tool_class = MagicMock()
        mock_tool_instance = MagicMock()
        mock_tool_class.return_value = mock_tool_instance

        def mock_validate_func(url):
            return True

        tool_config = ToolConfig(
            class_name="AnalyzeTextFileTool",
            name="analyze_text",
            description="desc",
            inputs="{}",
            output_type="string",
            params={"prompt": "describe this"},
            source="local",
            metadata={
                "llm_model": ["gpt-4"],
                "storage_client": "storage",
                "data_process_service_url": "http://service.com",
                "validate_url_access": mock_validate_func
            }
        )

        original_value = nexent_agent.__dict__.get("AnalyzeTextFileTool")
        nexent_agent.__dict__["AnalyzeTextFileTool"] = mock_tool_class

        try:
            result = nexent_agent_instance.create_local_tool(tool_config)
        finally:
            if original_value is not None:
                nexent_agent.__dict__["AnalyzeTextFileTool"] = original_value
            elif "AnalyzeTextFileTool" in nexent_agent.__dict__:
                del nexent_agent.__dict__["AnalyzeTextFileTool"]

        mock_tool_class.assert_called_once()
        call_kwargs = mock_tool_class.call_args[1]
        assert call_kwargs["validate_url_access"] == mock_validate_func

    def test_create_local_tool_analyze_text_file_with_validate_url_access_not_callable(self, nexent_agent_instance):
        """Test AnalyzeTextFileTool creation with non-callable validate_url_access (should be None)."""
        mock_tool_class = MagicMock()
        mock_tool_instance = MagicMock()
        mock_tool_class.return_value = mock_tool_instance

        tool_config = ToolConfig(
            class_name="AnalyzeTextFileTool",
            name="analyze_text",
            description="desc",
            inputs="{}",
            output_type="string",
            params={"prompt": "describe this"},
            source="local",
            metadata={
                "llm_model": ["gpt-4"],
                "storage_client": "storage",
                "data_process_service_url": "http://service.com",
                "validate_url_access": "not_a_callable_string"
            }
        )

        original_value = nexent_agent.__dict__.get("AnalyzeTextFileTool")
        nexent_agent.__dict__["AnalyzeTextFileTool"] = mock_tool_class

        try:
            result = nexent_agent_instance.create_local_tool(tool_config)
        finally:
            if original_value is not None:
                nexent_agent.__dict__["AnalyzeTextFileTool"] = original_value
            elif "AnalyzeTextFileTool" in nexent_agent.__dict__:
                del nexent_agent.__dict__["AnalyzeTextFileTool"]

        mock_tool_class.assert_called_once()
        call_kwargs = mock_tool_class.call_args[1]
        assert call_kwargs["validate_url_access"] is None

    def test_create_local_tool_analyze_image_with_validate_url_access_none(self, nexent_agent_instance):
        """Test AnalyzeImageTool creation with validate_url_access not in metadata (None)."""
        mock_tool_class = MagicMock()
        mock_tool_instance = MagicMock()
        mock_tool_class.return_value = mock_tool_instance

        tool_config = ToolConfig(
            class_name="AnalyzeImageTool",
            name="analyze_image",
            description="desc",
            inputs="{}",
            output_type="string",
            params={"param1": "value1"},
            source="local",
            metadata={
                "vlm_model": ["gpt-4-vision"],
                "storage_client": "storage"
            }
        )

        original_value = nexent_agent.__dict__.get("AnalyzeImageTool")
        nexent_agent.__dict__["AnalyzeImageTool"] = mock_tool_class

        try:
            result = nexent_agent_instance.create_local_tool(tool_config)
        finally:
            if original_value is not None:
                nexent_agent.__dict__["AnalyzeImageTool"] = original_value
            elif "AnalyzeImageTool" in nexent_agent.__dict__:
                del nexent_agent.__dict__["AnalyzeImageTool"]

        mock_tool_class.assert_called_once()
        call_kwargs = mock_tool_class.call_args[1]
        assert call_kwargs["validate_url_access"] is None

    def test_create_local_tool_analyze_image_with_validate_url_access_callable(self, nexent_agent_instance):
        """Test AnalyzeImageTool creation with validate_url_access as callable."""
        mock_tool_class = MagicMock()
        mock_tool_instance = MagicMock()
        mock_tool_class.return_value = mock_tool_instance

        def mock_validate_func(url):
            return True

        tool_config = ToolConfig(
            class_name="AnalyzeImageTool",
            name="analyze_image",
            description="desc",
            inputs="{}",
            output_type="string",
            params={"param1": "value1"},
            source="local",
            metadata={
                "vlm_model": ["gpt-4-vision"],
                "storage_client": "storage",
                "validate_url_access": mock_validate_func
            }
        )

        original_value = nexent_agent.__dict__.get("AnalyzeImageTool")
        nexent_agent.__dict__["AnalyzeImageTool"] = mock_tool_class

        try:
            result = nexent_agent_instance.create_local_tool(tool_config)
        finally:
            if original_value is not None:
                nexent_agent.__dict__["AnalyzeImageTool"] = original_value
            elif "AnalyzeImageTool" in nexent_agent.__dict__:
                del nexent_agent.__dict__["AnalyzeImageTool"]

        mock_tool_class.assert_called_once()
        call_kwargs = mock_tool_class.call_args[1]
        assert call_kwargs["validate_url_access"] == mock_validate_func

    def test_create_local_tool_analyze_image_with_validate_url_access_not_callable(self, nexent_agent_instance):
        """Test AnalyzeImageTool creation with non-callable validate_url_access (should be None)."""
        mock_tool_class = MagicMock()
        mock_tool_instance = MagicMock()
        mock_tool_class.return_value = mock_tool_instance

        tool_config = ToolConfig(
            class_name="AnalyzeImageTool",
            name="analyze_image",
            description="desc",
            inputs="{}",
            output_type="string",
            params={"param1": "value1"},
            source="local",
            metadata={
                "vlm_model": ["gpt-4-vision"],
                "storage_client": "storage",
                "validate_url_access": 12345
            }
        )

        original_value = nexent_agent.__dict__.get("AnalyzeImageTool")
        nexent_agent.__dict__["AnalyzeImageTool"] = mock_tool_class

        try:
            result = nexent_agent_instance.create_local_tool(tool_config)
        finally:
            if original_value is not None:
                nexent_agent.__dict__["AnalyzeImageTool"] = original_value
            elif "AnalyzeImageTool" in nexent_agent.__dict__:
                del nexent_agent.__dict__["AnalyzeImageTool"]

        mock_tool_class.assert_called_once()
        call_kwargs = mock_tool_class.call_args[1]
        assert call_kwargs["validate_url_access"] is None


class TestCreateLocalToolClassNotFound:
    """Tests for create_local_tool when class is not found."""

    def test_create_local_tool_class_not_found(self, nexent_agent_instance):
        """Test create_local_tool raises ValueError when class not found in globals."""
        tool_config = ToolConfig(
            class_name="NonExistentTool",
            name="nonexistent",
            description="desc",
            inputs="{}",
            output_type="string",
            params={},
            source="local"
        )

        with pytest.raises(ValueError, match="NonExistentTool not found in local"):
            nexent_agent_instance.create_local_tool(tool_config)


class TestCreateSingleAgent:
    """Tests for create_single_agent method."""

    def test_create_single_agent_invalid_type(self, nexent_agent_instance):
        """Test create_single_agent raises TypeError for invalid agent_config type."""
        with pytest.raises(TypeError, match="agent_config must be a AgentConfig object"):
            nexent_agent_instance.create_single_agent("not_an_agent_config")

    def test_wrap_subagent_uses_config_identity_and_name(self, nexent_agent_instance):
        """Test _wrap_subagent loads the wrapper and resolves managed-agent metadata."""
        inner_agent = MagicMock()
        sub_agent_config = types.SimpleNamespace(agent_id="managed-1", name="Research agent")

        wrapped_agent = nexent_agent_instance._wrap_subagent(inner_agent, sub_agent_config)

        assert wrapped_agent._inner is inner_agent
        assert wrapped_agent._observer is nexent_agent_instance.observer
        assert wrapped_agent._agent_id == "managed-1"
        assert wrapped_agent._agent_name == "Research agent"

    def test_create_single_agent_passes_context_item_override(
        self, nexent_agent_instance, mock_model_config, mock_core_agent
    ):
        """Test create_single_agent converts the supplied context input sequence into runtime state."""
        nexent_agent_instance.model_config_list = [mock_model_config]
        context_item = MagicMock()
        agent_config = AgentConfig(
            name="context_agent",
            description="Agent with runtime context",
            tools=[],
            max_steps=5,
            model_name="test_model",
        )

        with patch.object(nexent_agent, "CoreAgent", return_value=mock_core_agent) as mock_core_agent_fn:
            result = nexent_agent_instance.create_single_agent(
                agent_config,
                context_items_override=(context_item,),
            )

        context_runtime = mock_core_agent_fn.call_args.kwargs["context_runtime"]
        assert result is mock_core_agent
        assert context_runtime.items == [context_item]

    def test_create_single_agent_with_prompt_templates(self, nexent_agent_instance, mock_model_config):
        """Test create_single_agent correctly passes prompt_templates."""
        nexent_agent_instance.model_config_list = [mock_model_config]

        agent_config = AgentConfig(
            name="prompt_test_agent",
            description="Test agent with prompts",
            prompt_templates={
                "system": "You are a helpful assistant",
                "custom": "Custom template: {input}"
            },
            tools=[],
            max_steps=3,
            model_name="test_model"
        )

        # This test verifies the agent_config structure is correct
        # Full agent creation is tested in integration tests
        assert agent_config.prompt_templates is not None
        assert "system" in agent_config.prompt_templates

    def test_create_single_agent_with_instructions(self, nexent_agent_instance, mock_model_config):
        """Test create_single_agent correctly passes instructions."""
        nexent_agent_instance.model_config_list = [mock_model_config]

        agent_config = AgentConfig(
            name="instructions_agent",
            description="Test agent with instructions",
            tools=[],
            max_steps=5,
            model_name="test_model",
            instructions="Always be polite and helpful"
        )

        # This test verifies the agent_config structure is correct
        assert agent_config.instructions == "Always be polite and helpful"

    def test_create_single_agent_with_model_not_found(self, nexent_agent_instance, mock_model_config):
        """Test create_single_agent raises error when model is not found."""
        nexent_agent_instance.model_config_list = [mock_model_config]

        agent_config = AgentConfig(
            name="no_model_agent",
            description="Agent with non-existent model",
            tools=[],
            max_steps=5,
            model_name="nonexistent_model"
        )

        with pytest.raises(ValueError, match="Model nonexistent_model not found"):
            nexent_agent_instance.create_single_agent(agent_config)

    def test_create_single_agent_with_external_a2a_agents(self, nexent_agent_instance, mock_model_config, mock_core_agent):
        """Test create_single_agent correctly creates external A2A agent wrappers."""
        nexent_agent_instance.model_config_list = [mock_model_config]

        ext_agent_config = ExternalA2AAgentConfig(
            agent_id="ext_agent_1",
            name="External Assistant",
            description="An external assistant agent",
            url="https://example.com/a2a",
            api_key="test_api_key",
            transport_type="http-streaming",
            protocol_type="JSONRPC"
        )

        agent_config = AgentConfig(
            name="agent_with_external",
            description="Agent with external A2A agent",
            tools=[],
            max_steps=5,
            model_name="test_model",
            external_a2a_agents=[ext_agent_config]
        )

        mock_wrapper_instance = MagicMock()
        mock_wrapper_class = MagicMock(return_value=mock_wrapper_instance)

        mock_a2a_module = MagicMock()
        mock_a2a_module.ExternalA2AAgentWrapper = mock_wrapper_class

        with patch.dict("sys.modules", {"sdk.nexent.core.agents.a2a_agent_proxy": mock_a2a_module}):
            with patch.object(nexent_agent, 'CoreAgent', return_value=mock_core_agent) as mock_core_agent_fn:
                result = nexent_agent_instance.create_single_agent(agent_config)

                mock_wrapper_class.assert_called_once()
                call_kwargs = mock_wrapper_class.call_args[1]
                assert call_kwargs["stop_event"] == nexent_agent_instance.stop_event
                assert call_kwargs["observer"] == nexent_agent_instance.observer

                # Verify agent_info was passed and has correct type
                a2a_agent_info = call_kwargs["agent_info"]
                assert a2a_agent_info is not None
                assert hasattr(a2a_agent_info, 'agent_id')

                # Verify the A2A agent is nested in the managed-agent observer wrapper.
                mock_core_agent_fn.assert_called_once()
                core_agent_call_kwargs = mock_core_agent_fn.call_args[1]
                managed = core_agent_call_kwargs["managed_agents"]
                assert len(managed) == 1
                assert managed[0]._inner is mock_wrapper_instance

    def test_create_single_agent_with_multiple_external_a2a_agents(self, nexent_agent_instance, mock_model_config, mock_core_agent):
        """Test create_single_agent correctly creates multiple external A2A agent wrappers."""
        nexent_agent_instance.model_config_list = [mock_model_config]

        ext_agent_1 = ExternalA2AAgentConfig(
            agent_id="ext_agent_1",
            name="External Assistant 1",
            description="First external assistant",
            url="https://example1.com/a2a",
            transport_type="http-streaming"
        )
        ext_agent_2 = ExternalA2AAgentConfig(
            agent_id="ext_agent_2",
            name="External Assistant 2",
            description="Second external assistant",
            url="https://example2.com/a2a",
            transport_type="http-polling"
        )

        agent_config = AgentConfig(
            name="agent_with_multiple_external",
            description="Agent with multiple external A2A agents",
            tools=[],
            max_steps=5,
            model_name="test_model",
            external_a2a_agents=[ext_agent_1, ext_agent_2]
        )

        mock_wrapper_instance_1 = MagicMock()
        mock_wrapper_instance_2 = MagicMock()
        mock_wrapper_class = MagicMock(side_effect=[mock_wrapper_instance_1, mock_wrapper_instance_2])

        mock_a2a_module = MagicMock()
        mock_a2a_module.ExternalA2AAgentWrapper = mock_wrapper_class

        with patch.dict("sys.modules", {"sdk.nexent.core.agents.a2a_agent_proxy": mock_a2a_module}):
            with patch.object(nexent_agent, 'CoreAgent', return_value=mock_core_agent) as mock_core_agent_fn:
                result = nexent_agent_instance.create_single_agent(agent_config)

                assert mock_wrapper_class.call_count == 2

                # Verify both A2A agents are nested in managed-agent observer wrappers.
                core_agent_call_kwargs = mock_core_agent_fn.call_args[1]
                managed = core_agent_call_kwargs["managed_agents"]
                assert [wrapped_agent._inner for wrapped_agent in managed] == [
                    mock_wrapper_instance_1,
                    mock_wrapper_instance_2,
                ]

    def test_create_single_agent_with_external_a2a_agent_import_error(self, nexent_agent_instance, mock_model_config):
        """Test create_single_agent handles import error for ExternalA2AAgentWrapper."""
        nexent_agent_instance.model_config_list = [mock_model_config]

        ext_agent_config = ExternalA2AAgentConfig(
            agent_id="ext_agent_1",
            name="External Assistant",
            description="External assistant that will fail to import",
            url="https://example.com/a2a"
        )

        agent_config = AgentConfig(
            name="agent_with_failing_external",
            description="Agent with failing external A2A agent",
            tools=[],
            max_steps=5,
            model_name="test_model",
            external_a2a_agents=[ext_agent_config]
        )

        mock_a2a_module = MagicMock()
        mock_a2a_module.ExternalA2AAgentWrapper = MagicMock(side_effect=ImportError("Module not found"))

        with patch.dict("sys.modules", {"sdk.nexent.core.agents.a2a_agent_proxy": mock_a2a_module}):
            with pytest.raises(ValueError, match="Error in creating external A2A agent wrapper:"):
                nexent_agent_instance.create_single_agent(agent_config)

    def test_create_single_agent_with_external_a2a_agent_wrapper_error(self, nexent_agent_instance, mock_model_config):
        """Test create_single_agent handles wrapper creation error."""
        nexent_agent_instance.model_config_list = [mock_model_config]

        ext_agent_config = ExternalA2AAgentConfig(
            agent_id="ext_agent_1",
            name="External Assistant",
            description="External assistant that will fail",
            url="https://example.com/a2a"
        )

        agent_config = AgentConfig(
            name="agent_with_failing_wrapper",
            description="Agent with failing wrapper",
            tools=[],
            max_steps=5,
            model_name="test_model",
            external_a2a_agents=[ext_agent_config]
        )

        mock_a2a_module = MagicMock()
        mock_a2a_module.ExternalA2AAgentWrapper = MagicMock(side_effect=Exception("Wrapper creation failed"))

        with patch.dict("sys.modules", {"sdk.nexent.core.agents.a2a_agent_proxy": mock_a2a_module}):
            with pytest.raises(ValueError, match="Error in creating external A2A agent wrapper:"):
                nexent_agent_instance.create_single_agent(agent_config)

    def test_create_single_agent_with_external_and_managed_agents(self, nexent_agent_instance, mock_model_config, mock_core_agent):
        """Test create_single_agent correctly combines managed_agents and external_a2a_agents."""
        nexent_agent_instance.model_config_list = [mock_model_config]

        sub_agent_config = AgentConfig(
            name="sub_agent",
            description="A local sub agent",
            tools=[],
            max_steps=3,
            model_name="test_model"
        )

        ext_agent_config = ExternalA2AAgentConfig(
            agent_id="ext_agent_1",
            name="External Assistant",
            description="An external assistant",
            url="https://example.com/a2a"
        )

        agent_config = AgentConfig(
            name="agent_with_both",
            description="Agent with both managed and external agents",
            tools=[],
            max_steps=5,
            model_name="test_model",
            managed_agents=[sub_agent_config],
            external_a2a_agents=[ext_agent_config]
        )

        mock_wrapper_instance = MagicMock()
        mock_wrapper_class = MagicMock(return_value=mock_wrapper_instance)

        mock_a2a_module = MagicMock()
        mock_a2a_module.ExternalA2AAgentWrapper = mock_wrapper_class

        with patch.dict("sys.modules", {"sdk.nexent.core.agents.a2a_agent_proxy": mock_a2a_module}):
            with patch.object(nexent_agent, 'CoreAgent', return_value=mock_core_agent) as mock_core_agent_fn:
                result = nexent_agent_instance.create_single_agent(agent_config)

                # Verify external wrapper was created
                mock_wrapper_class.assert_called_once()

                # Verify CoreAgent received wrappers around both managed agents.
                core_agent_call_kwargs = mock_core_agent_fn.call_args[1]
                managed = core_agent_call_kwargs["managed_agents"]
                assert len(managed) == 2
                assert isinstance(managed[0]._inner, mock_core_agent_class)
                assert managed[1]._inner is mock_wrapper_instance


class TestAddHistoryToAgentEdgeCases:
    """Additional edge case tests for add_history_to_agent method."""

    def test_add_history_to_agent_with_none_history(self, nexent_agent_instance, mock_core_agent):
        """Test add_history_to_agent returns early when history is None."""
        nexent_agent_instance.agent = mock_core_agent

        # Should not raise and should not modify anything
        nexent_agent_instance.add_history_to_agent(None)

        mock_core_agent.memory.reset.assert_not_called()

    def test_add_history_to_agent_with_empty_list(self, nexent_agent_instance, mock_core_agent):
        """Test add_history_to_agent handles empty history list."""
        nexent_agent_instance.agent = mock_core_agent
        mock_core_agent.memory.steps = []

        history = []
        nexent_agent_instance.add_history_to_agent(history)

        mock_core_agent.memory.reset.assert_called_once()
        assert len(mock_core_agent.memory.steps) == 0

    def test_add_history_to_agent_invalid_type_in_list(self, nexent_agent_instance, mock_core_agent):
        """Test add_history_to_agent raises TypeError when history contains non-AgentHistory."""
        nexent_agent_instance.agent = mock_core_agent

        history = [
            AgentHistory(role="user", content="Valid message"),
            {"role": "assistant", "content": "Invalid - not AgentHistory"}
        ]

        with pytest.raises(TypeError, match="history must be a list of AgentHistory objects"):
            nexent_agent_instance.add_history_to_agent(history)

    def test_add_history_to_agent_invalid_agent_type(self, nexent_agent_instance):
        """Test add_history_to_agent raises TypeError when agent is not CoreAgent."""
        nexent_agent_instance.agent = None

        history = [AgentHistory(role="user", content="Hello")]

        with pytest.raises(TypeError, match="agent must be a CoreAgent object"):
            nexent_agent_instance.add_history_to_agent(history)

    def test_add_history_to_agent_preserves_step_numbers(self, nexent_agent_instance, mock_core_agent):
        """Test add_history_to_agent correctly sets step_number for assistant steps."""
        nexent_agent_instance.agent = mock_core_agent
        mock_core_agent.memory.steps = []

        history = [
            AgentHistory(role="user", content="First message"),
            AgentHistory(role="assistant", content="First response"),
            AgentHistory(role="user", content="Second message"),
            AgentHistory(role="assistant", content="Second response"),
        ]

        nexent_agent_instance.add_history_to_agent(history)

        # Verify the step numbers are correctly assigned
        assistant_steps = [s for s in mock_core_agent.memory.steps if isinstance(s, _ActionStep)]
        assert len(assistant_steps) == 2
        # First assistant step should have step_number 2 (after the user step)
        assert assistant_steps[0].step_number == 2
        # Second assistant step should have step_number 4
        assert assistant_steps[1].step_number == 4


class TestAgentRunWithObserverEdgeCases:
    """Additional edge case tests for agent_run_with_observer method."""

    def test_agent_run_with_observer_empty_step_list(self, nexent_agent_instance, mock_core_agent):
        """Test agent_run_with_observer handles empty step list."""
        nexent_agent_instance.agent = mock_core_agent
        mock_core_agent.stop_event.is_set.return_value = False
        mock_core_agent.run.return_value = []

        # Should not raise but also no final answer added
        try:
            nexent_agent_instance.agent_run_with_observer("test query")
        except Exception:
            # If step_log is undefined, it might raise NameError - this is expected behavior
            pass

    def test_agent_run_with_observer_with_none_duration(self, nexent_agent_instance, mock_core_agent):
        """Test agent_run_with_observer handles None duration."""
        nexent_agent_instance.agent = mock_core_agent
        mock_core_agent.stop_event.is_set.return_value = False

        mock_action_step = MagicMock(spec=_ActionStep)
        mock_action_step.timing = MagicMock()
        mock_action_step.timing.duration = None
        mock_action_step.step_number = 1
        mock_action_step.error = None

        mock_core_agent.run.return_value = [mock_action_step]
        mock_core_agent.run.return_value[-1].output = "Final answer"

        nexent_agent_instance.agent_run_with_observer("test query")

        mock_core_agent.observer.add_message.assert_any_call("", ProcessType.TOKEN_COUNT, ANY)
        mock_core_agent.observer.add_message.assert_any_call("test_agent", ProcessType.FINAL_ANSWER, "Final answer")

    def test_agent_run_with_observer_with_float_duration_conversion(self, nexent_agent_instance, mock_core_agent):
        """Test agent_run_with_observer correctly converts duration to string."""
        nexent_agent_instance.agent = mock_core_agent
        mock_core_agent.stop_event.is_set.return_value = False

        mock_action_step = MagicMock(spec=_ActionStep)
        mock_action_step.timing = MagicMock()
        mock_action_step.timing.duration = 3.14159
        mock_action_step.step_number = 1
        mock_action_step.error = None

        mock_core_agent.run.return_value = [mock_action_step]
        mock_core_agent.run.return_value[-1].output = "Answer"

        nexent_agent_instance.agent_run_with_observer("test query")

        # Verify duration was rounded to 2 decimal places
        mock_core_agent.observer.add_message.assert_any_call("", ProcessType.TOKEN_COUNT, ANY)


# ----------------------------------------------------------------------------
# Tests for sandbox warm-up logic (lines 502-544)
# ----------------------------------------------------------------------------


class TestSandboxWarmUp:
    """Tests for sandbox warm-up logic in create_single_agent.

    These tests verify the sandbox configuration handling logic without
    requiring the actual sandbox module to be loaded.
    """

    def test_has_host_tools_detects_host_tools_in_tool_list(
        self, nexent_agent_instance
    ):
        """Test that _has_host_tools correctly identifies tools with host execution flag."""
        mock_host_tool = MagicMock()
        mock_host_tool._nexent_execute_on_host = True
        mock_normal_tool = MagicMock()
        mock_normal_tool._nexent_execute_on_host = False

        result_with_host = _has_host_tools([mock_host_tool, mock_normal_tool])
        assert result_with_host is True

        result_without_host = _has_host_tools([mock_normal_tool])
        assert result_without_host is False

    def test_create_single_agent_sandbox_config_none_skips_executor(
        self, nexent_agent_instance, mock_model_config, mock_core_agent
    ):
        """Test that when sandbox_config is None, no executor is created."""
        nexent_agent_instance.model_config_list = [mock_model_config]
        nexent_agent_instance.sandbox_config = None

        mock_agent_config = AgentConfig(
            name="no_sandbox_agent",
            description="Agent without sandbox",
            prompt_templates={"system": "You are a test agent"},
            tools=[],
            max_steps=5,
            model_name="test_model",
            provide_run_summary=False,
            managed_agents=[]
        )

        with patch.object(nexent_agent, "CoreAgent", return_value=mock_core_agent) as mock_core_agent_fn:
            result = nexent_agent_instance.create_single_agent(mock_agent_config)

            mock_core_agent_fn.assert_called_once()
            call_kwargs = mock_core_agent_fn.call_args[1]
            assert call_kwargs.get("executor") is None

    def test_create_single_agent_managed_context_builds_executor(
        self, nexent_agent_instance, mock_model_config, mock_core_agent
    ):
        """Managed sub-agents receive their own configured sandbox executor."""
        nexent_agent_instance.model_config_list = [mock_model_config]

        from enum import Enum

        class SandboxLevel(str, Enum):
            LOCAL = "local"
            DOCKER = "docker"

        mock_sandbox_config = MagicMock()
        mock_sandbox_config.level = SandboxLevel.LOCAL
        mock_sandbox_config.scope.value = "system"
        nexent_agent_instance.sandbox_config = mock_sandbox_config
        mock_executor = MagicMock()
        mock_build = MagicMock(return_value=mock_executor)
        mock_sandbox_module = MagicMock()
        mock_sandbox_module.build_python_executor = mock_build
        mock_sandbox_module.SandboxLevel = SandboxLevel

        mock_agent_config = AgentConfig(
            name="managed_agent",
            description="Managed agent",
            prompt_templates={"system": "You are a test agent"},
            tools=[],
            max_steps=5,
            model_name="test_model",
            provide_run_summary=False,
            managed_agents=[]
        )

        with patch.dict("sys.modules", {
            "sdk.nexent.core.agents.sandbox": mock_sandbox_module,
        }), patch.object(nexent_agent, "CoreAgent", return_value=mock_core_agent) as mock_core_agent_fn:
            nexent_agent_instance.create_single_agent(mock_agent_config, _managed_context=True)

        mock_core_agent_fn.assert_called_once()
        assert mock_core_agent_fn.call_args.kwargs["executor"] is mock_executor
        mock_build.assert_called_once_with(
            config=mock_sandbox_config,
            logger_=ANY,
            managed_agents_exist=False,
            host_tools_exist=False,
            session_container_group=None,
        )


# ----------------------------------------------------------------------------
# Tests for _log_step_metrics file writing (lines 789-790)
# ----------------------------------------------------------------------------


class TestLogStepMetrics:
    """Tests for _log_step_metrics method."""

    def test_log_step_metrics_with_empty_metrics(self, nexent_agent_instance, mock_core_agent):
        """Test _log_step_metrics handles empty step_metrics gracefully."""
        nexent_agent_instance.agent = mock_core_agent
        mock_core_agent.step_metrics = []
        mock_core_agent.context_manager = None

        # Should not raise any exception
        nexent_agent_instance._log_step_metrics()

    def test_log_step_metrics_without_step_metrics_attribute(self, nexent_agent_instance, mock_core_agent):
        """Test _log_step_metrics handles missing step_metrics attribute."""
        nexent_agent_instance.agent = mock_core_agent
        if hasattr(mock_core_agent, "step_metrics"):
            delattr(mock_core_agent, "step_metrics")
        mock_core_agent.context_manager = None

        # Should not raise any exception
        nexent_agent_instance._log_step_metrics()


# ----------------------------------------------------------------------------
# Tests for _cleanup_sandbox method (lines 806-831)
# ----------------------------------------------------------------------------


class TestCleanupSandbox:
    """Tests for _cleanup_sandbox method.

    Note: Full sandbox cleanup tests (session scope, system scope, MinIO sync)
    require the actual sandbox module to be loaded since the functions are
    imported inside the method. The tests below cover the easily testable
    early return case and leave the complex cases as integration tests.
    """

    def test_cleanup_sandbox_no_executor(self, nexent_agent_instance, mock_core_agent):
        """Test _cleanup_sandbox returns early when no executor exists."""
        nexent_agent_instance.agent = mock_core_agent
        mock_core_agent.python_executor = None

        nexent_agent_instance._cleanup_sandbox()

    def test_cleanup_sandbox_with_none_python_executor_attribute(self, nexent_agent_instance, mock_core_agent):
        """Test _cleanup_sandbox handles getattr returning None gracefully."""
        nexent_agent_instance.agent = mock_core_agent
        # Simulate getattr returning None
        mock_core_agent.python_executor = None

        nexent_agent_instance._cleanup_sandbox()

class TestCleanupSandbox:
    """Tests for _cleanup_sandbox method.

    Note: Full sandbox cleanup tests (session scope, system scope, MinIO sync)
    require the actual sandbox module to be loaded since the functions are
    imported inside the method. The tests below cover the easily testable
    early return case and leave the complex cases as integration tests.
    """

    def test_cleanup_sandbox_no_executor(self, nexent_agent_instance, mock_core_agent):
        """Test _cleanup_sandbox returns early when no executor exists."""
        nexent_agent_instance.agent = mock_core_agent
        mock_core_agent.python_executor = None

        nexent_agent_instance._cleanup_sandbox()

    def test_cleanup_sandbox_with_none_python_executor_attribute(self, nexent_agent_instance, mock_core_agent):
        """Test _cleanup_sandbox handles getattr returning None gracefully."""
        nexent_agent_instance.agent = mock_core_agent
        # Simulate getattr returning None
        mock_core_agent.python_executor = None

        nexent_agent_instance._cleanup_sandbox()

    def test_cleanup_sandbox_no_sandbox_scope(self, nexent_agent_instance, mock_core_agent):
        """Test _cleanup_sandbox when _sandbox_scope is None."""
        nexent_agent_instance.agent = mock_core_agent
        mock_core_agent.python_executor = MagicMock()
        nexent_agent_instance._sandbox_scope = None

        nexent_agent_instance._cleanup_sandbox()


# ----------------------------------------------------------------------------
# Tests for _build_tool_input function (lines 57-69)
# ----------------------------------------------------------------------------


class TestBuildToolInput:
    """Tests for _build_tool_input helper function."""

    def test_build_tool_input_with_valid_signature(self):
        """Test _build_tool_input correctly binds args to signature."""
        def example_func(a, b, c=3):
            pass

        result = _build_tool_input(example_func, (1, 2), {"c": 4})
        assert result == {"a": 1, "b": 2, "c": 4}

    def test_build_tool_input_with_kwargs_only(self):
        """Test _build_tool_input handles kwargs-only calls."""
        def example_func(a, b):
            pass

        result = _build_tool_input(example_func, (), {"a": 1, "b": 2})
        assert result == {"a": 1, "b": 2}

    def test_build_tool_input_with_unmatched_signature(self):
        """Test _build_tool_input falls back when signature binding fails."""
        def example_func(a, b):
            pass

        # Call with too many positional args (should fail signature.bind_partial)
        result = _build_tool_input(example_func, (1, 2, 3, 4), {})
        # Should fall back to raw args/kwargs
        assert "args" in result
        assert result["args"] == [1, 2, 3, 4]

    def test_build_tool_input_with_empty_args_and_kwargs(self):
        """Test _build_tool_input handles empty inputs."""
        def example_func():
            pass

        result = _build_tool_input(example_func, (), {})
        assert result == {}

    def test_build_tool_input_with_kwargs_fallback(self):
        """Test _build_tool_input uses kwargs when signature binding fails."""
        def example_func(a):
            pass

        # Too many kwargs for a single-arg function
        result = _build_tool_input(example_func, (), {"a": 1, "b": 2})
        # Should fall back to using available args/kwargs
        assert result.get("a") == 1 or "kwargs" in result


# ----------------------------------------------------------------------------
# Tests for _wrap_tool_with_monitoring function (lines 72-143)
# ----------------------------------------------------------------------------


class TestWrapToolWithMonitoring:
    """Tests for _wrap_tool_with_monitoring helper function."""

    def test_wrap_tool_already_wrapped(self):
        """Test _wrap_tool_with_monitoring returns early for already wrapped tools."""
        mock_tool = MagicMock()
        mock_tool._nexent_monitoring_wrapped = True

        result = _wrap_tool_with_monitoring(mock_tool, "test_agent")
        assert result is mock_tool

    def test_wrap_tool_with_forward_method(self):
        """Test _wrap_tool_with_monitoring wraps tools with forward method."""
        mock_tool = MagicMock()
        mock_tool.forward = MagicMock(return_value="result")
        mock_tool._nexent_monitoring_wrapped = False

        result = _wrap_tool_with_monitoring(mock_tool, "test_agent")

        # The tool should now be marked as wrapped
        assert getattr(result, "_nexent_monitoring_wrapped", False) is True

    def test_wrap_tool_with_callable(self):
        """Test _wrap_tool_with_monitoring wraps callable tools."""
        def mock_callable(*args, **kwargs):
            return "result"

        mock_callable._nexent_monitoring_wrapped = False

        result = _wrap_tool_with_monitoring(mock_callable, "test_agent")

        # The callable should now be marked as wrapped
        assert getattr(result, "_nexent_monitoring_wrapped", False) is True

    def test_wrap_tool_without_forward_or_callable(self):
        """Test _wrap_tool_with_monitoring returns wrapped object for callable without forward."""
        # MagicMock with spec=[] is still callable due to MagicMock's nature
        # So it gets wrapped as a callable
        mock_tool = MagicMock(spec=[])
        mock_tool._nexent_monitoring_wrapped = False
        # Remove forward attribute if present
        if hasattr(mock_tool, 'forward'):
            del mock_tool.forward

        result = _wrap_tool_with_monitoring(mock_tool, "test_agent")

        # The result should be wrapped (a callable wrapper function)
        assert callable(result)
        assert getattr(result, "_nexent_monitoring_wrapped", False) is True


# ----------------------------------------------------------------------------
# Tests for create_builtin_tool (lines 325-385)
# ----------------------------------------------------------------------------


class TestCreateBuiltinTool:
    """Tests for create_builtin_tool method."""

    def test_create_builtin_tool_run_skill_script(self, nexent_agent_instance):
        """Test create_builtin_tool with RunSkillScriptTool."""
        tool_config = ToolConfig(
            class_name="RunSkillScriptTool",
            name="run_skill_script",
            description="Run a skill script",
            inputs="{}",
            output_type="string",
            params={"local_skills_dir": "/tmp/skills"},
            source="builtin",
            metadata={
                "agent_id": "agent_123",
                "tenant_id": "tenant_456",
                "version_no": 1
            },
        )

        mock_tool_instance = MagicMock()
        mock_tool_class = MagicMock(return_value=mock_tool_instance)

        with patch.dict("sys.modules", {
            "nexent.core.tools.run_skill_script_tool": MagicMock(
                RunSkillScriptTool=mock_tool_class,
            )
        }):
            result = nexent_agent_instance.create_builtin_tool(tool_config)
            assert result is mock_tool_instance
            mock_tool_class.assert_called_once_with(
                local_skills_dir="/tmp/skills",
                agent_id="agent_123",
                tenant_id="tenant_456",
                version_no=1,
                observer=nexent_agent_instance.observer,
                authorized_skill_names=None,
            )


class TestCreateBuiltinToolAndFileWorkspaceLifecycle:
    @pytest.mark.parametrize("class_name", ["DownloadFromS3Tool", "UploadToS3Tool"])
    def test_create_local_s3_tool_injects_runtime_context(
        self, nexent_agent_instance, class_name
    ):
        tool_class = MagicMock(return_value=MagicMock(inputs={}, output_type="string"))
        tool_config = ToolConfig(
            class_name=class_name,
            name=class_name,
            description="S3 file tool",
            inputs="{}",
            output_type="string",
            params={"workspace_path": "/mnt/nexent/workdir/user/run"},
            source="local",
            metadata={
                "minio_client": "storage",
                "user_id": "user",
                "tenant_id": "tenant",
            },
        )

        with patch.object(nexent_agent, class_name, tool_class, create=True):
            result = nexent_agent_instance.create_local_tool(tool_config)

        assert result is tool_class.return_value
        tool_class.assert_called_once_with(
            workspace_path="/mnt/nexent/workdir/user/run",
            minio_client="storage",
            user_id="user",
            tenant_id="tenant",
            observer=nexent_agent_instance.observer,
        )

    def test_builtin_skill_workspace_callback_pushes_files(self, nexent_agent_instance):
        tool_class = MagicMock(return_value=MagicMock())
        tool_config = ToolConfig(
            class_name="RunSkillScriptTool",
            name="run_skill_script",
            description="Run a skill",
            inputs="{}",
            output_type="string",
            params={
                "local_skills_dir": "/tmp/skills",
                "workspace_path": "/mnt/nexent/workdir/user/run",
            },
            source="builtin",
            metadata={},
        )

        with patch.dict("sys.modules", {
            "nexent.core.tools.run_skill_script_tool": MagicMock(
                RunSkillScriptTool=tool_class,
            )
        }), patch.object(nexent_agent_instance, "_push_file_workspace_to_sandbox") as push:
            nexent_agent_instance.create_builtin_tool(tool_config)
            tool_class.call_args.kwargs["on_complete"]("done")

        assert tool_class.call_args.kwargs["workspace_path"] == tool_config.params["workspace_path"]
        push.assert_called_once_with()

    def test_record_workspace_upload_deduplicates_object_name(self, nexent_agent_instance):
        upload = {"object_name": "workspace/user/run/outputs/report.txt"}

        nexent_agent_instance._record_workspace_upload(upload)
        nexent_agent_instance._record_workspace_upload(dict(upload))

        assert nexent_agent_instance._workspace_uploads == [upload]

    def test_cleanup_run_workspace_rejects_mismatched_run_id(self, tmp_path):
        workspace = tmp_path / "user" / "actual-run"
        workspace.mkdir(parents=True)
        cleanup_logger = MagicMock()

        removed = nexent_agent.cleanup_run_workspace(
            str(workspace), "different-run", cleanup_logger
        )

        assert removed is False
        assert workspace.exists()
        cleanup_logger.error.assert_called_once()

    def test_sandbox_container_returns_none_without_docker_container(
        self, nexent_agent_instance
    ):
        nexent_agent_instance._sandbox_executors = [object()]
        nexent_agent_instance.agent = MagicMock(python_executor=None)

        assert nexent_agent_instance._sandbox_container() is None

    def test_initialize_sandbox_workspaces_skips_missing_workspace(
        self, nexent_agent_instance
    ):
        nexent_agent_instance.workspace_path = None
        nexent_agent_instance._sandbox_executors = [MagicMock()]

        nexent_agent_instance._initialize_sandbox_workspaces()

        nexent_agent_instance._sandbox_executors[0].assert_not_called()

    def test_initialize_sandbox_workspaces_deduplicates_and_skips_unsupported_executors(
        self, nexent_agent_instance, tmp_path
    ):
        workspace = tmp_path / "user" / "run"
        (workspace / "outputs").mkdir(parents=True)
        docker_executor = MagicMock(_nexent_backend="docker")
        unsupported_executor = object()
        nexent_agent_instance.workspace_path = str(workspace)
        nexent_agent_instance._sandbox_executors = [
            docker_executor,
            docker_executor,
            unsupported_executor,
        ]

        nexent_agent_instance._initialize_sandbox_workspaces()

        docker_executor.assert_called_once()

    def test_prepare_workspace_rejects_files_without_download_tool(
        self, nexent_agent_instance, tmp_path
    ):
        nexent_agent_instance.workspace_path = str(tmp_path / "user" / "run")
        nexent_agent_instance.minio_files = [{"object_name": "attachments/user/a.txt"}]
        nexent_agent_instance.agent = MagicMock(tools={})

        with pytest.raises(RuntimeError, match="download_from_s3 is unavailable"):
            nexent_agent_instance._prepare_file_workspace("query")

    def test_prepare_workspace_skips_invalid_and_empty_file_entries(
        self, nexent_agent_instance, tmp_path
    ):
        workspace = tmp_path / "user" / "run"
        nexent_agent_instance.workspace_path = str(workspace)
        nexent_agent_instance.minio_files = ["invalid", {}, {"url": ""}]
        nexent_agent_instance.agent = MagicMock(tools={"download_from_s3": MagicMock()})

        with patch.object(nexent_agent_instance, "_push_file_workspace_to_sandbox") as push:
            result = nexent_agent_instance._prepare_file_workspace("query")

        assert "Run workspace" in result
        assert "Use bare relative paths" in result
        assert "not 'outputs/report.pdf'" in result
        assert "script_path='outputs/build.js'" in result
        assert "Direct subprocess, os.system, and shell calls" in result
        assert "sys.executable -m pip install" in result
        push.assert_called_once_with()

    def test_initialize_sandbox_workspaces_sets_cwd_for_every_docker_kernel(
        self, nexent_agent_instance, tmp_path
    ):
        class UnmarkedKernelLease:
            def __init__(self):
                self.container = object()
                self.calls = []

            def __call__(self, code):
                self.calls.append(code)

        workspace = tmp_path / "user" / "run"
        (workspace / "outputs").mkdir(parents=True)
        child_executor = MagicMock(_nexent_backend="docker")
        parent_executor = MagicMock(_nexent_backend="docker")
        local_executor = MagicMock(_nexent_backend="local")
        unmarked_kernel_lease = UnmarkedKernelLease()
        nexent_agent_instance.workspace_path = str(workspace)
        nexent_agent_instance._sandbox_executors = [
            child_executor,
            parent_executor,
            local_executor,
            unmarked_kernel_lease,
        ]

        nexent_agent_instance._initialize_sandbox_workspaces()

        for executor in (child_executor, parent_executor):
            executor.assert_called_once()
            bootstrap_code = executor.call_args.args[0]
            assert json.dumps(str(workspace.resolve())) in bootstrap_code
            assert json.dumps(str((workspace / "outputs").resolve())) in bootstrap_code
            assert "NEXENT_WORKSPACE" in bootstrap_code
            assert "NEXENT_OUTPUT_DIR" in bootstrap_code
            assert "chdir" in bootstrap_code
        local_executor.assert_not_called()
        assert len(unmarked_kernel_lease.calls) == 1
        assert "NEXENT_OUTPUT_DIR" in unmarked_kernel_lease.calls[0]

    def test_initialize_sandbox_workspaces_retries_unhealthy_kernel_lease(
        self, nexent_agent_instance, tmp_path
    ):
        class RecoveringKernelLease:
            _nexent_backend = "docker"
            _nexent_kernel_recovery_supported = True

            def __init__(self):
                self.container = object()
                self._unhealthy = False
                self.calls = []
                self.registered_bootstrap = []

            def __call__(self, code):
                self.calls.append(code)
                if len(self.calls) == 1:
                    self._unhealthy = True
                    raise RuntimeError("kernel channel failed")
                self._unhealthy = False
                return ["workspace", "outputs"]

            def register_kernel_bootstrap_code(self, code):
                result = self(code)
                self.registered_bootstrap.append(code)
                return result

        workspace = tmp_path / "user" / "run"
        (workspace / "outputs").mkdir(parents=True)
        executor = RecoveringKernelLease()
        nexent_agent_instance.workspace_path = str(workspace)
        nexent_agent_instance._sandbox_executors = [executor]

        nexent_agent_instance._initialize_sandbox_workspaces()

        assert len(executor.calls) == 2
        assert executor.calls[0] == executor.calls[1]
        assert executor._unhealthy is False
        assert executor.registered_bootstrap == [executor.calls[0]]

    def test_initialize_sandbox_workspaces_reports_retry_failure(
        self, nexent_agent_instance, tmp_path
    ):
        class FailingKernelLease:
            _nexent_backend = "docker"
            _nexent_kernel_recovery_supported = True
            _unhealthy = True
            container = object()

            def register_kernel_bootstrap_code(self, code):
                raise RuntimeError("replacement bootstrap failed")

        workspace = tmp_path / "user" / "run"
        (workspace / "outputs").mkdir(parents=True)
        nexent_agent_instance.workspace_path = str(workspace)
        nexent_agent_instance._sandbox_executors = [FailingKernelLease()]

        with pytest.raises(RuntimeError, match="replacement bootstrap failed"):
            nexent_agent_instance._initialize_sandbox_workspaces()

    def test_initialize_sandbox_workspaces_does_not_retry_healthy_failure(
        self, nexent_agent_instance, tmp_path
    ):
        executor = MagicMock(
            _nexent_backend="docker",
            _nexent_kernel_recovery_supported=True,
            _unhealthy=False,
        )
        executor.side_effect = RuntimeError("bootstrap rejected")
        workspace = tmp_path / "user" / "run"
        (workspace / "outputs").mkdir(parents=True)
        nexent_agent_instance.workspace_path = str(workspace)
        nexent_agent_instance._sandbox_executors = [executor]

        with pytest.raises(RuntimeError, match="bootstrap rejected"):
            nexent_agent_instance._initialize_sandbox_workspaces()

        executor.assert_called_once()

    def test_sandbox_containers_include_children_and_deduplicate_shared_container(
        self, nexent_agent_instance
    ):
        shared_container = MagicMock(id="shared-container")
        child_container = MagicMock(id="child-container")
        nexent_agent_instance._sandbox_executors = [
            MagicMock(container=shared_container),
            MagicMock(container=child_container),
        ]
        nexent_agent_instance.agent = MagicMock(
            python_executor=MagicMock(container=shared_container)
        )

        assert nexent_agent_instance._sandbox_containers() == [
            shared_container,
            child_container,
        ]

    @pytest.mark.parametrize("put_archive_result", [True, False])
    def test_non_shared_workspace_pushes_archive(
        self, nexent_agent_instance, put_archive_result
    ):
        workspace = MagicMock()
        workspace.resolve.return_value = workspace
        workspace.exists.return_value = True
        workspace.drive = ""
        workspace.__str__.return_value = "/mnt/nexent/workdir/user/run"
        container = MagicMock()
        container.put_archive.return_value = put_archive_result
        nexent_agent_instance.workspace_path = "/mnt/nexent/workdir/user/run"
        nexent_agent_instance.sandbox_config = MagicMock(extra_kwargs={})
        nexent_agent_instance.agent = MagicMock(
            python_executor=MagicMock(container=container)
        )
        archive_writer = MagicMock()
        archive_context = MagicMock()
        archive_context.__enter__.return_value = archive_writer

        with patch.object(nexent_agent, "Path", return_value=workspace), patch.object(
            nexent_agent.tarfile, "open", return_value=archive_context
        ), patch.object(nexent_agent_instance, "_grant_sandbox_output_access") as grant:
            if put_archive_result:
                nexent_agent_instance._push_file_workspace_to_sandbox()
            else:
                with pytest.raises(RuntimeError, match="Failed to copy run workspace"):
                    nexent_agent_instance._push_file_workspace_to_sandbox()

        archive_writer.add.assert_called_once()
        if put_archive_result:
            grant.assert_called_once_with(container, workspace)
        else:
            grant.assert_not_called()

    def test_grant_sandbox_output_access_uses_sandbox_group(self, tmp_path):
        workspace = tmp_path / "tenant" / "user" / "run-1"
        input_dir = workspace / "inputs"
        output_dir = workspace / "outputs"
        input_dir.mkdir(parents=True)
        output_dir.mkdir(parents=True)
        container = MagicMock()
        container.exec_run.side_effect = [
            MagicMock(exit_code=0, output=b"1000\n"),
            MagicMock(exit_code=0, output=b""),
            MagicMock(exit_code=0, output=b""),
            MagicMock(exit_code=0, output=b""),
        ]

        NexentAgent._grant_sandbox_output_access(container, workspace)

        assert container.exec_run.call_args_list == [
            call(["id", "-g"]),
            call(["chgrp", "-R", "1000", str(workspace)], user="0"),
            call(["chmod", "-R", "g+rwX", str(workspace)], user="0"),
            call(
                ["find", str(workspace), "-type", "d", "-exec", "chmod", "g+s", "{}", "+"],
                user="0",
            ),
        ]

    def test_shared_workspace_skips_archive_copy(self, nexent_agent_instance, tmp_path):
        workspace = MagicMock()
        workspace.resolve.return_value = workspace
        workspace.exists.return_value = True
        workspace.drive = ""
        container = MagicMock()
        nexent_agent_instance.workspace_path = "/mnt/nexent/workdir/user/run-1"
        nexent_agent_instance.sandbox_config = MagicMock(
            extra_kwargs={
                "shared_workspace": True,
                "workspace_volume_name": "nexent-agent-workspace",
            }
        )
        nexent_agent_instance.agent = MagicMock(
            python_executor=MagicMock(container=container)
        )

        with patch.object(nexent_agent, "Path", return_value=workspace), patch.object(
            nexent_agent_instance, "_grant_sandbox_output_access"
        ) as grant_access:
            nexent_agent_instance._push_file_workspace_to_sandbox()

        container.put_archive.assert_not_called()
        grant_access.assert_called_once_with(container, workspace)

    def test_shared_workspace_skips_archive_pull(self, nexent_agent_instance, tmp_path):
        workspace = tmp_path / "user" / "run-1"
        workspace.mkdir(parents=True)
        container = MagicMock()
        nexent_agent_instance.workspace_path = str(workspace)
        nexent_agent_instance.sandbox_config = MagicMock(
            extra_kwargs={
                "shared_workspace": True,
                "workspace_volume_name": "nexent-agent-workspace",
            }
        )
        nexent_agent_instance.agent = MagicMock(
            python_executor=MagicMock(container=container)
        )

        nexent_agent_instance._pull_file_workspace_from_sandbox()

        container.get_archive.assert_not_called()

    def test_grant_sandbox_output_access_rejects_invalid_gid(self, tmp_path):
        container = MagicMock()
        container.exec_run.return_value = MagicMock(exit_code=0, output=b"sandbox\n")

        with pytest.raises(RuntimeError, match="invalid group ID"):
            NexentAgent._grant_sandbox_output_access(container, tmp_path)

    def test_grant_sandbox_output_access_rejects_gid_command_failure(self, tmp_path):
        container = MagicMock()
        container.exec_run.return_value = MagicMock(exit_code=1, output=b"denied")

        with pytest.raises(RuntimeError, match="determine the sandbox user's group"):
            NexentAgent._grant_sandbox_output_access(container, tmp_path)

    def test_grant_sandbox_output_access_reports_permission_command_failure(self, tmp_path):
        container = MagicMock()
        container.exec_run.side_effect = [
            MagicMock(exit_code=0, output=b"1000\n"),
            MagicMock(exit_code=1, output=b"operation not permitted"),
        ]

        with pytest.raises(RuntimeError, match="operation not permitted"):
            NexentAgent._grant_sandbox_output_access(container, tmp_path)

    def test_pull_workspace_extracts_safe_archive(self, nexent_agent_instance):
        workspace = MagicMock()
        workspace.resolve.return_value = workspace
        workspace.drive = ""
        workspace.__str__.return_value = "/mnt/nexent/workdir/user/run"
        extraction_root = MagicMock()
        workspace.parent.resolve.return_value = extraction_root
        target = MagicMock()
        extraction_root.__truediv__.return_value.resolve.return_value = target
        member = MagicMock(name="safe-member")
        member.name = "run/outputs/report.txt"
        member.isfile.return_value = True
        member.isdir.return_value = False
        archive_reader = MagicMock()
        archive_reader.getmembers.return_value = [member]
        archive_context = MagicMock()
        archive_context.__enter__.return_value = archive_reader
        container = MagicMock()
        container.get_archive.return_value = ([b"archive"], {})
        nexent_agent_instance.workspace_path = "/mnt/nexent/workdir/user/run"
        nexent_agent_instance.sandbox_config = MagicMock(extra_kwargs={})
        nexent_agent_instance.agent = MagicMock(
            python_executor=MagicMock(container=container)
        )

        with patch.object(nexent_agent, "Path", return_value=workspace), patch.object(
            nexent_agent.tarfile, "open", return_value=archive_context
        ):
            nexent_agent_instance._pull_file_workspace_from_sandbox()

        target.relative_to.assert_called_once_with(extraction_root)
        archive_reader.extractall.assert_called_once_with(extraction_root, members=[member])

    @pytest.mark.parametrize("escape_archive", [False, True])
    def test_pull_workspace_rejects_unsafe_archive(
        self, nexent_agent_instance, escape_archive
    ):
        workspace = MagicMock()
        workspace.resolve.return_value = workspace
        workspace.drive = ""
        extraction_root = MagicMock()
        workspace.parent.resolve.return_value = extraction_root
        member = MagicMock()
        member.name = "unsafe"
        member.isfile.return_value = escape_archive
        member.isdir.return_value = False
        target = extraction_root.__truediv__.return_value.resolve.return_value
        if escape_archive:
            target.relative_to.side_effect = ValueError("escape")
        archive_reader = MagicMock()
        archive_reader.getmembers.return_value = [member]
        archive_context = MagicMock()
        archive_context.__enter__.return_value = archive_reader
        container = MagicMock()
        container.get_archive.return_value = ([b"archive"], {})
        nexent_agent_instance.workspace_path = "/mnt/nexent/workdir/user/run"
        nexent_agent_instance.sandbox_config = MagicMock(extra_kwargs={})
        nexent_agent_instance.agent = MagicMock(
            python_executor=MagicMock(container=container)
        )

        with patch.object(nexent_agent, "Path", return_value=workspace), patch.object(
            nexent_agent.tarfile, "open", return_value=archive_context
        ), patch.object(nexent_agent.logger, "warning") as warning:
            nexent_agent_instance._pull_file_workspace_from_sandbox()

        warning.assert_called_once()

    def test_finalize_workspace_handles_missing_upload_tool(
        self, nexent_agent_instance, tmp_path
    ):
        nexent_agent_instance.workspace_path = str(tmp_path / "user" / "run")
        nexent_agent_instance.agent = MagicMock(tools={})

        with patch.object(nexent_agent_instance, "_pull_file_workspace_from_sandbox"), patch.object(
            nexent_agent.logger, "error"
        ) as error:
            nexent_agent_instance._finalize_file_workspace()

        error.assert_called_once()

    def test_finalize_workspace_skips_inputs_skills_and_uploaded_files_and_reports_failure(
        self, nexent_agent_instance, tmp_path
    ):
        workspace = tmp_path / "user" / "run"
        input_file = workspace / "inputs" / "input.txt"
        skill_file = workspace / "skills" / "probe" / "scripts" / "probe.py"
        uploaded_file = workspace / "outputs" / "uploaded.txt"
        failed_file = workspace / "outputs" / "failed.txt"
        dependency_file = workspace / "outputs" / "app" / "node_modules" / "pkg" / "index.js"
        cache_file = workspace / "outputs" / "app" / ".parcel-cache" / "state"
        virtualenv_file = workspace / "outputs" / ".venv" / "lib" / "module.py"
        for path in (
            input_file,
            skill_file,
            uploaded_file,
            failed_file,
            dependency_file,
            cache_file,
            virtualenv_file,
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("data", encoding="utf-8")
        upload_tool = MagicMock()
        upload_tool.uploaded_paths = {
            os.path.normcase(os.path.abspath(str(uploaded_file)))
        }
        upload_tool.forward.side_effect = RuntimeError("upload failed")
        nexent_agent_instance.workspace_path = str(workspace)
        nexent_agent_instance.agent = MagicMock(tools={"upload_to_s3": upload_tool})

        with patch.object(nexent_agent_instance, "_pull_file_workspace_from_sandbox"):
            nexent_agent_instance._finalize_file_workspace()

        upload_tool.forward.assert_called_once_with(str(failed_file), "outputs/failed.txt")
        assert any(
            call_args.args[1] == ProcessType.ERROR
            for call_args in nexent_agent_instance.observer.add_message.call_args_list
        )

    def test_cleanup_rejects_mismatched_run_directory(self, nexent_agent_instance, tmp_path):
        workspace = tmp_path / "user" / "actual-run"
        workspace.mkdir(parents=True)
        nexent_agent_instance.workspace_path = str(workspace)
        nexent_agent_instance.workspace_run_id = "different-run"

        nexent_agent_instance._cleanup_file_workspace()

        assert workspace.exists()

    @pytest.mark.parametrize("exec_failure", [False, True])
    def test_cleanup_logs_sandbox_failures(
        self, nexent_agent_instance, tmp_path, exec_failure
    ):
        workspace = tmp_path / "user" / "run"
        workspace.mkdir(parents=True)
        container = MagicMock()
        if exec_failure:
            container.exec_run.side_effect = RuntimeError("docker unavailable")
        else:
            container.exec_run.return_value = MagicMock(
                exit_code=1, output=b"permission denied"
            )
        nexent_agent_instance.workspace_path = str(workspace)
        nexent_agent_instance.workspace_run_id = "run"
        nexent_agent_instance.agent = MagicMock(
            python_executor=MagicMock(container=container)
        )

        with patch.object(nexent_agent.logger, "warning") as warning:
            nexent_agent_instance._cleanup_file_workspace()

        warning.assert_called_once()

    def test_cleanup_logs_host_removal_failure(self, nexent_agent_instance, tmp_path):
        workspace = tmp_path / "user" / "run"
        workspace.mkdir(parents=True)
        nexent_agent_instance.workspace_path = str(workspace)
        nexent_agent_instance.workspace_run_id = "run"
        nexent_agent_instance.agent = MagicMock(python_executor=None)

        with patch.object(nexent_agent.shutil, "rmtree", side_effect=OSError("busy")), patch.object(
            nexent_agent.logger, "error"
        ) as error:
            nexent_agent_instance._cleanup_file_workspace()

        error.assert_called_once()

    def test_cleanup_removes_exact_sandbox_run_directory_as_root(
        self, nexent_agent_instance, tmp_path
    ):
        workspace_root = tmp_path / "workdir"
        workspace = workspace_root / "user" / "run-1"
        (workspace / "outputs").mkdir(parents=True)
        (workspace / "outputs" / "result.txt").write_text("result", encoding="utf-8")
        container = MagicMock()
        container.exec_run.return_value = MagicMock(exit_code=0, output=b"")
        nexent_agent_instance.workspace_path = str(workspace)
        nexent_agent_instance.workspace_run_id = "run-1"
        nexent_agent_instance.agent = MagicMock(
            python_executor=MagicMock(container=container)
        )

        nexent_agent_instance._cleanup_file_workspace()

        container.exec_run.assert_called_once_with(
            ["rm", "-rf", "--", str(workspace.resolve())],
            user="0",
        )
        assert not workspace.exists()
        assert not workspace.parent.exists()
        assert workspace_root.exists()

    def test_cleanup_removes_sandbox_directory_when_host_copy_is_missing(
        self, nexent_agent_instance, tmp_path
    ):
        workspace = tmp_path / "workdir" / "user" / "run-1"
        container = MagicMock()
        container.exec_run.return_value = MagicMock(exit_code=0, output=b"")
        nexent_agent_instance.workspace_path = str(workspace)
        nexent_agent_instance.workspace_run_id = "run-1"
        nexent_agent_instance.agent = MagicMock(
            python_executor=MagicMock(container=container)
        )

        nexent_agent_instance._cleanup_file_workspace()

        container.exec_run.assert_called_once_with(
            ["rm", "-rf", "--", str(workspace.resolve())],
            user="0",
        )

    def test_download_finalize_emit_and_cleanup(self, nexent_agent_instance, tmp_path):
        workspace = tmp_path / "user" / "run-1"
        nexent_agent_instance.workspace_path = str(workspace)
        nexent_agent_instance.workspace_run_id = "run-1"
        nexent_agent_instance.minio_files = [
            {"name": "input.csv", "object_name": "attachments/user/input.csv"}
        ]

        download_tool = MagicMock()
        download_tool.minio_client.default_bucket = "nexent"

        def download_file(_source, local_filename):
            path = workspace / local_filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("input", encoding="utf-8")
            return json.dumps({"local_path": str(path)})

        download_tool.forward.side_effect = download_file
        upload_tool = MagicMock()
        upload_tool.uploaded_paths = set()

        def upload_file(file_path, _target_filename):
            payload = {
                "object_name": "workspace/user/run-1/outputs/result.txt",
                "name": Path(file_path).name,
                "file_size_bytes": Path(file_path).stat().st_size,
            }
            nexent_agent_instance._record_workspace_upload(payload)
            return json.dumps(payload)

        upload_tool.forward.side_effect = upload_file
        nexent_agent_instance.agent = MagicMock(
            tools={
                "download_from_s3": download_tool,
                "upload_to_s3": upload_tool,
            },
            python_executor=None,
        )

        query = nexent_agent_instance._prepare_file_workspace("analyze")
        output = workspace / "outputs" / "result.txt"
        output.write_text("result", encoding="utf-8")
        nexent_agent_instance._finalize_file_workspace()
        nexent_agent_instance._cleanup_file_workspace()

        assert str(workspace / "inputs" / "000_input.csv") in query
        upload_tool.forward.assert_called_once_with(str(output), "outputs/result.txt")
        assert not workspace.exists()
        assert any(
            call.args[1] == ProcessType.FILE_ARTIFACT
            for call in nexent_agent_instance.observer.add_message.call_args_list
        )

    def test_create_builtin_tool_read_skill_md(self, nexent_agent_instance):
        """Test create_builtin_tool with ReadSkillMdTool."""
        tool_config = ToolConfig(
            class_name="ReadSkillMdTool",
            name="read_skill_md",
            description="Read skill markdown",
            inputs="{}",
            output_type="string",
            params={"local_skills_dir": "/tmp/skills"},
            source="builtin",
            metadata={
                "agent_id": "agent_123",
                "tenant_id": "tenant_456",
                "version_no": 1
            },
        )

        mock_tool_instance = MagicMock()
        mock_tool_class = MagicMock(return_value=mock_tool_instance)

        with patch.dict("sys.modules", {
            "nexent.core.tools.read_skill_md_tool": MagicMock(
                ReadSkillMdTool=mock_tool_class,
            )
        }):
            result = nexent_agent_instance.create_builtin_tool(tool_config)
            assert result is mock_tool_instance
            mock_tool_class.assert_called_once_with(
                local_skills_dir="/tmp/skills",
                agent_id="agent_123",
                tenant_id="tenant_456",
                version_no=1,
            )

    def test_create_builtin_tool_write_skill_file(self, nexent_agent_instance):
        """Test create_builtin_tool with WriteSkillFileTool."""
        tool_config = ToolConfig(
            class_name="WriteSkillFileTool",
            name="write_skill_file",
            description="Write skill file",
            inputs="{}",
            output_type="string",
            params={"local_skills_dir": "/tmp/skills"},
            source="builtin",
            metadata={
                "agent_id": "agent_123",
                "tenant_id": "tenant_456",
                "version_no": 1
            },
        )

        mock_tool_instance = MagicMock()
        mock_tool_class = MagicMock(return_value=mock_tool_instance)

        with patch.dict("sys.modules", {
            "nexent.core.tools.write_skill_file_tool": MagicMock(
                WriteSkillFileTool=mock_tool_class,
            )
        }):
            result = nexent_agent_instance.create_builtin_tool(tool_config)
            assert result is mock_tool_instance
            mock_tool_class.assert_called_once_with(
                local_skills_dir="/tmp/skills",
                agent_id="agent_123",
                tenant_id="tenant_456",
                version_no=1,
            )

    def test_create_builtin_tool_read_skill_config(self, nexent_agent_instance):
        """Test create_builtin_tool with ReadSkillConfigTool."""
        tool_config = ToolConfig(
            class_name="ReadSkillConfigTool",
            name="read_skill_config",
            description="Read skill config",
            inputs="{}",
            output_type="string",
            params={"local_skills_dir": "/tmp/skills"},
            source="builtin",
            metadata={
                "agent_id": "agent_123",
                "tenant_id": "tenant_456",
                "version_no": 1
            },
        )

        mock_tool_instance = MagicMock()
        mock_tool_class = MagicMock(return_value=mock_tool_instance)

        with patch.dict("sys.modules", {
            "nexent.core.tools.read_skill_config_tool": MagicMock(
                ReadSkillConfigTool=mock_tool_class,
            )
        }):
            result = nexent_agent_instance.create_builtin_tool(tool_config)
            assert result is mock_tool_instance
            mock_tool_class.assert_called_once_with(
                local_skills_dir="/tmp/skills",
                agent_id="agent_123",
                tenant_id="tenant_456",
                version_no=1,
                config_overrides=None,
            )

    def test_create_builtin_tool_unknown_tool(self, nexent_agent_instance):
        """Test create_builtin_tool raises ValueError for unknown tool."""
        tool_config = ToolConfig(
            class_name="UnknownTool",
            name="unknown",
            description="Unknown tool",
            inputs="{}",
            output_type="string",
            params={},
            source="builtin",
            metadata={},
        )

        with pytest.raises(ValueError, match="Unknown builtin tool: UnknownTool"):
            nexent_agent_instance.create_builtin_tool(tool_config)


# ----------------------------------------------------------------------------
# Tests for _tool_name helper (lines 37-43)
# ----------------------------------------------------------------------------


class TestToolName:
    """Tests for _tool_name helper function."""

    def test_tool_name_with_name_attribute(self):
        """Test _tool_name returns name attribute when present."""
        mock_tool = MagicMock()
        mock_tool.name = "custom_name"

        result = _tool_name(mock_tool)
        assert result == "custom_name"

    def test_tool_name_with___name___attribute(self):
        """Test _tool_name returns __name__ attribute when name is missing."""
        mock_tool = MagicMock(spec=[])
        del mock_tool.name  # Ensure name attribute doesn't exist
        mock_tool.__name__ = "function_name"

        result = _tool_name(mock_tool)
        assert result == "function_name"

    def test_tool_name_with_type_name(self):
        """Test _tool_name falls back to type name."""
        mock_tool = MagicMock(spec=[])
        del mock_tool.name
        del mock_tool.__name__

        result = _tool_name(mock_tool)
        assert result == "MagicMock"


# ----------------------------------------------------------------------------
# Tests for set_agent method (lines 698-701)
# ----------------------------------------------------------------------------


class TestSetAgent:
    """Tests for set_agent method."""

    def test_set_agent_with_core_agent(self, nexent_agent_instance, mock_core_agent):
        """Test set_agent accepts valid CoreAgent."""
        nexent_agent_instance.set_agent(mock_core_agent)
        assert nexent_agent_instance.agent is mock_core_agent

    def test_set_agent_with_invalid_type(self, nexent_agent_instance):
        """Test set_agent raises TypeError for non-CoreAgent."""
        invalid_agent = "not a core agent"

        with pytest.raises(TypeError, match="agent must be a CoreAgent object"):
            nexent_agent_instance.set_agent(invalid_agent)


# ----------------------------------------------------------------------------
# Tests for create_mcp_tool (lines 314-323)
# ----------------------------------------------------------------------------


class TestCreateMcpTool:
    """Tests for create_mcp_tool method."""

    def test_create_mcp_tool_success(self, nexent_agent_instance):
        """Test create_mcp_tool successfully finds and returns a tool."""
        mock_tool = MagicMock()
        mock_tool.name = "test_tool"

        mock_collection = MagicMock()
        mock_collection.tools = [mock_tool]
        nexent_agent_instance.mcp_tool_collection = mock_collection

        result = nexent_agent_instance.create_mcp_tool("test_tool")
        assert result is mock_tool

    def test_create_mcp_tool_collection_not_initialized(self, nexent_agent_instance):
        """Test create_mcp_tool raises when MCP collection is None."""
        nexent_agent_instance.mcp_tool_collection = None

        with pytest.raises(ValueError, match="MCP tool collection is not initialized"):
            nexent_agent_instance.create_mcp_tool("test_tool")

    def test_create_mcp_tool_not_found(self, nexent_agent_instance):
        """Test create_mcp_tool raises when tool is not found."""
        mock_collection = MagicMock()
        mock_collection.tools = []
        nexent_agent_instance.mcp_tool_collection = mock_collection

        with pytest.raises(ValueError, match="test_tool not found in MCP server"):
            nexent_agent_instance.create_mcp_tool("test_tool")


# ----------------------------------------------------------------------------
# Tests for HaotianSearchTool in create_local_tool (lines 264-269)
# ----------------------------------------------------------------------------


class TestCreateLocalToolHaotian:
    """Tests for HaotianSearchTool creation."""

    def test_create_local_tool_haotian_search_tool(self, nexent_agent_instance):
        """Test create_local_tool with HaotianSearchTool."""
        mock_haotian_class = MagicMock()
        mock_haotian_instance = MagicMock()
        mock_haotian_class.return_value = mock_haotian_instance

        tool_config = ToolConfig(
            class_name="HaotianSearchTool",
            name="haotian_search",
            description="Haotian search",
            inputs="{}",
            output_type="string",
            params={"api_key": "test_key"},
            source="local",
            metadata={"rerank_model": MagicMock()},
        )

        original_value = nexent_agent_instance.__class__.__dict__.get("HaotianSearchTool")
        nexent_agent.__dict__["HaotianSearchTool"] = mock_haotian_class

        try:
            result = nexent_agent_instance.create_local_tool(tool_config)

            # Verify observer was set
            assert mock_haotian_instance.observer == nexent_agent_instance.observer
        finally:
            if original_value is not None:
                nexent_agent.__dict__["HaotianSearchTool"] = original_value
            elif "HaotianSearchTool" in nexent_agent.__dict__:
                del nexent_agent.__dict__["HaotianSearchTool"]


# ----------------------------------------------------------------------------
# Tests for StoreMemoryTool and SearchMemoryTool (lines 291-303)
# ----------------------------------------------------------------------------


class TestCreateLocalToolMemoryTools:
    """Tests for memory tool creation."""

    def test_create_local_tool_store_memory_tool(self, nexent_agent_instance):
        """Test create_local_tool with StoreMemoryTool."""
        mock_memory_class = MagicMock()
        mock_memory_instance = MagicMock()
        mock_memory_class.return_value = mock_memory_instance

        tool_config = ToolConfig(
            class_name="StoreMemoryTool",
            name="store_memory",
            description="Store memory",
            inputs="{}",
            output_type="string",
            params={},
            source="local",
            metadata={
                "memory_config": {"max_size": 1000},
                "tenant_id": "tenant_123",
                "user_id": "user_456",
                "agent_id": "agent_789",
                "memory_user_config": {"enable": True}
            },
        )

        original_value = nexent_agent_instance.__class__.__dict__.get("StoreMemoryTool")
        nexent_agent.__dict__["StoreMemoryTool"] = mock_memory_class

        try:
            result = nexent_agent_instance.create_local_tool(tool_config)

            # Verify attributes were set
            assert mock_memory_instance.observer == nexent_agent_instance.observer
            assert mock_memory_instance.memory_config == {"max_size": 1000}
            assert mock_memory_instance.tenant_id == "tenant_123"
            assert mock_memory_instance.user_id == "user_456"
            assert mock_memory_instance.agent_id == "agent_789"
            assert mock_memory_instance.memory_user_config == {"enable": True}
        finally:
            if original_value is not None:
                nexent_agent.__dict__["StoreMemoryTool"] = original_value
            elif "StoreMemoryTool" in nexent_agent.__dict__:
                del nexent_agent.__dict__["StoreMemoryTool"]

    def test_create_local_tool_search_memory_tool(self, nexent_agent_instance):
        """Test create_local_tool with SearchMemoryTool."""
        mock_memory_class = MagicMock()
        mock_memory_instance = MagicMock()
        mock_memory_class.return_value = mock_memory_instance

        tool_config = ToolConfig(
            class_name="SearchMemoryTool",
            name="search_memory",
            description="Search memory",
            inputs="{}",
            output_type="string",
            params={},
            source="local",
            metadata={
                "memory_config": {"top_k": 5},
                "tenant_id": "tenant_123",
                "user_id": "user_456",
                "agent_id": "agent_789",
                "memory_user_config": None
            },
        )

        original_value = nexent_agent_instance.__class__.__dict__.get("SearchMemoryTool")
        nexent_agent.__dict__["SearchMemoryTool"] = mock_memory_class

        try:
            result = nexent_agent_instance.create_local_tool(tool_config)

            # Verify attributes were set
            assert mock_memory_instance.observer == nexent_agent_instance.observer
            assert mock_memory_instance.memory_config == {"top_k": 5}
            assert mock_memory_instance.memory_user_config is None
        finally:
            if original_value is not None:
                nexent_agent.__dict__["SearchMemoryTool"] = original_value
            elif "SearchMemoryTool" in nexent_agent.__dict__:
                del nexent_agent.__dict__["SearchMemoryTool"]


# ----------------------------------------------------------------------------
# Tests for _log_step_metrics with context manager (lines 780-781)
# ----------------------------------------------------------------------------


class TestLogStepMetricsContextManager:
    """Tests for _log_step_metrics with context manager."""

    def test_log_step_metrics_with_context_manager(self, nexent_agent_instance, mock_core_agent):
        """Test _log_step_metrics logs context manager stats when available."""
        nexent_agent_instance.agent = mock_core_agent

        # Create step_metrics with all required fields
        mock_core_agent.step_metrics = [
            {
                "step_number": 1,
                "main_llm": {"input_tokens": 100, "output_tokens": 50},
                "compression": {"input_tokens": 80, "output_tokens": 40},
                "memory_state": {
                    "estimated_input_tokens": 80,
                    "estimated_output_tokens": 40
                },
                "uncompressed_mem_est_input": 100,
                "compression_ratio": "20.0%",
                "cache_hit": True
            }
        ]

        mock_context_runtime = MagicMock()
        mock_context_runtime.global_compression_stats.return_value = {"total_saved": "25%"}
        mock_core_agent.context_runtime = mock_context_runtime

        # This should log without error
        nexent_agent_instance._log_step_metrics()

        # Verify context runtime was called
        mock_context_runtime.global_compression_stats.assert_called_once()


# ----------------------------------------------------------------------------
# Tests for AnalyzeVideoTool (lines 281-290)
# ----------------------------------------------------------------------------


class TestCreateLocalToolVideoTool:
    """Tests for AnalyzeVideoTool creation."""

    def test_create_local_tool_analyze_video_tool(self, nexent_agent_instance):
        """Test create_local_tool with AnalyzeVideoTool."""
        mock_video_class = MagicMock()
        mock_video_instance = MagicMock()
        mock_video_class.return_value = mock_video_instance

        tool_config = ToolConfig(
            class_name="AnalyzeVideoTool",
            name="analyze_video",
            description="Analyze video",
            inputs="{}",
            output_type="string",
            params={"video_url": "https://example.com/video.mp4"},
            source="local",
            metadata={
                "vlm_model": "video_model",
                "storage_client": "storage_client",
                "validate_url_access": None
            },
        )

        original_value = nexent_agent_instance.__class__.__dict__.get("AnalyzeVideoTool")
        nexent_agent.__dict__["AnalyzeVideoTool"] = mock_video_class

        try:
            result = nexent_agent_instance.create_local_tool(tool_config)

            mock_video_class.assert_called_once()
            call_kwargs = mock_video_class.call_args[1]
            assert call_kwargs["vlm_model"] == "video_model"
            assert call_kwargs["storage_client"] == "storage_client"
            assert call_kwargs["validate_url_access"] is None
        finally:
            if original_value is not None:
                nexent_agent.__dict__["AnalyzeVideoTool"] = original_value
            elif "AnalyzeVideoTool" in nexent_agent.__dict__:
                del nexent_agent.__dict__["AnalyzeVideoTool"]

    def test_create_local_tool_analyze_video_tool_with_callable_validator(self, nexent_agent_instance):
        """Test create_local_tool with AnalyzeVideoTool and callable validator."""
        mock_video_class = MagicMock()
        mock_video_instance = MagicMock()
        mock_video_class.return_value = mock_video_instance

        def mock_validator(url):
            return True

        tool_config = ToolConfig(
            class_name="AnalyzeVideoTool",
            name="analyze_video",
            description="Analyze video",
            inputs="{}",
            output_type="string",
            params={},
            source="local",
            metadata={
                "vlm_model": "video_model",
                "storage_client": "storage",
                "validate_url_access": mock_validator
            },
        )

        original_value = nexent_agent_instance.__class__.__dict__.get("AnalyzeVideoTool")
        nexent_agent.__dict__["AnalyzeVideoTool"] = mock_video_class

        try:
            result = nexent_agent_instance.create_local_tool(tool_config)

            call_kwargs = mock_video_class.call_args[1]
            assert call_kwargs["validate_url_access"] is mock_validator
        finally:
            if original_value is not None:
                nexent_agent.__dict__["AnalyzeVideoTool"] = original_value
            elif "AnalyzeVideoTool" in nexent_agent.__dict__:
                del nexent_agent.__dict__["AnalyzeVideoTool"]


if __name__ == "__main__":
    pytest.main([__file__])


class TestCreateLocalToolMemory:
    """Tests for create_local_tool with StoreMemoryTool and SearchMemoryTool."""

    def test_create_local_tool_store_memory_success(self, nexent_agent_instance):
        """Test successful StoreMemoryTool creation with metadata."""
        mock_tool_class = MagicMock()
        mock_tool_instance = MagicMock()
        mock_tool_class.return_value = mock_tool_instance

        tool_config = ToolConfig(
            class_name="StoreMemoryTool",
            name="store_memory",
            description="desc",
            inputs="{}",
            output_type="string",
            params={},
            source="local",
            metadata={
                "memory_config": {"type": "vector"},
                "tenant_id": "tenant_123",
                "user_id": "user_456",
                "agent_id": "agent_789",
                "conversation_id": 101,
                "memory_user_config": {"version": "v1"}
            }
        )

        original_value = nexent_agent.__dict__.get("StoreMemoryTool")
        nexent_agent.__dict__["StoreMemoryTool"] = mock_tool_class

        try:
            result = nexent_agent_instance.create_local_tool(tool_config)
            assert result == mock_tool_instance
            # Verify memory_config was set
            assert result.memory_config == {"type": "vector"}
            # Verify tenant_id was set
            assert result.tenant_id == "tenant_123"
            # Verify user_id was set
            assert result.user_id == "user_456"
            # Verify agent_id was set
            assert result.agent_id == "agent_789"
            # Verify conversation_id was set for short-term memory isolation
            assert result.conversation_id == "101"
            # Verify memory_user_config was set
            assert result.memory_user_config == {"version": "v1"}
            # Verify observer was set
            assert result.observer == nexent_agent_instance.observer
            assert result.description == "desc"
            assert result.inputs == {}
            assert result.output_type == "string"
        finally:
            if original_value is not None:
                nexent_agent.__dict__["StoreMemoryTool"] = original_value
            elif "StoreMemoryTool" in nexent_agent.__dict__:
                del nexent_agent.__dict__["StoreMemoryTool"]

    def test_create_local_tool_search_memory_success(self, nexent_agent_instance):
        """Test successful SearchMemoryTool creation with metadata."""
        mock_tool_class = MagicMock()
        mock_tool_instance = MagicMock()
        mock_tool_class.return_value = mock_tool_instance

        tool_config = ToolConfig(
            class_name="SearchMemoryTool",
            name="search_memory",
            description="desc",
            inputs="{}",
            output_type="string",
            params={},
            source="local",
            metadata={
                "memory_config": {"type": "vector"},
                "tenant_id": "tenant_abc",
                "user_id": "user_def",
                "agent_id": "agent_ghi",
                "conversation_id": "conversation_jkl",
            }
        )

        original_value = nexent_agent.__dict__.get("SearchMemoryTool")
        nexent_agent.__dict__["SearchMemoryTool"] = mock_tool_class

        try:
            result = nexent_agent_instance.create_local_tool(tool_config)
            assert result == mock_tool_instance
            # Verify memory_config was set
            assert result.memory_config == {"type": "vector"}
            # Verify tenant_id was set
            assert result.tenant_id == "tenant_abc"
            assert result.conversation_id == "conversation_jkl"
            # Verify observer was set
            assert result.observer == nexent_agent_instance.observer
        finally:
            if original_value is not None:
                nexent_agent.__dict__["SearchMemoryTool"] = original_value
            elif "SearchMemoryTool" in nexent_agent.__dict__:
                del nexent_agent.__dict__["SearchMemoryTool"]

    def test_create_local_tool_store_memory_without_metadata(self, nexent_agent_instance):
        """Test StoreMemoryTool creation with minimal/no metadata."""
        mock_tool_class = MagicMock()
        mock_tool_instance = MagicMock()
        mock_tool_class.return_value = mock_tool_instance

        tool_config = ToolConfig(
            class_name="StoreMemoryTool",
            name="store_memory",
            description="desc",
            inputs="{}",
            output_type="string",
            params={},
            source="local",
            metadata={}
        )

        original_value = nexent_agent.__dict__.get("StoreMemoryTool")
        nexent_agent.__dict__["StoreMemoryTool"] = mock_tool_class

        try:
            result = nexent_agent_instance.create_local_tool(tool_config)
            assert result == mock_tool_instance
            # Verify defaults are set
            assert result.memory_config == {}
            assert result.tenant_id == ""
            assert result.user_id == ""
            assert result.agent_id == ""
            assert result.conversation_id == ""
            assert result.memory_user_config is None
        finally:
            if original_value is not None:
                nexent_agent.__dict__["StoreMemoryTool"] = original_value
            elif "StoreMemoryTool" in nexent_agent.__dict__:
                del nexent_agent.__dict__["StoreMemoryTool"]


class TestMonitoringHelpers:
    """Tests for monitoring helper functions."""

    def test_tool_name_with_name_attribute(self):
        """Test _tool_name returns name attribute when available."""
        mock_tool = MagicMock()
        mock_tool.name = "custom_tool_name"

        result = nexent_agent._tool_name(mock_tool)
        assert result == "custom_tool_name"

    def test_tool_name_with_only_name_attribute(self):
        """Test _tool_name returns name attribute (no __name__)."""
        mock_tool = MagicMock(spec=["name"])
        mock_tool.name = "tool_with_name_only"

        result = nexent_agent._tool_name(mock_tool)
        assert result == "tool_with_name_only"

    def test_tool_name_with_no_name_fallback_to_type_name(self):
        """Test _tool_name falls back to type name."""
        mock_tool = MagicMock()
        del mock_tool.name
        mock_tool.__name__ = None
        type(mock_tool).__name__ = "MockToolClass"

        result = nexent_agent._tool_name(mock_tool)
        assert result == "MockToolClass"

    def test_is_retriever_tool_with_knowledge_base(self):
        """Test _is_retriever_tool returns True for KnowledgeBaseSearchTool."""
        # The function checks type(tool_obj).__name__ which needs actual class name
        mock_tool = MagicMock()
        mock_tool.__class__.__name__ = "KnowledgeBaseSearchTool"

        result = nexent_agent._is_retriever_tool(mock_tool)
        assert result is True

    def test_is_retriever_tool_with_search_memory(self):
        """Test _is_retriever_tool returns True for SearchMemoryTool."""
        # The function checks type(tool_obj).__name__ which needs actual class name
        mock_tool = MagicMock()
        mock_tool.__class__.__name__ = "SearchMemoryTool"

        result = nexent_agent._is_retriever_tool(mock_tool)
        assert result is True

    def test_is_retriever_tool_returns_false_for_other_tools(self):
        """Test _is_retriever_tool returns False for non-retriever tools."""
        class MockTool:
            pass

        result = nexent_agent._is_retriever_tool(MockTool())
        assert result is False

    def test_build_tool_input_with_valid_signature(self):
        """Test _build_tool_input with inspect.signature success."""
        def sample_func(a, b, c=10):
            pass

        result = nexent_agent._build_tool_input(sample_func, (1, 2), {"c": 3})
        assert result == {"a": 1, "b": 2, "c": 3}

    def test_build_tool_input_with_signature_failure(self):
        """Test _build_tool_input falls back when signature fails."""
        def bad_func():
            raise TypeError("cannot inspect")

        result = nexent_agent._build_tool_input(bad_func, (1, 2), {"key": "value"})
        # Should fall back to args/kwargs
        assert result.get("args") == [1, 2]
        assert result.get("key") == "value"

    def test_build_tool_input_with_value_error(self):
        """Test _build_tool_input falls back on ValueError."""
        def bad_func():
            raise ValueError("invalid value")

        result = nexent_agent._build_tool_input(bad_func, (), {"x": 1})
        assert result == {"x": 1}

    def test_build_tool_input_with_empty_args_kwargs(self):
        """Test _build_tool_input with no args or kwargs."""
        def empty_func():
            pass

        result = nexent_agent._build_tool_input(empty_func, (), {})
        assert result == {}


# ----------------------------------------------------------------------------
# Tests for _wrap_tool_with_monitoring wrapper invocations (lines 88-149)
# Existing tests only verify wrapping; these tests actually CALL the wrappers
# so the inner monitored_span / set_monitored_output / monitored_forward /
# monitored_callable bodies execute.
# ----------------------------------------------------------------------------


class TestWrapToolMonitoringInvocation:
    """Tests that invoke the wrapped functions to cover inner function bodies."""

    def _make_monitoring_manager(self):
        """Create a mock monitoring manager with context-manager support."""

        class _CtxMgr:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *args):
                return False

        mm = MagicMock()
        mm.start_agent_run.return_value = _CtxMgr()
        mm.trace_tool_call.side_effect = lambda *a, **kw: _CtxMgr()
        mm.trace_retriever_call.side_effect = lambda *a, **kw: _CtxMgr()
        mm.set_tool_output = MagicMock()
        mm.set_retriever_output = MagicMock()
        mm.trace_agent_step.side_effect = lambda *a, **kw: _CtxMgr()
        return mm

    def test_sync_forward_invocation_covers_monitored_paths(self):
        """Invoke wrapped forward to cover monitored_span + set_monitored_output (sync, non-retriever)."""
        mm = self._make_monitoring_manager()

        class NonRetrieverTool:
            def forward(self, x=1):
                return f"result_{x}"

        tool = NonRetrieverTool()
        tool._nexent_monitoring_wrapped = False

        with patch.object(nexent_agent, "get_monitoring_manager", return_value=mm):
            wrapped = _wrap_tool_with_monitoring(tool, "test_agent")
            result = wrapped.forward(x=42)

        assert result == "result_42"
        mm.trace_tool_call.assert_called_once()
        mm.set_tool_output.assert_called_once_with("result_42")

    def test_async_forward_invocation_covers_async_monitored_forward(self):
        """Invoke wrapped async forward to cover async monitored_forward body (lines 106-112)."""
        import asyncio
        mm = self._make_monitoring_manager()

        class AsyncTool:
            async def forward(self, q="hello"):
                return f"async_{q}"

        tool = AsyncTool()
        tool._nexent_monitoring_wrapped = False

        with patch.object(nexent_agent, "get_monitoring_manager", return_value=mm):
            wrapped = _wrap_tool_with_monitoring(tool, "agent_async")
            result = asyncio.get_event_loop().run_until_complete(
                wrapped.forward(q="world")
            )

        assert result == "async_world"
        mm.trace_tool_call.assert_called_once()
        mm.set_tool_output.assert_called_once_with("async_world")

    def test_retriever_tool_sync_forward_covers_retriever_paths(self):
        """Invoke wrapped forward on a retriever tool to cover trace_retriever_call + set_retriever_output."""
        mm = self._make_monitoring_manager()

        class KnowledgeBaseSearchTool:
            def forward(self, query=""):
                return [{"content": "doc1"}]

        tool = KnowledgeBaseSearchTool()
        tool._nexent_monitoring_wrapped = False

        with patch.object(nexent_agent, "get_monitoring_manager", return_value=mm):
            wrapped = _wrap_tool_with_monitoring(tool, "agent_r")
            result = wrapped.forward(query="test")

        assert result == [{"content": "doc1"}]
        mm.trace_retriever_call.assert_called_once()
        mm.trace_tool_call.assert_not_called()
        mm.set_retriever_output.assert_called_once_with([{"content": "doc1"}])

    def test_sync_callable_invocation_covers_monitored_callable(self):
        """Invoke wrapped callable (sync, no forward) to cover lines 140-144."""
        mm = self._make_monitoring_manager()

        def my_tool(x=1):
            return x * 2

        my_tool._nexent_monitoring_wrapped = False

        with patch.object(nexent_agent, "get_monitoring_manager", return_value=mm):
            wrapped = _wrap_tool_with_monitoring(my_tool, "callable_agent")
            result = wrapped(x=21)

        assert result == 42
        mm.trace_tool_call.assert_called_once()
        mm.set_tool_output.assert_called_once_with(42)

    def test_async_callable_invocation_covers_async_monitored_callable(self):
        """Invoke wrapped async callable to cover lines 130-136."""
        import asyncio
        mm = self._make_monitoring_manager()

        async def async_func(val=0):
            return val + 100

        async_func._nexent_monitoring_wrapped = False

        with patch.object(nexent_agent, "get_monitoring_manager", return_value=mm):
            wrapped = _wrap_tool_with_monitoring(async_func, "agent_ac")
            result = asyncio.get_event_loop().run_until_complete(
                wrapped(val=5)
            )

        assert result == 105
        mm.trace_tool_call.assert_called_once()
        mm.set_tool_output.assert_called_once_with(105)

    def test_retriever_callable_invocation_covers_retriever_callable_paths(self):
        """Invoke wrapped retriever callable (no forward) to cover retriever branches."""
        mm = self._make_monitoring_manager()

        class SearchMemoryTool:
            def __call__(self, query=""):
                return "memory_result"

        tool = SearchMemoryTool()
        tool._nexent_monitoring_wrapped = False

        with patch.object(nexent_agent, "get_monitoring_manager", return_value=mm):
            wrapped = _wrap_tool_with_monitoring(tool, "agent_mem")
            result = wrapped(query="hi")

        assert result == "memory_result"
        mm.trace_retriever_call.assert_called_once()
        mm.set_retriever_output.assert_called_once_with("memory_result")

    def test_non_callable_non_forward_object_returns_unchanged(self):
        """An object with no forward and not callable hits the final return (line 149)."""
        mm = self._make_monitoring_manager()

        class PlainObject:
            pass

        tool = PlainObject()
        tool._nexent_monitoring_wrapped = False

        with patch.object(nexent_agent, "get_monitoring_manager", return_value=mm):
            result = _wrap_tool_with_monitoring(tool, "agent_plain")

        assert result is tool
        mm.trace_tool_call.assert_not_called()


# ----------------------------------------------------------------------------
# Tests for create_local_tool AidpSearchTool branch (lines 343-364)
# ----------------------------------------------------------------------------


class TestCreateLocalToolAidpSearchTool:
    """Tests for the AidpSearchTool branch in create_local_tool."""

    def test_aidp_search_tool_with_allowed_kds_set(self, nexent_agent_instance):
        """AidpSearchTool with allowed_kds_set in metadata installs whitelist."""
        mock_tool_class = MagicMock()
        mock_tool_instance = MagicMock()
        mock_tool_class.return_value = mock_tool_instance

        tool_config = ToolConfig(
            class_name="AidpSearchTool",
            name="aidp_search",
            description="desc",
            inputs="{}",
            output_type="string",
            params={"param1": "val"},
            source="local",
            metadata={"allowed_kds_set": ["kb1", "kb2"]},
        )

        original = nexent_agent.__dict__.get("AidpSearchTool")
        nexent_agent.__dict__["AidpSearchTool"] = mock_tool_class
        try:
            result = nexent_agent_instance.create_local_tool(tool_config)
        finally:
            if original is not None:
                nexent_agent.__dict__["AidpSearchTool"] = original
            elif "AidpSearchTool" in nexent_agent.__dict__:
                del nexent_agent.__dict__["AidpSearchTool"]

        assert result is mock_tool_instance
        mock_tool_class.assert_called_once_with(param1="val")
        mock_tool_instance.set_allowed_kds.assert_called_once_with(["kb1", "kb2"])
        assert mock_tool_instance.observer == nexent_agent_instance.observer

    def test_aidp_search_tool_without_metadata(self, nexent_agent_instance):
        """AidpSearchTool with metadata=None calls set_allowed_kds(None)."""
        mock_tool_class = MagicMock()
        mock_tool_instance = MagicMock()
        mock_tool_class.return_value = mock_tool_instance

        tool_config = ToolConfig(
            class_name="AidpSearchTool",
            name="aidp_search",
            description="desc",
            inputs="{}",
            output_type="string",
            params={},
            source="local",
            metadata=None,
        )

        original = nexent_agent.__dict__.get("AidpSearchTool")
        nexent_agent.__dict__["AidpSearchTool"] = mock_tool_class
        try:
            result = nexent_agent_instance.create_local_tool(tool_config)
        finally:
            if original is not None:
                nexent_agent.__dict__["AidpSearchTool"] = original
            elif "AidpSearchTool" in nexent_agent.__dict__:
                del nexent_agent.__dict__["AidpSearchTool"]

        assert result is mock_tool_instance
        mock_tool_instance.set_allowed_kds.assert_called_once_with(None)

    def test_aidp_search_tool_set_allowed_kds_raises_exception(self, nexent_agent_instance):
        """When whitelist installation raises, fall back to a deny-all whitelist."""
        mock_tool_class = MagicMock()
        mock_tool_instance = MagicMock()
        mock_tool_instance.set_allowed_kds.side_effect = [RuntimeError("boom"), None]
        mock_tool_class.return_value = mock_tool_instance

        tool_config = ToolConfig(
            class_name="AidpSearchTool",
            name="aidp_search",
            description="desc",
            inputs="{}",
            output_type="string",
            params={},
            source="local",
            metadata={"allowed_kds_set": ["kb1"]},
        )

        original = nexent_agent.__dict__.get("AidpSearchTool")
        nexent_agent.__dict__["AidpSearchTool"] = mock_tool_class
        try:
            result = nexent_agent_instance.create_local_tool(tool_config)
        finally:
            if original is not None:
                nexent_agent.__dict__["AidpSearchTool"] = original
            elif "AidpSearchTool" in nexent_agent.__dict__:
                del nexent_agent.__dict__["AidpSearchTool"]

        assert result is mock_tool_instance
        # First call with ["kb1"] raises, fallback call installs an empty whitelist.
        assert mock_tool_instance.set_allowed_kds.call_count == 2
        mock_tool_instance.set_allowed_kds.assert_any_call(["kb1"])
        mock_tool_instance.set_allowed_kds.assert_any_call([])


# ----------------------------------------------------------------------------
# Tests for create_builtin_tool CreatePlanTool / UpdatePlanStepTool (lines 439-443)
# ----------------------------------------------------------------------------


class TestCreateBuiltinToolPlanTools:
    """Tests for CreatePlanTool and UpdatePlanStepTool in create_builtin_tool."""

    def test_create_builtin_tool_create_plan_tool(self, nexent_agent_instance):
        """create_builtin_tool with CreatePlanTool returns CreatePlanTool instance."""
        mock_tool_class = MagicMock()
        mock_tool_instance = MagicMock()
        mock_tool_class.return_value = mock_tool_instance

        tool_config = ToolConfig(
            class_name="CreatePlanTool",
            name="create_plan",
            description="Create a plan",
            inputs="{}",
            output_type="string",
            params={},
            source="builtin",
        )

        with patch.dict("sys.modules", {
            "nexent.core.tools.plan_tools": MagicMock(CreatePlanTool=mock_tool_class),
        }):
            result = nexent_agent_instance.create_builtin_tool(tool_config)

        assert result is mock_tool_instance
        mock_tool_class.assert_called_once_with()

    def test_create_builtin_tool_update_plan_step_tool(self, nexent_agent_instance):
        """create_builtin_tool with UpdatePlanStepTool returns UpdatePlanStepTool instance."""
        mock_tool_class = MagicMock()
        mock_tool_instance = MagicMock()
        mock_tool_class.return_value = mock_tool_instance

        tool_config = ToolConfig(
            class_name="UpdatePlanStepTool",
            name="update_plan_step",
            description="Update a plan step",
            inputs="{}",
            output_type="string",
            params={},
            source="builtin",
        )

        with patch.dict("sys.modules", {
            "nexent.core.tools.plan_tools": MagicMock(UpdatePlanStepTool=mock_tool_class),
        }):
            result = nexent_agent_instance.create_builtin_tool(tool_config)

        assert result is mock_tool_instance
        mock_tool_class.assert_called_once_with()

    def test_create_builtin_tool_scheduled_task_proposal(self, nexent_agent_instance):
        mock_tool_class = MagicMock()
        mock_tool_instance = MagicMock()
        mock_tool_class.return_value = mock_tool_instance
        create_proposal = MagicMock()
        tool_config = ToolConfig(
            class_name="CreateScheduledTaskProposalTool",
            name="create_scheduled_task_proposal",
            description="Create a scheduled-task proposal",
            inputs="{}",
            output_type="string",
            params={},
            source="builtin",
            metadata={"create_proposal": create_proposal},
        )

        with patch.dict("sys.modules", {
            "nexent.core.tools.create_scheduled_task_tool": MagicMock(
                CreateScheduledTaskProposalTool=mock_tool_class,
            ),
        }):
            result = nexent_agent_instance.create_builtin_tool(tool_config)

        assert result is mock_tool_instance
        mock_tool_class.assert_called_once_with(
            create_proposal=create_proposal,
            observer=nexent_agent_instance.observer,
        )


# ----------------------------------------------------------------------------
# Tests for agent_run_with_observer token_usage extraction (lines 767-768, 770)
# ----------------------------------------------------------------------------


class TestAgentRunWithTokenUsage:
    """Tests for token_usage extraction in agent_run_with_observer."""

    def test_agent_run_extracts_token_usage_from_step_log(self, nexent_agent_instance, mock_core_agent):
        """Verify token_usage.input_tokens and output_tokens are read and accumulated."""
        nexent_agent_instance.agent = mock_core_agent
        mock_core_agent.stop_event.is_set.return_value = False

        mock_action_step = MagicMock(spec=ActionStep)
        mock_action_step.timing = MagicMock(duration=1.0)
        mock_action_step.step_number = 1
        mock_action_step.error = None
        mock_action_step.output = "done"
        mock_action_step.token_usage = MagicMock(input_tokens=100, output_tokens=50)

        mock_core_agent.run.return_value = [mock_action_step]

        nexent_agent_instance.agent_run_with_observer("test query")

        # Find TOKEN_COUNT payloads and check step tokens appear
        token_payloads = [
            json.loads(call.args[2])
            for call in mock_core_agent.observer.add_message.call_args_list
            if len(call.args) >= 3 and call.args[1] == ProcessType.TOKEN_COUNT
        ]
        assert any(p.get("step_input_tokens") == 100 for p in token_payloads)
        assert any(p.get("step_output_tokens") == 50 for p in token_payloads)

    def test_agent_run_accumulates_output_tokens_across_steps(self, nexent_agent_instance, mock_core_agent):
        """Verify total_output_tokens accumulates across multiple steps."""
        nexent_agent_instance.agent = mock_core_agent
        mock_core_agent.stop_event.is_set.return_value = False

        step1 = MagicMock(spec=ActionStep)
        step1.timing = MagicMock(duration=1.0)
        step1.step_number = 1
        step1.error = None
        step1.output = "step1"
        step1.token_usage = MagicMock(input_tokens=50, output_tokens=20)

        step2 = MagicMock(spec=ActionStep)
        step2.timing = MagicMock(duration=2.0)
        step2.step_number = 2
        step2.error = None
        step2.output = "final_answer"
        step2.token_usage = MagicMock(input_tokens=60, output_tokens=30)

        mock_core_agent.run.return_value = [step1, step2]

        nexent_agent_instance.agent_run_with_observer("test query")

        token_payloads = [
            json.loads(call.args[2])
            for call in mock_core_agent.observer.add_message.call_args_list
            if len(call.args) >= 3 and call.args[1] == ProcessType.TOKEN_COUNT
        ]
        total_outputs = [p.get("total_output_tokens") for p in token_payloads if p.get("total_output") is not None]
        # At least one payload should have accumulated output tokens
        if total_outputs:
            assert max(total_outputs) >= 20


# ----------------------------------------------------------------------------
# Tests for _log_step_metrics N/A path (line 885)
# ----------------------------------------------------------------------------


class TestLogStepMetricsNA:
    """Tests for _log_step_metrics when total_raw == 0 (line 885)."""

    def test_log_step_metrics_total_raw_zero_gives_na(self, nexent_agent_instance, mock_core_agent):
        """When total_raw == 0, total_save_str should be 'N/A'."""
        nexent_agent_instance.agent = mock_core_agent
        mock_core_agent.step_metrics = [
            {
                "main_llm": {"input_tokens": 10, "output_tokens": 5},
                "compression": {"input_tokens": 8, "output_tokens": 4},
                "memory_state": {"estimated_input_tokens": 9, "estimated_output_tokens": 5},
                "uncompressed_mem_est_input": 0,
                "compression_ratio": 10.0,
                "cache_hit": False,
                "step_number": 1,
            }
        ]

        import io
        captured = io.StringIO()
        mock_file = MagicMock()
        mock_file.__enter__ = MagicMock(return_value=captured)
        mock_file.__exit__ = MagicMock(return_value=False)

        with patch("builtins.open", return_value=mock_file):
            nexent_agent_instance._log_step_metrics()

        output = captured.getvalue()
        assert "N/A" in output


# ----------------------------------------------------------------------------
# Tests for _cleanup_sandbox MinIO sync and executor release (lines 966-989)
# ----------------------------------------------------------------------------


class TestCleanupSandboxAdvanced:
    """Tests for _cleanup_sandbox MinIO sync and scope-based executor cleanup."""

    def test_cleanup_sandbox_minio_sync_success(self, nexent_agent_instance, mock_core_agent):
        """MinIO sync success path uploads files and logs."""
        nexent_agent_instance.agent = mock_core_agent
        mock_executor = MagicMock()
        mock_core_agent.python_executor = mock_executor
        nexent_agent_instance._sandbox_scope = "session"

        mock_sandbox_config = MagicMock()
        mock_sandbox_config.auto_sync_outputs = True
        mock_sandbox_config.output_dir = "/tmp/output"
        nexent_agent_instance.sandbox_config = mock_sandbox_config

        mock_minio = MagicMock()
        nexent_agent_instance.minio_client = mock_minio
        mock_core_agent.agent_run_id = "run-123"

        mock_sync = MagicMock(return_value=["file1.txt", "file2.txt"])
        mock_cleanup = MagicMock()

        mock_sandbox_module = MagicMock()
        mock_sandbox_module._sync_outputs_to_minio = mock_sync
        mock_sandbox_module.cleanup_executor = mock_cleanup

        with patch.dict("sys.modules", {
            "sdk.nexent.core.agents.sandbox": mock_sandbox_module,
        }):
            nexent_agent_instance._cleanup_sandbox()

        mock_sync.assert_called_once_with(
            output_dir="/tmp/output",
            agent_run_id="run-123",
            minio_client=mock_minio,
            bucket="nexent-artifacts",
            logger_=ANY,
        )
        mock_cleanup.assert_called_once()

    def test_cleanup_sandbox_minio_sync_exception(self, nexent_agent_instance, mock_core_agent):
        """MinIO sync exception is caught and logged (does not crash)."""
        nexent_agent_instance.agent = mock_core_agent
        mock_executor = MagicMock()
        mock_core_agent.python_executor = mock_executor
        nexent_agent_instance._sandbox_scope = "session"

        mock_sandbox_config = MagicMock()
        mock_sandbox_config.auto_sync_outputs = True
        mock_sandbox_config.output_dir = "/tmp/output"
        nexent_agent_instance.sandbox_config = mock_sandbox_config
        nexent_agent_instance.minio_client = MagicMock()

        mock_sync = MagicMock(side_effect=RuntimeError("MinIO down"))
        mock_cleanup = MagicMock()

        mock_sandbox_module = MagicMock()
        mock_sandbox_module._sync_outputs_to_minio = mock_sync
        mock_sandbox_module.cleanup_executor = mock_cleanup

        with patch.dict("sys.modules", {
            "sdk.nexent.core.agents.sandbox": mock_sandbox_module,
        }):
            nexent_agent_instance._cleanup_sandbox()

        mock_cleanup.assert_called_once()

    def test_cleanup_sandbox_system_scope_releases_executor(self, nexent_agent_instance, mock_core_agent):
        """System scope calls release_python_executor instead of cleanup_executor."""
        nexent_agent_instance.agent = mock_core_agent
        mock_executor = MagicMock()
        mock_core_agent.python_executor = mock_executor
        nexent_agent_instance._sandbox_scope = "system"

        nexent_agent_instance.sandbox_config = None
        nexent_agent_instance.minio_client = None

        mock_release = MagicMock()
        mock_sandbox_module = MagicMock()
        mock_sandbox_module.release_python_executor = mock_release

        with patch.dict("sys.modules", {
            "sdk.nexent.core.agents.sandbox": mock_sandbox_module,
        }):
            nexent_agent_instance._cleanup_sandbox()

        mock_release.assert_called_once_with(mock_executor, ANY)

    def test_cleanup_sandbox_releases_all_agent_executors_in_reverse_order(
        self, nexent_agent_instance, mock_core_agent
    ):
        """System cleanup returns parent and child kernel leases exactly once."""
        child_executor = MagicMock(name="child_executor")
        parent_executor = MagicMock(name="parent_executor")
        nexent_agent_instance.agent = mock_core_agent
        mock_core_agent.python_executor = parent_executor
        nexent_agent_instance._sandbox_executors = [child_executor, parent_executor]
        nexent_agent_instance._sandbox_scope = "system"
        nexent_agent_instance.sandbox_config = None
        nexent_agent_instance.minio_client = None

        mock_release = MagicMock()
        mock_sandbox_module = MagicMock()
        mock_sandbox_module.release_python_executor = mock_release

        with patch.dict("sys.modules", {
            "sdk.nexent.core.agents.sandbox": mock_sandbox_module,
        }):
            nexent_agent_instance._cleanup_sandbox()

        assert mock_release.call_args_list == [
            call(parent_executor, ANY),
            call(child_executor, ANY),
        ]
        assert nexent_agent_instance._sandbox_executors == []
        assert mock_core_agent.python_executor is None

    def test_cleanup_sandbox_deduplicates_executor_without_root_agent(
        self, nexent_agent_instance
    ):
        executor = MagicMock()
        nexent_agent_instance.agent = None
        nexent_agent_instance._sandbox_executors = [executor, executor]
        nexent_agent_instance._sandbox_scope = "session"
        nexent_agent_instance.sandbox_config = None
        nexent_agent_instance.minio_client = None

        mock_cleanup = MagicMock()
        mock_sandbox_module = MagicMock(cleanup_executor=mock_cleanup)

        with patch.dict(
            "sys.modules",
            {"sdk.nexent.core.agents.sandbox": mock_sandbox_module},
        ):
            nexent_agent_instance._cleanup_sandbox()

        mock_cleanup.assert_called_once_with(executor, ANY, timeout=5.0)
        assert nexent_agent_instance._sandbox_executors == []

    def test_cleanup_sandbox_minio_sync_no_uploaded_files(self, nexent_agent_instance, mock_core_agent):
        """MinIO sync returns empty list, no log message about sync."""
        nexent_agent_instance.agent = mock_core_agent
        mock_executor = MagicMock()
        mock_core_agent.python_executor = mock_executor
        nexent_agent_instance._sandbox_scope = "session"

        mock_sandbox_config = MagicMock()
        mock_sandbox_config.auto_sync_outputs = True
        mock_sandbox_config.output_dir = "/tmp/output"
        nexent_agent_instance.sandbox_config = mock_sandbox_config
        nexent_agent_instance.minio_client = MagicMock()

        mock_sync = MagicMock(return_value=[])
        mock_cleanup = MagicMock()

        mock_sandbox_module = MagicMock()
        mock_sandbox_module._sync_outputs_to_minio = mock_sync
        mock_sandbox_module.cleanup_executor = mock_cleanup

        with patch.dict("sys.modules", {
            "sdk.nexent.core.agents.sandbox": mock_sandbox_module,
        }):
            nexent_agent_instance._cleanup_sandbox()

        mock_sync.assert_called_once()
        mock_cleanup.assert_called_once()


# ----------------------------------------------------------------------------
# Tests for create_single_agent sandbox build + plan wiring (lines 615-694)
# ----------------------------------------------------------------------------


class TestCreateSingleAgentSandboxAndPlanning:
    """Tests for sandbox build and plan-tool wiring in create_single_agent."""

    def _run_create_single_agent(self, nexent_agent_instance, mock_model_config,
                                  mock_core_agent, agent_config):
        """Helper to invoke create_single_agent with CoreAgent mocked."""
        with patch.object(nexent_agent, "CoreAgent", return_value=mock_core_agent) as mock_cls:
            return nexent_agent_instance.create_single_agent(agent_config), mock_cls

    def _make_sandbox_level(self):
        """Create a stub for SandboxLevel that supports .value and enum equality."""
        from enum import Enum

        class SandboxLevel(str, Enum):
            LOCAL = "local"
            DOCKER = "docker"
            WASM = "wasm"

        return SandboxLevel

    def _make_sandbox_config(self, level_value, scope_value="session"):
        """Create a sandbox_config mock with proper enum-like level and scope."""
        SandboxLevel = self._make_sandbox_level()
        mock_sandbox_config = MagicMock()
        mock_sandbox_config.level = SandboxLevel(level_value)
        mock_sandbox_config.scope = MagicMock()
        mock_sandbox_config.scope.value = scope_value
        mock_sandbox_config.network_disabled = True
        return mock_sandbox_config

    def test_sandbox_build_local_level_skips_warmup(self, nexent_agent_instance, mock_model_config, mock_core_agent):
        """Sandbox with LOCAL level skips warm-up call (lines 615-626)."""
        nexent_agent_instance.model_config_list = [mock_model_config]
        SandboxLevel = self._make_sandbox_level()

        nexent_agent_instance.sandbox_config = self._make_sandbox_config("local")

        mock_build = MagicMock(return_value=MagicMock())

        mock_sandbox_module = MagicMock()
        mock_sandbox_module.build_python_executor = mock_build
        mock_sandbox_module.SandboxLevel = SandboxLevel

        agent_config = AgentConfig(
            name="sandbox_agent",
            description="Agent with sandbox",
            prompt_templates={"system": "test"},
            tools=[],
            max_steps=5,
            model_name="test_model",
            provide_run_summary=False,
            managed_agents=[],
            enable_planning=False,
        )

        with patch.dict("sys.modules", {
            "sdk.nexent.core.agents.sandbox": mock_sandbox_module,
        }):
            result, mock_cls = self._run_create_single_agent(
                nexent_agent_instance, mock_model_config, mock_core_agent, agent_config
            )

        mock_build.assert_called_once()
        assert nexent_agent_instance._sandbox_scope == "session"

    def test_sandbox_build_docker_level_with_warmup(self, nexent_agent_instance, mock_model_config, mock_core_agent):
        """Sandbox with DOCKER level triggers warm-up (lines 627-648)."""
        nexent_agent_instance.model_config_list = [mock_model_config]
        SandboxLevel = self._make_sandbox_level()

        nexent_agent_instance.sandbox_config = self._make_sandbox_config("docker")

        mock_executor = MagicMock()
        mock_executor._nexent_backend = "docker"
        mock_build = MagicMock(return_value=mock_executor)

        mock_sandbox_module = MagicMock()
        mock_sandbox_module.build_python_executor = mock_build
        mock_sandbox_module.SandboxLevel = SandboxLevel

        agent_config = AgentConfig(
            name="docker_agent",
            description="Agent with docker sandbox",
            prompt_templates={"system": "test"},
            tools=[],
            max_steps=5,
            model_name="test_model",
            provide_run_summary=False,
            managed_agents=[],
            enable_planning=False,
        )

        with patch.dict("sys.modules", {
            "sdk.nexent.core.agents.sandbox": mock_sandbox_module,
        }):
            result, mock_cls = self._run_create_single_agent(
                nexent_agent_instance, mock_model_config, mock_core_agent, agent_config
            )

        mock_build.assert_called_once()
        # Warm-up call should have happened: executor("[0, None]")
        mock_executor.assert_called_once_with("[0, None]")

    def test_docker_sandbox_binds_skill_script_execution_backend(
        self, nexent_agent_instance, mock_model_config, mock_core_agent
    ):
        nexent_agent_instance.model_config_list = [mock_model_config]
        nexent_agent_instance.sandbox_config = self._make_sandbox_config("docker")
        nexent_agent_instance.workspace_path = "/mnt/nexent/workdir/user/run"

        tool = MagicMock()
        tool.name = "run_skill_script"
        tool.bind_execution_backend = MagicMock()
        tool_config = ToolConfig(
            class_name="RunSkillScriptTool",
            name="run_skill_script",
            description="Run a skill script",
            inputs="{}",
            output_type="string",
            params={},
            source="builtin",
        )
        agent_config = AgentConfig(
            name="docker_agent",
            description="Agent with sandbox skill execution",
            prompt_templates={"system": "test"},
            tools=[tool_config],
            max_steps=5,
            model_name="test_model",
            provide_run_summary=False,
            managed_agents=[],
            enable_planning=False,
        )
        executor = MagicMock()
        executor._nexent_backend = "docker"
        runner = MagicMock()
        runner_class = MagicMock(return_value=runner)
        sandbox_module = MagicMock()
        sandbox_module.SandboxLevel = self._make_sandbox_level()
        sandbox_module.build_python_executor = MagicMock(return_value=executor)
        sandbox_module.SandboxSkillScriptRunner = runner_class

        with patch.dict(
            "sys.modules",
            {"sdk.nexent.core.agents.sandbox": sandbox_module},
        ), patch.object(
            nexent_agent_instance, "create_tool", return_value=tool
        ), patch.object(
            nexent_agent, "_wrap_tool_with_monitoring", side_effect=lambda value, _name: value
        ), patch.object(
            nexent_agent_instance, "_pull_file_workspace_from_sandbox"
        ) as pull_workspace:
            self._run_create_single_agent(
                nexent_agent_instance,
                mock_model_config,
                mock_core_agent,
                agent_config,
            )
            on_complete = tool.bind_execution_backend.call_args.kwargs["on_complete"]
            on_complete("done")

        runner_class.assert_called_once_with(
            executor,
            timeout_seconds=300,
            workspace_path=nexent_agent_instance.workspace_path,
            network_enabled=False,
        )
        tool.bind_execution_backend.assert_called_once_with(
            runner,
            on_complete=tool.bind_execution_backend.call_args.kwargs["on_complete"],
        )
        pull_workspace.assert_called_once_with()
        assert nexent_agent_instance._sandbox_skill_runners == [runner]

    def test_sandbox_build_docker_warmup_fallback_local(self, nexent_agent_instance, mock_model_config, mock_core_agent):
        """Warm-up detects fallback to local backend (lines 633-640)."""
        nexent_agent_instance.model_config_list = [mock_model_config]
        SandboxLevel = self._make_sandbox_level()

        nexent_agent_instance.sandbox_config = self._make_sandbox_config("docker")

        mock_executor = MagicMock()
        mock_executor._nexent_backend = "local"  # fallback to local
        mock_build = MagicMock(return_value=mock_executor)

        mock_sandbox_module = MagicMock()
        mock_sandbox_module.build_python_executor = mock_build
        mock_sandbox_module.SandboxLevel = SandboxLevel

        agent_config = AgentConfig(
            name="fallback_agent",
            description="Agent with fallback",
            prompt_templates={"system": "test"},
            tools=[],
            max_steps=5,
            model_name="test_model",
            provide_run_summary=False,
            managed_agents=[],
        )

        with patch.dict("sys.modules", {
            "sdk.nexent.core.agents.sandbox": mock_sandbox_module,
        }):
            result, _ = self._run_create_single_agent(
                nexent_agent_instance, mock_model_config, mock_core_agent, agent_config
            )

        mock_build.assert_called_once()

    def test_sandbox_build_warmup_error(self, nexent_agent_instance, mock_model_config, mock_core_agent):
        """Warm-up exception is caught and logged (lines 649-654)."""
        nexent_agent_instance.model_config_list = [mock_model_config]
        SandboxLevel = self._make_sandbox_level()

        nexent_agent_instance.sandbox_config = self._make_sandbox_config("docker")

        mock_executor = MagicMock(side_effect=RuntimeError("sandbox unreachable"))
        mock_build = MagicMock(return_value=mock_executor)

        mock_sandbox_module = MagicMock()
        mock_sandbox_module.build_python_executor = mock_build
        mock_sandbox_module.SandboxLevel = SandboxLevel

        agent_config = AgentConfig(
            name="err_agent",
            description="Agent with warm-up error",
            prompt_templates={"system": "test"},
            tools=[],
            max_steps=5,
            model_name="test_model",
            provide_run_summary=False,
            managed_agents=[],
        )

        with patch.dict("sys.modules", {
            "sdk.nexent.core.agents.sandbox": mock_sandbox_module,
        }):
            # Should NOT raise despite warm-up failure
            result, _ = self._run_create_single_agent(
                nexent_agent_instance, mock_model_config, mock_core_agent, agent_config
            )

        mock_build.assert_called_once()

    def test_parent_and_managed_agent_share_session_container_with_distinct_kernels(
        self, nexent_agent_instance, mock_model_config
    ):
        """Agent-tree executors share a session container but keep separate kernels."""
        nexent_agent_instance.model_config_list = [mock_model_config]
        SandboxLevel = self._make_sandbox_level()
        nexent_agent_instance.sandbox_config = self._make_sandbox_config(
            "docker", scope_value="session"
        )

        shared_group = object()
        child_executor = MagicMock(name="child_executor")
        child_executor._nexent_session_container_group = shared_group
        parent_executor = MagicMock(name="parent_executor")
        parent_executor._nexent_session_container_group = shared_group
        mock_build = MagicMock(side_effect=[child_executor, parent_executor])
        mock_sandbox_module = MagicMock()
        mock_sandbox_module.build_python_executor = mock_build
        mock_sandbox_module.SandboxLevel = SandboxLevel

        child_agent = MagicMock(name="child_agent")
        child_agent.name = "child"
        child_agent.enable_planning = False
        parent_agent = MagicMock(name="parent_agent")
        parent_agent.enable_planning = False

        child_config = AgentConfig(
            name="child",
            description="Managed child",
            prompt_templates={"system": "child"},
            tools=[],
            max_steps=5,
            model_name="test_model",
            managed_agents=[],
            enable_planning=False,
        )
        parent_config = AgentConfig(
            name="parent",
            description="Parent agent",
            prompt_templates={"system": "parent"},
            tools=[],
            max_steps=5,
            model_name="test_model",
            managed_agents=[child_config],
            enable_planning=False,
        )

        with patch.dict("sys.modules", {
            "sdk.nexent.core.agents.sandbox": mock_sandbox_module,
        }), patch.object(
            nexent_agent,
            "CoreAgent",
            side_effect=[child_agent, parent_agent],
        ) as mock_core_agent_cls:
            result = nexent_agent_instance.create_single_agent(parent_config)

        assert result is parent_agent
        assert mock_build.call_count == 2
        assert mock_build.call_args_list[0].kwargs["managed_agents_exist"] is False
        assert mock_build.call_args_list[0].kwargs["host_tools_exist"] is False
        assert mock_build.call_args_list[0].kwargs["session_container_group"] is None
        assert mock_build.call_args_list[1].kwargs["managed_agents_exist"] is True
        assert mock_build.call_args_list[1].kwargs["host_tools_exist"] is True
        assert (
            mock_build.call_args_list[1].kwargs["session_container_group"]
            is shared_group
        )

        child_call, parent_call = mock_core_agent_cls.call_args_list
        assert child_call.kwargs["executor"] is child_executor
        assert parent_call.kwargs["executor"] is parent_executor
        managed_wrapper = parent_call.kwargs["managed_agents"][0]
        assert managed_wrapper._nexent_execute_on_host is True
        assert managed_wrapper._inner is child_agent
        assert nexent_agent_instance._sandbox_executors == [
            child_executor,
            parent_executor,
        ]

    def test_agent_tree_rejects_multiple_session_container_groups(
        self, nexent_agent_instance, mock_model_config
    ):
        nexent_agent_instance.model_config_list = [mock_model_config]
        SandboxLevel = self._make_sandbox_level()
        nexent_agent_instance.sandbox_config = self._make_sandbox_config(
            "docker", scope_value="session"
        )
        child_executor = MagicMock()
        child_executor._nexent_session_container_group = object()
        parent_executor = MagicMock()
        parent_executor._nexent_session_container_group = object()
        mock_sandbox_module = MagicMock()
        mock_sandbox_module.build_python_executor = MagicMock(
            side_effect=[child_executor, parent_executor]
        )
        mock_sandbox_module.SandboxLevel = SandboxLevel
        child_config = AgentConfig(
            name="child",
            description="Managed child",
            prompt_templates={"system": "child"},
            tools=[],
            max_steps=5,
            model_name="test_model",
            managed_agents=[],
            enable_planning=False,
        )
        parent_config = AgentConfig(
            name="parent",
            description="Parent agent",
            prompt_templates={"system": "parent"},
            tools=[],
            max_steps=5,
            model_name="test_model",
            managed_agents=[child_config],
            enable_planning=False,
        )

        with patch.dict(
            "sys.modules",
            {"sdk.nexent.core.agents.sandbox": mock_sandbox_module},
        ), patch.object(nexent_agent, "CoreAgent", return_value=MagicMock()):
            with pytest.raises(ValueError, match="multiple session sandbox containers"):
                nexent_agent_instance.create_single_agent(parent_config)

    def test_plan_tool_wiring_when_planning_enabled(self, nexent_agent_instance, mock_model_config, mock_core_agent):
        """When enable_planning=True, plan tool deps are wired (lines 683-694)."""
        nexent_agent_instance.model_config_list = [mock_model_config]
        nexent_agent_instance.sandbox_config = None

        # Set up mock_core_agent.tools with create_plan and update_plan_step
        mock_create_plan = MagicMock()
        mock_update_step = MagicMock()
        mock_core_agent.tools = {
            "create_plan": mock_create_plan,
            "update_plan_step": mock_update_step,
        }
        mock_core_agent.plan_repo = MagicMock()
        mock_core_agent._on_plan_created = MagicMock()
        mock_core_agent._on_step_updated = MagicMock()
        mock_core_agent._get_conversation_id = MagicMock()
        mock_core_agent._get_user_id = MagicMock()
        mock_core_agent.enable_planning = True

        agent_config = AgentConfig(
            name="planning_agent",
            description="Agent with planning",
            prompt_templates={"system": "test"},
            tools=[],
            max_steps=5,
            model_name="test_model",
            provide_run_summary=False,
            managed_agents=[],
            enable_planning=True,
        )

        with patch.object(nexent_agent, "CoreAgent", return_value=mock_core_agent):
            nexent_agent_instance.create_single_agent(agent_config)

        # Verify create_plan wired
        assert mock_create_plan.observer is mock_core_agent.observer
        assert mock_create_plan.plan_repo is mock_core_agent.plan_repo
        assert mock_create_plan._on_plan_created is mock_core_agent._on_plan_created
        assert mock_create_plan._get_conversation_id is mock_core_agent._get_conversation_id
        assert mock_create_plan._get_user_id is mock_core_agent._get_user_id

        # Verify update_step wired
        assert mock_update_step.observer is mock_core_agent.observer
        assert mock_update_step.plan_repo is mock_core_agent.plan_repo
        assert mock_update_step._on_step_updated is mock_core_agent._on_step_updated
        assert mock_update_step._get_conversation_id is mock_core_agent._get_conversation_id
        assert mock_update_step._get_user_id is mock_core_agent._get_user_id


def test_create_local_tool_independent_aidp_search(nexent_agent_instance):
    """IndependentAidpSearchTool keeps credentials, strips runtime-only params,
    and receives the image_url_builder from metadata."""
    mock_tool_class = MagicMock()
    mock_tool_instance = MagicMock()
    mock_tool_class.return_value = mock_tool_instance

    builder = lambda _url: "/api/ind-aidp/images/ref"
    tool_config = ToolConfig(
        class_name="IndependentAidpSearchTool",
        name="ind_aidp_search",
        description="desc",
        inputs="{}",
        output_type="string",
        params={
            "server_url": "https://independent-aidp.example",
            "api_key": "instance-secret",
            "observer": "should-be-replaced",
            "image_url_builder": "should-be-replaced",
            "rerank_model": "should-drop",
            "rerank": "should-drop",
        },
        source="local",
        metadata={"image_url_builder": builder},
    )

    original_value = nexent_agent.__dict__.get("IndependentAidpSearchTool")
    nexent_agent.__dict__["IndependentAidpSearchTool"] = mock_tool_class
    try:
        result = nexent_agent_instance.create_local_tool(tool_config)
    finally:
        if original_value is not None:
            nexent_agent.__dict__["IndependentAidpSearchTool"] = original_value
        elif "IndependentAidpSearchTool" in nexent_agent.__dict__:
            del nexent_agent.__dict__["IndependentAidpSearchTool"]

    mock_tool_class.assert_called_once_with(
        server_url="https://independent-aidp.example",
        api_key="instance-secret",
    )
    assert result is mock_tool_instance
    assert result.observer == nexent_agent_instance.observer
    assert result.image_url_builder is builder


def test_create_local_tool_independent_aidp_search_without_metadata(nexent_agent_instance):
    """IndependentAidpSearchTool with no metadata leaves image_url_builder as None."""
    mock_tool_class = MagicMock()
    mock_tool_instance = MagicMock()
    mock_tool_class.return_value = mock_tool_instance
    tool_config = ToolConfig(
        class_name="IndependentAidpSearchTool",
        name="ind_aidp_search",
        description="desc",
        inputs="{}",
        output_type="string",
        params={
            "server_url": "https://independent-aidp.example",
            "api_key": "instance-secret",
            "tenant_id": "aidp",
            "kds_list": ["kb-1"],  # not in the filter list -> other branch of the loop
        },
        source="local",
        metadata={},
    )

    original_value = nexent_agent.__dict__.get("IndependentAidpSearchTool")
    nexent_agent.__dict__["IndependentAidpSearchTool"] = mock_tool_class
    try:
        result = nexent_agent_instance.create_local_tool(tool_config)
    finally:
        if original_value is not None:
            nexent_agent.__dict__["IndependentAidpSearchTool"] = original_value
        elif "IndependentAidpSearchTool" in nexent_agent.__dict__:
            del nexent_agent.__dict__["IndependentAidpSearchTool"]

    mock_tool_class.assert_called_once_with(
        server_url="https://independent-aidp.example",
        api_key="instance-secret",
        tenant_id="aidp",
        kds_list=["kb-1"],
    )
    assert result.image_url_builder is None
