import sys
import types
from pathlib import Path
from threading import Event
from unittest.mock import MagicMock, patch

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

# Create dummy smolagents sub-modules that may be imported indirectly
for sub_mod in ["agents", "memory", "models", "monitoring", "utils", "local_python_executor"]:
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
    pass


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

MessageObserver = _MockMessageObserver
ProcessType = _MockProcessType


mock_nexent_core_utils_module = types.ModuleType("nexent.core.utils")
mock_nexent_core_utils_observer_module = types.ModuleType("nexent.core.utils.observer")
mock_nexent_core_utils_observer_module.MessageObserver = _MockMessageObserver
mock_nexent_core_utils_observer_module.ProcessType = _MockProcessType

mock_sdk_module = types.ModuleType("sdk")
mock_sdk_nexent_module = types.ModuleType("sdk.nexent")
mock_sdk_nexent_core_module = types.ModuleType("sdk.nexent.core")
mock_sdk_nexent_core_agents_module = types.ModuleType("sdk.nexent.core.agents")
mock_sdk_nexent_core_utils_module = types.ModuleType("sdk.nexent.core.utils")
mock_sdk_nexent_core_utils_observer_module = types.ModuleType(
    "sdk.nexent.core.utils.observer"
)
mock_sdk_nexent_core_utils_observer_module.MessageObserver = _MockMessageObserver
mock_sdk_nexent_core_utils_observer_module.ProcessType = _MockProcessType

mock_sdk_module.__path__ = [str(SDK_SOURCE_ROOT)]
mock_sdk_nexent_module.__path__ = [str(SDK_SOURCE_ROOT / "nexent")]
mock_sdk_nexent_core_module.__path__ = [str(SDK_SOURCE_ROOT / "nexent" / "core")]
mock_sdk_nexent_core_agents_module.__path__ = [
    str(SDK_SOURCE_ROOT / "nexent" / "core" / "agents")
]
mock_sdk_nexent_core_utils_module.__path__ = [str(SDK_SOURCE_ROOT / "nexent" / "core" / "utils")]
mock_sdk_nexent_core_utils_observer_module.__path__ = []

mock_prompt_template_utils_module = types.ModuleType(
    "nexent.core.utils.prompt_template_utils"
)
mock_prompt_template_utils_module.get_prompt_template = MagicMock(return_value="")

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
mock_nexent_load_save_module = types.ModuleType("nexent.multi_modal.load_save_object")
mock_nexent_load_save_module.LoadSaveObjectManager = MagicMock()
mock_nexent_module.multi_modal = mock_nexent_multi_modal_module
module_mocks = {
    "sdk": sdk_namespace_module,
    "smolagents": mock_smolagents,
    "smolagents.tools": mock_smolagents_tools,
    "smolagents.agents": MagicMock(),
    "smolagents.memory": MagicMock(),
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
    "sdk.nexent.core.utils": mock_sdk_nexent_core_utils_module,
    "sdk.nexent.core.utils.observer": mock_sdk_nexent_core_utils_observer_module,
    "nexent.core.utils.prompt_template_utils": mock_prompt_template_utils_module,
    "nexent.core.utils.tools_common_message": mock_tools_common_message_module,
    "nexent.core.models": mock_nexent_core_models_module,
    "nexent.storage": mock_nexent_storage_module,
    "nexent.multi_modal": mock_nexent_multi_modal_module,
    "nexent.multi_modal.load_save_object": mock_nexent_load_save_module,
    # Mock tiktoken to avoid importing the real package when models import it
    "tiktoken": MagicMock(),
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
    from sdk.nexent.core.agents.nexent_agent import NexentAgent, ActionStep, TaskStep
    from sdk.nexent.core.agents.agent_model import ToolConfig, ModelConfig, AgentConfig, AgentHistory

    # Clean up after import
    sys.modules.pop("nexent.utils.http_client_manager", None)


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
    return agent


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

    # Verify OpenAIModel was constructed with correct parameters
    mock_openai_model_class.assert_called_once_with(
        observer=nexent_agent_with_models.observer,
        model_id=mock_model_config.model_name,
        api_key=mock_model_config.api_key,
        model_factory=mock_model_config.model_factory,
        api_base=mock_model_config.url,
        temperature=mock_model_config.temperature,
        top_p=mock_model_config.top_p,
        ssl_verify=True
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

    # Verify OpenAIModel was constructed with correct parameters
    mock_openai_model_class.assert_called_once_with(
        observer=nexent_agent_with_models.observer,
        model_id=mock_deep_thinking_model_config.model_name,
        model_factory=mock_deep_thinking_model_config.model_factory,
        api_key=mock_deep_thinking_model_config.api_key,
        api_base=mock_deep_thinking_model_config.url,
        temperature=mock_deep_thinking_model_config.temperature,
        top_p=mock_deep_thinking_model_config.top_p,
        ssl_verify=True
    )

    # Verify stop_event was set
    assert result.stop_event == nexent_agent_with_models.stop_event


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
            "index_names": ["conflicting_index"],  # This should be filtered out
            "vdb_core": "conflicting_vdb",  # This should be filtered out
            "embedding_model": "conflicting_model",  # This should be filtered out
            "observer": "conflicting_observer",  # This should be filtered out
        },
        source="local",
        metadata={
            "index_names": ["index1", "index2"],  # These should be used instead
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
        index_names=["conflicting_index"],  # Not excluded by current implementation
    )
    # Verify excluded parameters were set directly as attributes after instantiation
    assert result == mock_kb_tool_instance
    assert mock_kb_tool_instance.observer == nexent_agent_instance.observer
    assert mock_kb_tool_instance.vdb_core == mock_vdb_core  # From metadata, not params
    assert mock_kb_tool_instance.embedding_model == mock_embedding_model  # From metadata, not params


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

    with patch.object(
            nexent_agent_instance,
            "create_mcp_tool",
            return_value="mcp_tool",
    ) as mock_create_mcp_tool:
        result = nexent_agent_instance.create_tool(tool_config)

    mock_create_mcp_tool.assert_called_once_with("DummyTool")
    assert result == "mcp_tool"


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
    mock_action_step.duration = 1.5
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
        "", ProcessType.TOKEN_COUNT, "1.5")
    mock_core_agent.observer.add_message.assert_any_call(
        "test_agent", ProcessType.FINAL_ANSWER, " content")


