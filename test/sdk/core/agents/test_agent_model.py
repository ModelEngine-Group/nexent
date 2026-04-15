"""
Unit tests for sdk.nexent.core.agents.agent_model module.

This module tests all Pydantic models and related constants:
- Protocol constants (PROTOCOL_JSONRPC, PROTOCOL_HTTP_JSON, PROTOCOL_GRPC)
- ModelConfig
- ToolConfig
- AgentConfig
- AgentHistory
- AgentRunInfo
- MemoryContext
- MemoryUserConfig
- ExternalA2AAgentConfig
"""
import os
import sys
import types
import importlib.util
from pathlib import Path
from threading import Event
from types import ModuleType
from unittest.mock import MagicMock

import pytest

TEST_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = TEST_ROOT.parent

for _path in (str(PROJECT_ROOT), str(TEST_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)


# ---------------------------------------------------------------------------
# Prepare mocks for external dependencies
# ---------------------------------------------------------------------------

def _create_mock_smolagents():
    """Create mock smolagents module with all required submodules."""
    mock_smolagents = ModuleType("smolagents")
    mock_smolagents.__dict__.update({})
    mock_smolagents.__path__ = []

    mock_smolagents.ActionStep = MagicMock()
    mock_smolagents.TaskStep = MagicMock()
    mock_smolagents.Timing = MagicMock()
    mock_smolagents.AgentText = MagicMock()
    mock_smolagents.handle_agent_output_types = MagicMock()

    agents_mod = ModuleType("smolagents.agents")
    for _name in ["CodeAgent", "populate_template", "handle_agent_output_types", "AgentError", "ActionOutput", "RunResult"]:
        setattr(agents_mod, _name, MagicMock(name=f"smolagents.agents.{_name}"))
    setattr(mock_smolagents, "agents", agents_mod)

    local_python_mod = ModuleType("smolagents.local_python_executor")
    setattr(local_python_mod, "fix_final_answer_code", MagicMock(name="fix_final_answer_code"))
    setattr(mock_smolagents, "local_python_executor", local_python_mod)

    memory_mod = ModuleType("smolagents.memory")
    for _name in ["ActionStep", "ToolCall", "TaskStep", "SystemPromptStep", "PlanningStep", "FinalAnswerStep"]:
        setattr(memory_mod, _name, MagicMock(name=f"smolagents.memory.{_name}"))
    setattr(mock_smolagents, "memory", memory_mod)

    models_mod = ModuleType("smolagents.models")
    setattr(models_mod, "ChatMessage", MagicMock(name="ChatMessage"))
    setattr(models_mod, "MessageRole", MagicMock(name="MessageRole"))
    setattr(models_mod, "CODEAGENT_RESPONSE_FORMAT", MagicMock(name="CODEAGENT_RESPONSE_FORMAT"))
    setattr(models_mod, "OpenAIServerModel", MagicMock(name="OpenAIServerModel"))
    setattr(mock_smolagents, "models", models_mod)

    monitoring_mod = ModuleType("smolagents.monitoring")
    setattr(monitoring_mod, "LogLevel", MagicMock(name="LogLevel"))
    setattr(monitoring_mod, "Timing", MagicMock(name="Timing"))
    setattr(monitoring_mod, "YELLOW_HEX", MagicMock(name="YELLOW_HEX"))
    setattr(monitoring_mod, "TokenUsage", MagicMock(name="TokenUsage"))
    setattr(mock_smolagents, "monitoring", monitoring_mod)

    utils_mod = ModuleType("smolagents.utils")
    for _name in ["AgentExecutionError", "AgentGenerationError", "AgentParsingError",
                  "AgentMaxStepsError", "truncate_content", "extract_code_from_text"]:
        setattr(utils_mod, _name, MagicMock(name=f"smolagents.utils.{_name}"))
    setattr(mock_smolagents, "utils", utils_mod)

    tools_mod = ModuleType("smolagents.tools")
    mock_tool_class = MagicMock()
    mock_tool_class.from_langchain = MagicMock()
    setattr(tools_mod, "Tool", mock_tool_class)
    setattr(mock_smolagents, "tools", tools_mod)

    return mock_smolagents


def _create_mock_modules():
    """Create all required module mocks."""
    mock_smolagents = _create_mock_smolagents()

    mock_rich_console = ModuleType("rich.console")
    mock_rich_text = ModuleType("rich.text")
    mock_rich = ModuleType("rich")
    setattr(mock_rich, "Group", MagicMock(side_effect=lambda *args: args))
    setattr(mock_rich_text, "Text", MagicMock())
    setattr(mock_rich, "console", mock_rich_console)
    setattr(mock_rich, "text", mock_rich_text)
    setattr(mock_rich_console, "Group", MagicMock(side_effect=lambda *args: args))

    mock_jinja2 = ModuleType("jinja2")
    setattr(mock_jinja2, "Template", MagicMock())
    setattr(mock_jinja2, "StrictUndefined", MagicMock())

    mock_langchain_core = ModuleType("langchain_core")
    mock_langchain_core.tools = ModuleType("langchain_core.tools")
    setattr(mock_langchain_core.tools, "BaseTool", MagicMock())

    mock_exa_py = ModuleType("exa_py")
    setattr(mock_exa_py, "Exa", MagicMock())

    mock_openai = ModuleType("openai")
    mock_openai.types = ModuleType("openai.types")
    mock_openai.types.chat = ModuleType("openai.types.chat")
    setattr(mock_openai.types.chat, "chat_completion_message", MagicMock())
    setattr(mock_openai.types.chat, "chat_completion_message_param", MagicMock())

    class ProcessType:
        STEP_COUNT = "STEP_COUNT"
        PARSE = "PARSE"
        EXECUTION_LOGS = "EXECUTION_LOGS"
        AGENT_NEW_RUN = "AGENT_NEW_RUN"
        AGENT_FINISH = "AGENT_FINISH"
        FINAL_ANSWER = "FINAL_ANSWER"
        ERROR = "ERROR"
        OTHER = "OTHER"
        SEARCH_CONTENT = "SEARCH_CONTENT"
        TOKEN_COUNT = "TOKEN_COUNT"
        PICTURE_WEB = "PICTURE_WEB"
        CARD = "CARD"
        TOOL = "TOOL"
        MEMORY_SEARCH = "MEMORY_SEARCH"
        MODEL_OUTPUT_DEEP_THINKING = "MODEL_OUTPUT_DEEP_THINKING"
        MODEL_OUTPUT_THINKING = "MODEL_OUTPUT_THINKING"
        MODEL_OUTPUT_CODE = "MODEL_OUTPUT_CODE"

    class MessageObserver:
        def __init__(self):
            self.messages = []
            self.add_message = MagicMock()

        def add_message(self, agent_name=None, process_type=None, content=None):
            self.messages.append({
                "agent_name": agent_name,
                "process_type": process_type,
                "content": content
            })

    mock_observer = ModuleType("sdk.nexent.core.utils.observer")
    setattr(mock_observer, "MessageObserver", MessageObserver)
    setattr(mock_observer, "ProcessType", ProcessType)

    mock_tools_common_message_module = ModuleType("nexent.core.utils.tools_common_message")

    mock_botocore_module = ModuleType("botocore")
    mock_botocore_exceptions = ModuleType("botocore.exceptions")
    mock_botocore_exceptions.ClientError = MagicMock()
    mock_botocore_module.exceptions = mock_botocore_exceptions
    mock_botocore_client = ModuleType("botocore.client")
    mock_botocore_client.Config = MagicMock()
    mock_botocore_args = ModuleType("botocore.args")
    mock_botocore_args.ClientArgsCreator = MagicMock()
    mock_botocore_regions = ModuleType("botocore.regions")
    mock_botocore_regions.EndpointResolverBuiltins = MagicMock()
    mock_botocore_crt = ModuleType("botocore.crt")
    mock_botocore_crt.CRT_SUPPORTED_AUTH_TYPES = []

    # Mock A2AAgentInfo
    mock_a2a_agent_proxy = ModuleType("sdk.nexent.core.agents.a2a_agent_proxy")
    mock_a2a_agent_proxy_class = MagicMock()
    setattr(mock_a2a_agent_proxy, "A2AAgentInfo", mock_a2a_agent_proxy_class)

    return {
        "smolagents": mock_smolagents,
        "smolagents.agents": mock_smolagents.agents,
        "smolagents.memory": mock_smolagents.memory,
        "smolagents.models": mock_smolagents.models,
        "smolagents.monitoring": mock_smolagents.monitoring,
        "smolagents.utils": mock_smolagents.utils,
        "smolagents.local_python_executor": mock_smolagents.local_python_executor,
        "smolagents.tools": mock_smolagents.tools,
        "rich.console": mock_rich_console,
        "rich.text": mock_rich_text,
        "rich": mock_rich,
        "jinja2": mock_jinja2,
        "langchain_core": mock_langchain_core,
        "langchain_core.tools": mock_langchain_core.tools,
        "exa_py": mock_exa_py,
        "openai": mock_openai,
        "openai.types": mock_openai.types,
        "openai.types.chat": mock_openai.types.chat,
        "sdk.nexent.core.utils.observer": mock_observer,
        "sdk.nexent.core.utils.observer.MessageObserver": MessageObserver,
        "sdk.nexent.core.utils.observer.ProcessType": ProcessType,
        "nexent.core.utils.observer": mock_observer,
        "nexent.core.utils.tools_common_message": mock_tools_common_message_module,
        "botocore": mock_botocore_module,
        "botocore.client": mock_botocore_client,
        "botocore.exceptions": mock_botocore_exceptions,
        "botocore.args": mock_botocore_args,
        "botocore.regions": mock_botocore_regions,
        "botocore.crt": mock_botocore_crt,
        "sdk.nexent.core.agents.a2a_agent_proxy": mock_a2a_agent_proxy,
        "paramiko": MagicMock(),
        "boto3": MagicMock(),
        "tiktoken": MagicMock(),
        "aiohttp": MagicMock(),
        "tavily": MagicMock(),
        "linkup": MagicMock(),
    }


# Create mock modules
_module_mocks = _create_mock_modules()

# Register mocks in sys.modules
_original_modules = {}
for name, module in _module_mocks.items():
    if name in sys.modules:
        _original_modules[name] = sys.modules[name]
    sys.modules[name] = module


# ---------------------------------------------------------------------------
# Load agent_model module directly
# ---------------------------------------------------------------------------

def _load_agent_model_module():
    """Load agent_model module directly."""
    # Use cross-platform path construction
    # __file__ is C:\xuyaqi\develop\nexent\test\sdk\core\agents\test_agent_model.py
    # We need to go up 5 levels to get to C:\xuyaqi\develop\nexent
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
    agent_model_path = os.path.join(project_root, "sdk", "nexent", "core", "agents", "agent_model.py")

    sys.modules["sdk"] = ModuleType("sdk")
    sys.modules["sdk.nexent"] = ModuleType("sdk.nexent")
    sys.modules["sdk.nexent.core"] = ModuleType("sdk.nexent.core")
    sys.modules["sdk.nexent.core.agents"] = ModuleType("sdk.nexent.core.agents")

    spec = importlib.util.spec_from_file_location("sdk.nexent.core.agents.agent_model", agent_model_path)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "sdk.nexent.core.agents"
    sys.modules["sdk.nexent.core.agents.agent_model"] = module

    spec.loader.exec_module(module)
    return module


agent_model_module = _load_agent_model_module()

# Import ProcessType and MessageObserver for tests
ProcessType = _module_mocks["sdk.nexent.core.utils.observer"].ProcessType
MessageObserver = _module_mocks["sdk.nexent.core.utils.observer"].MessageObserver


# ----------------------------------------------------------------------------
# Tests for Protocol Constants
# ----------------------------------------------------------------------------

class TestProtocolConstants:
    """Tests for protocol type constants."""

    def test_protocol_jsonrpc_value(self):
        """Test PROTOCOL_JSONRPC constant has correct value."""
        assert agent_model_module.PROTOCOL_JSONRPC == "JSONRPC"

    def test_protocol_http_json_value(self):
        """Test PROTOCOL_HTTP_JSON constant has correct value."""
        assert agent_model_module.PROTOCOL_HTTP_JSON == "HTTP+JSON"

    def test_protocol_grpc_value(self):
        """Test PROTOCOL_GRPC constant has correct value."""
        assert agent_model_module.PROTOCOL_GRPC == "GRPC"

    def test_protocol_constants_are_strings(self):
        """Test all protocol constants are string type."""
        assert isinstance(agent_model_module.PROTOCOL_JSONRPC, str)
        assert isinstance(agent_model_module.PROTOCOL_HTTP_JSON, str)
        assert isinstance(agent_model_module.PROTOCOL_GRPC, str)


# ----------------------------------------------------------------------------
# Tests for ModelConfig
# ----------------------------------------------------------------------------

class TestModelConfig:
    """Tests for ModelConfig Pydantic model."""

    def test_model_config_creation_with_all_fields(self):
        """Test ModelConfig creation with all fields."""
        config = agent_model_module.ModelConfig(
            cite_name="gpt-4",
            api_key="sk-test-key",
            model_name="gpt-4-turbo",
            url="https://api.openai.com/v1",
            temperature=0.7,
            top_p=0.9,
            ssl_verify=False,
            model_factory="openai"
        )
        assert config.cite_name == "gpt-4"
        assert config.api_key == "sk-test-key"
        assert config.model_name == "gpt-4-turbo"
        assert config.url == "https://api.openai.com/v1"
        assert config.temperature == 0.7
        assert config.top_p == 0.9
        assert config.ssl_verify is False
        assert config.model_factory == "openai"

    def test_model_config_creation_with_minimal_fields(self):
        """Test ModelConfig creation with only required fields."""
        config = agent_model_module.ModelConfig(
            cite_name="gpt-4",
            model_name="gpt-4-turbo",
            url="https://api.openai.com/v1"
        )
        assert config.cite_name == "gpt-4"
        assert config.api_key == ""
        assert config.temperature == 0.1
        assert config.top_p == 0.95
        assert config.ssl_verify is True
        assert config.model_factory is None

    def test_model_config_defaults(self):
        """Test ModelConfig has correct default values."""
        config = agent_model_module.ModelConfig(
            cite_name="test",
            model_name="test-model",
            url="https://example.com"
        )
        assert config.api_key == ""
        assert config.temperature == 0.1
        assert config.top_p == 0.95
        assert config.ssl_verify is True
        assert config.model_factory is None

    def test_model_config_temperature_boundary(self):
        """Test ModelConfig accepts boundary temperature values."""
        config_min = agent_model_module.ModelConfig(
            cite_name="test",
            model_name="test",
            url="https://example.com",
            temperature=0.0
        )
        assert config_min.temperature == 0.0

        config_max = agent_model_module.ModelConfig(
            cite_name="test",
            model_name="test",
            url="https://example.com",
            temperature=2.0
        )
        assert config_max.temperature == 2.0

    def test_model_config_top_p_boundary(self):
        """Test ModelConfig accepts boundary top_p values."""
        config_min = agent_model_module.ModelConfig(
            cite_name="test",
            model_name="test",
            url="https://example.com",
            top_p=0.0
        )
        assert config_min.top_p == 0.0

        config_max = agent_model_module.ModelConfig(
            cite_name="test",
            model_name="test",
            url="https://example.com",
            top_p=1.0
        )
        assert config_max.top_p == 1.0

    def test_model_config_serialization(self):
        """Test ModelConfig can be serialized to dict."""
        config = agent_model_module.ModelConfig(
            cite_name="gpt-4",
            api_key="secret",
            model_name="gpt-4-turbo",
            url="https://api.openai.com/v1"
        )
        data = config.model_dump()
        assert data["cite_name"] == "gpt-4"
        assert data["api_key"] == "secret"
        assert data["model_name"] == "gpt-4-turbo"

    def test_model_config_missing_required_fields(self):
        """Test ModelConfig raises error when required fields are missing."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            agent_model_module.ModelConfig()

        with pytest.raises(Exception):  # Pydantic ValidationError
            agent_model_module.ModelConfig(cite_name="test")


# ----------------------------------------------------------------------------
# Tests for ToolConfig
# ----------------------------------------------------------------------------

class TestToolConfig:
    """Tests for ToolConfig Pydantic model."""

    def test_tool_config_creation_with_all_fields(self):
        """Test ToolConfig creation with all fields."""
        config = agent_model_module.ToolConfig(
            class_name="TavilySearchTool",
            name="web_search",
            description="Search the web",
            inputs='{"query": "str"}',
            output_type="string",
            params={"api_key": "test-key"},
            source="local",
            usage="mcp-server-1",
            metadata={"key": "value"}
        )
        assert config.class_name == "TavilySearchTool"
        assert config.name == "web_search"
        assert config.description == "Search the web"
        assert config.inputs == '{"query": "str"}'
        assert config.output_type == "string"
        assert config.params == {"api_key": "test-key"}
        assert config.source == "local"
        assert config.usage == "mcp-server-1"
        assert config.metadata == {"key": "value"}

    def test_tool_config_with_minimal_fields(self):
        """Test ToolConfig creation with minimal fields."""
        config = agent_model_module.ToolConfig(
            class_name="SomeTool",
            name=None,
            description=None,
            inputs=None,
            output_type=None,
            params={},
            source="local"
        )
        assert config.class_name == "SomeTool"
        assert config.name is None
        assert config.description is None
        assert config.inputs is None
        assert config.output_type is None
        assert config.params == {}
        assert config.source == "local"
        assert config.usage is None
        assert config.metadata is None

    def test_tool_config_defaults(self):
        """Test ToolConfig has correct default values."""
        config = agent_model_module.ToolConfig(
            class_name="TestTool",
            name=None,
            description=None,
            inputs=None,
            output_type=None,
            params={"key": "value"},
            source="local"
        )
        assert config.name is None
        assert config.description is None
        assert config.inputs is None
        assert config.output_type is None
        assert config.usage is None
        assert config.metadata is None

    def test_tool_config_params_as_dict(self):
        """Test ToolConfig params field accepts dictionary."""
        params = {
            "api_key": "secret",
            "top_k": 5,
            "enabled": True
        }
        config = agent_model_module.ToolConfig(
            class_name="TestTool",
            name=None,
            description=None,
            inputs=None,
            output_type=None,
            params=params,
            source="local"
        )
        assert config.params == params

    def test_tool_config_metadata_as_dict(self):
        """Test ToolConfig metadata field accepts dictionary."""
        metadata = {
            "index_names": ["index1", "index2"],
            "embedding_model": {"name": "text-embedding-ada-002"}
        }
        config = agent_model_module.ToolConfig(
            class_name="KnowledgeBaseTool",
            name=None,
            description=None,
            inputs=None,
            output_type=None,
            params={},
            source="local",
            metadata=metadata
        )
        assert config.metadata == metadata


# ----------------------------------------------------------------------------
# Tests for AgentHistory
# ----------------------------------------------------------------------------

class TestAgentHistory:
    """Tests for AgentHistory Pydantic model."""

    def test_agent_history_creation(self):
        """Test AgentHistory creation with required fields."""
        history = agent_model_module.AgentHistory(
            role="user",
            content="Hello, how are you?"
        )
        assert history.role == "user"
        assert history.content == "Hello, how are you?"

    def test_agent_history_assistant_role(self):
        """Test AgentHistory with assistant role."""
        history = agent_model_module.AgentHistory(
            role="assistant",
            content="I'm doing well, thank you!"
        )
        assert history.role == "assistant"
        assert history.content == "I'm doing well, thank you!"

    def test_agent_history_multiline_content(self):
        """Test AgentHistory with multiline content."""
        content = """This is a multi-line response.
It has multiple lines.
And more content here."""
        history = agent_model_module.AgentHistory(role="assistant", content=content)
        assert history.content == content

    def test_agent_history_serialization(self):
        """Test AgentHistory can be serialized to dict."""
        history = agent_model_module.AgentHistory(role="user", content="Test message")
        data = history.model_dump()
        assert data["role"] == "user"
        assert data["content"] == "Test message"


# ----------------------------------------------------------------------------
# Tests for MemoryUserConfig
# ----------------------------------------------------------------------------

class TestMemoryUserConfig:
    """Tests for MemoryUserConfig Pydantic model."""

    def test_memory_user_config_creation(self):
        """Test MemoryUserConfig creation with all fields."""
        config = agent_model_module.MemoryUserConfig(
            memory_switch=True,
            agent_share_option="team",
            disable_agent_ids=["agent-1", "agent-2"],
            disable_user_agent_ids=["user-agent-1"]
        )
        assert config.memory_switch is True
        assert config.agent_share_option == "team"
        assert config.disable_agent_ids == ["agent-1", "agent-2"]
        assert config.disable_user_agent_ids == ["user-agent-1"]

    def test_memory_user_config_defaults(self):
        """Test MemoryUserConfig default values."""
        config = agent_model_module.MemoryUserConfig(
            memory_switch=False,
            agent_share_option="private",
            disable_agent_ids=[],
            disable_user_agent_ids=[]
        )
        assert config.memory_switch is False
        assert config.agent_share_option == "private"
        assert config.disable_agent_ids == []
        assert config.disable_user_agent_ids == []

    def test_memory_user_config_str_method(self):
        """Test MemoryUserConfig __str__ method."""
        config = agent_model_module.MemoryUserConfig(
            memory_switch=True,
            agent_share_option="public",
            disable_agent_ids=[],
            disable_user_agent_ids=[]
        )
        str_repr = str(config)
        assert "memory_switch" in str_repr
        assert "agent_share_option" in str_repr


# ----------------------------------------------------------------------------
# Tests for MemoryContext
# ----------------------------------------------------------------------------

class TestMemoryContext:
    """Tests for MemoryContext Pydantic model."""

    def test_memory_context_creation(self):
        """Test MemoryContext creation with all fields."""
        user_config = agent_model_module.MemoryUserConfig(
            memory_switch=True,
            agent_share_option="team",
            disable_agent_ids=[],
            disable_user_agent_ids=[]
        )
        context = agent_model_module.MemoryContext(
            user_config=user_config,
            memory_config={"type": "chroma"},
            tenant_id="tenant-123",
            user_id="user-456",
            agent_id="agent-789"
        )
        assert context.tenant_id == "tenant-123"
        assert context.user_id == "user-456"
        assert context.agent_id == "agent-789"
        assert context.user_config == user_config
        assert context.memory_config == {"type": "chroma"}

    def test_memory_context_str_method(self):
        """Test MemoryContext __str__ method returns JSON string."""
        user_config = agent_model_module.MemoryUserConfig(
            memory_switch=False,
            agent_share_option="private",
            disable_agent_ids=[],
            disable_user_agent_ids=[]
        )
        context = agent_model_module.MemoryContext(
            user_config=user_config,
            memory_config={},
            tenant_id="tenant-1",
            user_id="user-1",
            agent_id="agent-1"
        )
        str_repr = str(context)
        assert "tenant_id" in str_repr
        assert "agent_id" in str_repr


# ----------------------------------------------------------------------------
# Tests for AgentRunInfo
# ----------------------------------------------------------------------------

class TestAgentRunInfo:
    """Tests for AgentRunInfo Pydantic model."""

    def test_agent_run_info_creation(self):
        """Test AgentRunInfo creation with all fields."""
        observer = MessageObserver()
        stop_event = Event()
        model_config = agent_model_module.ModelConfig(
            cite_name="gpt-4",
            model_name="gpt-4",
            url="https://api.openai.com/v1"
        )

        run_info = agent_model_module.AgentRunInfo(
            query="What is the capital of France?",
            model_config_list=[model_config],
            observer=observer,
            agent_config=agent_model_module.AgentConfig(
                name="test_agent",
                description="A test agent",
                tools=[],
                model_name="gpt-4"
            ),
            stop_event=stop_event
        )

        assert run_info.query == "What is the capital of France?"
        assert len(run_info.model_config_list) == 1
        assert run_info.observer == observer
        assert run_info.stop_event == stop_event
        assert run_info.agent_config.name == "test_agent"

    def test_agent_run_info_with_optional_fields(self):
        """Test AgentRunInfo with optional fields populated."""
        observer = MessageObserver()
        stop_event = Event()
        model_config = agent_model_module.ModelConfig(
            cite_name="gpt-4",
            model_name="gpt-4",
            url="https://api.openai.com/v1"
        )
        history = [
            agent_model_module.AgentHistory(role="user", content="Hello"),
            agent_model_module.AgentHistory(role="assistant", content="Hi there!")
        ]

        run_info = agent_model_module.AgentRunInfo(
            query="Second question",
            model_config_list=[model_config],
            observer=observer,
            agent_config=agent_model_module.AgentConfig(
                name="test_agent",
                description="A test agent",
                tools=[],
                model_name="gpt-4"
            ),
            mcp_host=["https://mcp-server.com/sse"],
            history=history,
            stop_event=stop_event
        )

        assert run_info.mcp_host == ["https://mcp-server.com/sse"]
        assert len(run_info.history) == 2
        assert run_info.history[0].role == "user"

    def test_agent_run_info_mcp_host_string(self):
        """Test AgentRunInfo with mcp_host as simple string in a list."""
        observer = MessageObserver()
        stop_event = Event()
        model_config = agent_model_module.ModelConfig(
            cite_name="gpt-4",
            model_name="gpt-4",
            url="https://api.openai.com/v1"
        )

        run_info = agent_model_module.AgentRunInfo(
            query="Query with string mcp host",
            model_config_list=[model_config],
            observer=observer,
            agent_config=agent_model_module.AgentConfig(
                name="test_agent",
                description="A test agent",
                tools=[],
                model_name="gpt-4"
            ),
            mcp_host=["https://mcp-server.com/mcp"],
            stop_event=stop_event
        )

        assert run_info.mcp_host == ["https://mcp-server.com/mcp"]

    def test_agent_run_info_mcp_host_dict(self):
        """Test AgentRunInfo with mcp_host as dict configuration."""
        observer = MessageObserver()
        stop_event = Event()
        model_config = agent_model_module.ModelConfig(
            cite_name="gpt-4",
            model_name="gpt-4",
            url="https://api.openai.com/v1"
        )
        mcp_config = {
            "url": "https://mcp-server.com/sse",
            "transport": "sse",
            "headers": {"Authorization": "Bearer token123"}
        }

        run_info = agent_model_module.AgentRunInfo(
            query="Query with dict mcp host",
            model_config_list=[model_config],
            observer=observer,
            agent_config=agent_model_module.AgentConfig(
                name="test_agent",
                description="A test agent",
                tools=[],
                model_name="gpt-4"
            ),
            mcp_host=[mcp_config],
            stop_event=stop_event
        )

        assert len(run_info.mcp_host) == 1
        assert run_info.mcp_host[0]["url"] == "https://mcp-server.com/sse"

    def test_agent_run_info_without_history(self):
        """Test AgentRunInfo defaults to None for history."""
        observer = MessageObserver()
        stop_event = Event()
        model_config = agent_model_module.ModelConfig(
            cite_name="gpt-4",
            model_name="gpt-4",
            url="https://api.openai.com/v1"
        )

        run_info = agent_model_module.AgentRunInfo(
            query="Fresh query",
            model_config_list=[model_config],
            observer=observer,
            agent_config=agent_model_module.AgentConfig(
                name="test_agent",
                description="A test agent",
                tools=[],
                model_name="gpt-4"
            ),
            stop_event=stop_event
        )

        assert run_info.history is None
        assert run_info.mcp_host is None


# ----------------------------------------------------------------------------
# Tests for ExternalA2AAgentConfig
# ----------------------------------------------------------------------------

class TestExternalA2AAgentConfig:
    """Tests for ExternalA2AAgentConfig Pydantic model."""

    def test_external_a2a_agent_config_creation(self):
        """Test ExternalA2AAgentConfig creation with required fields."""
        config = agent_model_module.ExternalA2AAgentConfig(
            agent_id="ext-agent-123",
            name="External Agent",
            description="An external A2A agent",
            url="https://external-agent.com/a2a"
        )
        assert config.agent_id == "ext-agent-123"
        assert config.name == "External Agent"
        assert config.description == "An external A2A agent"
        assert config.url == "https://external-agent.com/a2a"
        assert config.api_key is None
        assert config.transport_type == "http-streaming"
        assert config.protocol_version == "1.0"
        assert config.protocol_type == agent_model_module.PROTOCOL_JSONRPC
        assert config.timeout == 300.0
        assert config.raw_card is None

    def test_external_a2a_agent_config_with_all_fields(self):
        """Test ExternalA2AAgentConfig creation with all fields."""
        config = agent_model_module.ExternalA2AAgentConfig(
            agent_id="ext-agent-456",
            name="Full Config Agent",
            description="Agent with full configuration",
            url="https://example.com/a2a",
            api_key="secret-api-key",
            transport_type="http-polling",
            protocol_version="2.0",
            protocol_type=agent_model_module.PROTOCOL_HTTP_JSON,
            timeout=600.0,
            raw_card={"skills": []}
        )
        assert config.agent_id == "ext-agent-456"
        assert config.api_key == "secret-api-key"
        assert config.transport_type == "http-polling"
        assert config.protocol_version == "2.0"
        assert config.protocol_type == agent_model_module.PROTOCOL_HTTP_JSON
        assert config.timeout == 600.0
        assert config.raw_card == {"skills": []}

    def test_external_a2a_agent_config_default_values(self):
        """Test ExternalA2AAgentConfig has correct default values."""
        config = agent_model_module.ExternalA2AAgentConfig(
            agent_id="test-id",
            name="Test",
            description="",
            url="https://test.com"
        )
        assert config.transport_type == "http-streaming"
        assert config.protocol_version == "1.0"
        assert config.protocol_type == agent_model_module.PROTOCOL_JSONRPC
        assert config.timeout == 300.0

    def test_external_a2a_agent_config_with_raw_card_skills(self):
        """Test ExternalA2AAgentConfig auto-enhances description from raw_card skills."""
        config = agent_model_module.ExternalA2AAgentConfig(
            agent_id="skill-agent",
            name="Skill Agent",
            description="",  # Start with empty description
            url="https://skill-agent.com",
            raw_card={
                "skills": [
                    {
                        "name": "Web Search",
                        "description": "Search the web",
                        "examples": ["search for news", "find weather"]
                    },
                    {
                        "name": "Calculator",
                        "description": "Perform calculations",
                        "examples": ["calculate 2+2"]
                    }
                ]
            }
        )
        # After model_post_init, description should be enhanced
        assert "Web Search" in config.description
        assert "Calculator" in config.description
        assert "调用示例" in config.description

    def test_external_a2a_agent_config_skills_without_examples(self):
        """Test ExternalA2AAgentConfig handles skills without examples."""
        config = agent_model_module.ExternalA2AAgentConfig(
            agent_id="no-examples-agent",
            name="No Examples Agent",
            description="",
            url="https://no-examples.com",
            raw_card={
                "skills": [
                    {"name": "Simple Skill", "description": "No examples here"}
                ]
            }
        )
        # Should not crash and should have capability names
        assert "Simple Skill" in config.description
        assert "调用示例" not in config.description

    def test_external_a2a_agent_config_empty_skills(self):
        """Test ExternalA2AAgentConfig handles empty skills list."""
        config = agent_model_module.ExternalA2AAgentConfig(
            agent_id="empty-skills-agent",
            name="Empty Skills Agent",
            description="Existing description",
            url="https://empty.com",
            raw_card={"skills": []}
        )
        # Description should remain unchanged
        assert config.description == "Existing description"

    def test_external_a2a_agent_config_no_raw_card(self):
        """Test ExternalA2AAgentConfig without raw_card doesn't crash."""
        config = agent_model_module.ExternalA2AAgentConfig(
            agent_id="no-card-agent",
            name="No Card Agent",
            description="Agent without raw card",
            url="https://no-card.com"
        )
        assert config.raw_card is None
        assert config.description == "Agent without raw card"

    def test_external_a2a_agent_config_to_a2a_agent_info(self):
        """Test ExternalA2AAgentConfig.to_a2a_agent_info converts correctly."""
        config = agent_model_module.ExternalA2AAgentConfig(
            agent_id="convert-agent",
            name="Convert Agent",
            description="A test agent",
            url="https://convert.com/a2a",
            api_key="converted-key",
            transport_type="http-polling",
            protocol_version="1.5",
            protocol_type=agent_model_module.PROTOCOL_HTTP_JSON,
            timeout=450.0,
            raw_card={"test": "data"}
        )

        agent_info = config.to_a2a_agent_info()

        # Verify the mock was called with correct arguments
        mock_a2a_agent_proxy_class = _module_mocks["sdk.nexent.core.agents.a2a_agent_proxy"].A2AAgentInfo
        mock_a2a_agent_proxy_class.assert_called_once()
        call_kwargs = mock_a2a_agent_proxy_class.call_args[1]
        assert call_kwargs["agent_id"] == "convert-agent"
        assert call_kwargs["name"] == "Convert Agent"
        assert call_kwargs["url"] == "https://convert.com/a2a"
        assert call_kwargs["api_key"] == "converted-key"
        assert call_kwargs["transport_type"] == "http-polling"
        assert call_kwargs["protocol_version"] == "1.5"
        assert call_kwargs["protocol_type"] == agent_model_module.PROTOCOL_HTTP_JSON
        assert call_kwargs["timeout"] == 450.0
        assert call_kwargs["raw_card"] == {"test": "data"}

    def test_external_a2a_agent_config_multiple_skills_examples(self):
        """Test ExternalA2AAgentConfig handles multiple skills with many examples."""
        config = agent_model_module.ExternalA2AAgentConfig(
            agent_id="multi-skill-agent",
            name="Multi Skill Agent",
            description="",
            url="https://multi.com",
            raw_card={
                "skills": [
                    {
                        "name": "Skill1",
                        "examples": ["ex1", "ex2", "ex3", "ex4"]
                    },
                    {
                        "name": "Skill2",
                        "examples": ["ex5", "ex6"]
                    }
                ]
            }
        )
        # Should pick first 8 examples (limited in _build_skills_description)
        assert "Skill1" in config.description
        assert "Skill2" in config.description
        assert "调用示例" in config.description

    def test_external_a2a_agent_config_with_existing_description_appends_skills(self):
        """Test ExternalA2AAgentConfig appends skills info to existing description."""
        original_desc = "This is an existing agent description."
        config = agent_model_module.ExternalA2AAgentConfig(
            agent_id="append-agent",
            name="Append Agent",
            description=original_desc,
            url="https://append.com",
            raw_card={
                "skills": [
                    {"name": "Web Search", "examples": ["search news"]}
                ]
            }
        )
        # Original description should be preserved and skills appended
        assert original_desc in config.description
        assert "Web Search" in config.description
        assert "调用示例" in config.description
        # Skills info should come after original description
        desc_parts = config.description.split("\n\n")
        assert len(desc_parts) == 2
        assert desc_parts[0] == original_desc

    def test_external_a2a_agent_config_raw_card_without_skills_key(self):
        """Test ExternalA2AAgentConfig handles raw_card without 'skills' key."""
        config = agent_model_module.ExternalA2AAgentConfig(
            agent_id="no-skills-key-agent",
            name="No Skills Key Agent",
            description="Agent with raw card but no skills",
            url="https://no-skills-key.com",
            raw_card={
                "name": "Some Agent",
                "version": "1.0"
            }
        )
        # Description should remain unchanged since no skills
        assert config.description == "Agent with raw card but no skills"

    def test_external_a2a_agent_config_skills_with_empty_name(self):
        """Test ExternalA2AAgentConfig handles skills with empty name."""
        config = agent_model_module.ExternalA2AAgentConfig(
            agent_id="empty-name-agent",
            name="Empty Name Agent",
            description="",
            url="https://empty-name.com",
            raw_card={
                "skills": [
                    {"name": "", "examples": ["example1"]},
                    {"name": "Valid Skill", "examples": []}
                ]
            }
        )
        # Should include valid skill name but not empty string
        assert "Valid Skill" in config.description
        assert '""' not in config.description.split("[此助手可处理:")[1] if "[此助手可处理:" in config.description else True

    def test_external_a2a_agent_config_examples_limit(self):
        """Test ExternalA2AAgentConfig limits examples to 8 total."""
        many_examples = [f"example_{i}" for i in range(15)]
        config = agent_model_module.ExternalA2AAgentConfig(
            agent_id="many-examples-agent",
            name="Many Examples Agent",
            description="",
            url="https://many-examples.com",
            raw_card={
                "skills": [
                    {"name": "Skill", "examples": many_examples}
                ]
            }
        )
        # Should only include first 8 examples
        example_part = config.description.split("调用示例:")[1] if "调用示例:" in config.description else ""
        example_count = example_part.count('"')
        assert example_count <= 16  # 8 examples * 2 quotes each

    def test_external_a2a_agent_config_build_skills_description_directly(self):
        """Test _build_skills_description method directly."""
        config = agent_model_module.ExternalA2AAgentConfig(
            agent_id="direct-test-agent",
            name="Direct Test",
            description="",
            url="https://direct.com",
            raw_card={
                "skills": [
                    {"name": "Test Skill", "examples": ["test1", "test2"]}
                ]
            }
        )
        # Call the method directly
        result = config._build_skills_description()
        assert "[此助手可处理: Test Skill]" in result
        assert "调用示例" in result
        assert "test1" in result
        assert "test2" in result

    def test_external_a2a_agent_config_build_skills_returns_empty_for_no_raw_card(self):
        """Test _build_skills_description returns empty string when raw_card is None."""
        config = agent_model_module.ExternalA2AAgentConfig(
            agent_id="no-card-agent",
            name="No Card",
            description="Test",
            url="https://test.com"
        )
        result = config._build_skills_description()
        assert result == ""

    def test_external_a2a_agent_config_skill_examples_from_multiple_skills(self):
        """Test _build_skills_description collects examples from multiple skills (max 3 per skill)."""
        config = agent_model_module.ExternalA2AAgentConfig(
            agent_id="multi-examples-agent",
            name="Multi Examples",
            description="",
            url="https://multi-examples.com",
            raw_card={
                "skills": [
                    {"name": "Skill1", "examples": ["ex1", "ex2", "ex3", "ex4", "ex5"]},
                    {"name": "Skill2", "examples": ["ex6", "ex7", "ex8", "ex9"]}
                ]
            }
        )
        # Should take first 3 examples from each skill = 6 examples max
        result = config._build_skills_description()
        assert "Skill1" in result
        assert "Skill2" in result
        assert "ex1" in result
        assert "ex4" not in result or "ex5" not in result  # Not all 5 from Skill1


# ----------------------------------------------------------------------------
# Tests for AgentConfig
# ----------------------------------------------------------------------------

class TestAgentConfig:
    """Tests for AgentConfig Pydantic model."""

    def test_agent_config_creation_with_all_fields(self):
        """Test AgentConfig creation with all fields."""
        config = agent_model_module.AgentConfig(
            name="test_agent",
            description="A test agent",
            prompt_templates={"system": "You are helpful"},
            tools=[],
            max_steps=10,
            model_name="gpt-4",
            provide_run_summary=True,
            instructions="Additional instructions",
            managed_agents=[],
            external_a2a_agents=[]
        )
        assert config.name == "test_agent"
        assert config.description == "A test agent"
        assert config.prompt_templates == {"system": "You are helpful"}
        assert config.tools == []
        assert config.max_steps == 10
        assert config.model_name == "gpt-4"
        assert config.provide_run_summary is True
        assert config.instructions == "Additional instructions"

    def test_agent_config_defaults(self):
        """Test AgentConfig has correct default values."""
        config = agent_model_module.AgentConfig(
            name="default_agent",
            description="An agent with defaults",
            tools=[],
            model_name="default-model"
        )
        assert config.prompt_templates is None
        assert config.max_steps == 5
        assert config.provide_run_summary is False
        assert config.instructions is None
        assert config.managed_agents == []
        assert config.external_a2a_agents == []

    def test_agent_config_with_tools(self):
        """Test AgentConfig with tools list."""
        tool = agent_model_module.ToolConfig(
            class_name="TavilySearchTool",
            name=None,
            description=None,
            inputs=None,
            output_type=None,
            params={},
            source="local"
        )
        config = agent_model_module.AgentConfig(
            name="agent_with_tools",
            description="Agent with tools",
            tools=[tool],
            model_name="test"
        )
        assert len(config.tools) == 1
        assert config.tools[0].class_name == "TavilySearchTool"

    def test_agent_config_with_managed_agents(self):
        """Test AgentConfig with nested managed agents."""
        sub_agent = agent_model_module.AgentConfig(
            name="sub_agent",
            description="A sub agent",
            tools=[],
            model_name="sub-model"
        )
        config = agent_model_module.AgentConfig(
            name="parent_agent",
            description="Parent agent with sub-agents",
            tools=[],
            model_name="parent-model",
            managed_agents=[sub_agent]
        )
        assert len(config.managed_agents) == 1
        assert config.managed_agents[0].name == "sub_agent"

    def test_agent_config_with_external_a2a_agents(self):
        """Test AgentConfig with external A2A agents."""
        ext_agent = agent_model_module.ExternalA2AAgentConfig(
            agent_id="ext-1",
            name="External",
            description="External agent",
            url="https://external.com"
        )
        config = agent_model_module.AgentConfig(
            name="agent_with_external",
            description="Agent calling external A2A agents",
            tools=[],
            model_name="test",
            external_a2a_agents=[ext_agent]
        )
        assert len(config.external_a2a_agents) == 1
        assert config.external_a2a_agents[0].agent_id == "ext-1"

    def test_agent_config_max_steps_boundary(self):
        """Test AgentConfig accepts boundary max_steps values."""
        config_min = agent_model_module.AgentConfig(
            name="min_steps",
            description="Min steps",
            tools=[],
            model_name="test",
            max_steps=1
        )
        assert config_min.max_steps == 1

        config_max = agent_model_module.AgentConfig(
            name="max_steps",
            description="Max steps",
            tools=[],
            model_name="test",
            max_steps=100
        )
        assert config_max.max_steps == 100


# ----------------------------------------------------------------------------
# Tests for model_rebuild
# ----------------------------------------------------------------------------

class TestModelRebuild:
    """Tests for Pydantic model_rebuild calls."""

    def test_agent_config_can_be_rebuilt(self):
        """Test AgentConfig.model_rebuild() works correctly."""
        # This should not raise any error
        agent_model_module.AgentConfig.model_rebuild()
        assert True

    def test_agent_run_info_can_be_rebuilt(self):
        """Test AgentRunInfo.model_rebuild() works correctly."""
        # This should not raise any error
        agent_model_module.AgentRunInfo.model_rebuild()
        assert True


if __name__ == "__main__":
    pytest.main([__file__])