def test_agent_run_with_observer_success_with_string_final_answer(nexent_agent_instance, mock_core_agent):
    """Test successful agent_run_with_observer with string final answer."""
    # Setup
    nexent_agent_instance.agent = mock_core_agent
    mock_core_agent.stop_event.is_set.return_value = False

    # Mock step logs
    mock_action_step = MagicMock(spec=ActionStep)
    mock_action_step.duration = 2.0
    mock_action_step.error = None

    mock_core_agent.run.return_value = [mock_action_step]
    mock_core_agent.run.return_value[-1].output = "String final answer with <think>thinking</think>"

    # Execute
    nexent_agent_instance.agent_run_with_observer("test query")

    # Verify
    mock_core_agent.observer.add_message.assert_any_call(
        "", ProcessType.TOKEN_COUNT, "2.0")
    mock_core_agent.observer.add_message.assert_any_call(
        "test_agent", ProcessType.FINAL_ANSWER, "")


def test_agent_run_with_observer_with_error_in_step(nexent_agent_instance, mock_core_agent):
    """Test agent_run_with_observer handles error in step log."""
    # Setup
    nexent_agent_instance.agent = mock_core_agent
    mock_core_agent.stop_event.is_set.return_value = False

    # Mock step logs with error
    mock_action_step = MagicMock(spec=ActionStep)
    mock_action_step.duration = 1.0
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
    mock_action_step.duration = 1.0
    mock_action_step.error = None

    mock_core_agent.run.return_value = [mock_task_step, mock_action_step]
    mock_core_agent.run.return_value[-1].output = "Final answer"

    # Execute
    nexent_agent_instance.agent_run_with_observer("test query")

    # Verify only ActionStep was processed
    mock_core_agent.observer.add_message.assert_any_call(
        "", ProcessType.TOKEN_COUNT, "1.0")
    # Should not process TaskStep


def test_agent_run_with_observer_with_stop_event_set(nexent_agent_instance, mock_core_agent):
    """Test agent_run_with_observer handles stop event being set."""
    # Setup
    nexent_agent_instance.agent = mock_core_agent
    mock_core_agent.stop_event.is_set.return_value = True

    # Mock step logs
    mock_action_step = MagicMock(spec=ActionStep)
    mock_action_step.duration = 1.0
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
    mock_action_step.duration = 1.0
    mock_action_step.error = None

    mock_core_agent.run.return_value = [mock_action_step]
    mock_core_agent.run.return_value[-1].output = "Final answer"

    # Execute with reset=False
    nexent_agent_instance.agent_run_with_observer("test query", reset=False)

    # Verify run was called with reset=False
    mock_core_agent.run.assert_called_once_with(
        "test query", stream=True, reset=False)

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


if __name__ == "__main__":
    pytest.main([__file__])
