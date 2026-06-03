"""
Unit tests for sdk.nexent.core.agents ContextComponent and ContextStrategy classes.

This module tests:
- ContextComponent abstract base class
- SystemPromptComponent
- ToolsComponent
- SkillsComponent
- MemoryComponent
- KnowledgeBaseComponent
- ManagedAgentsComponent
- ExternalAgentsComponent
- ContextStrategy abstract base class
- FullStrategy
- TokenBudgetStrategy
- BufferedStrategy
- PriorityWeightedStrategy
- Extended ContextManagerConfig
"""
import os
import sys
import types
import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest

TEST_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = TEST_ROOT.parent

for _path in (str(PROJECT_ROOT), str(TEST_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)


def _create_mock_smolagents():
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


_module_mocks = _create_mock_modules()
_original_modules = {}
for name, module in _module_mocks.items():
    if name in sys.modules:
        _original_modules[name] = sys.modules[name]
    sys.modules[name] = module


def _load_agent_model_module():
    project_root = os.path.dirname(
        os.path.dirname(
            os.path.dirname(
                os.path.dirname(
                    os.path.dirname(os.path.abspath(__file__))
                )
            )
        )
    )
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


def _load_summary_config_module():
    project_root = os.path.dirname(
        os.path.dirname(
            os.path.dirname(
                os.path.dirname(
                    os.path.dirname(os.path.abspath(__file__))
                )
            )
        )
    )
    summary_config_path = os.path.join(project_root, "sdk", "nexent", "core", "agents", "summary_config.py")

    spec = importlib.util.spec_from_file_location("sdk.nexent.core.agents.summary_config", summary_config_path)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "sdk.nexent.core.agents"
    sys.modules["sdk.nexent.core.agents.summary_config"] = module

    spec.loader.exec_module(module)
    return module


agent_model_module = _load_agent_model_module()
summary_config_module = _load_summary_config_module()


def _restore_real_modules() -> None:
    """
    Roll back every sys.modules entry this file installed at import time so
    sibling test trees (e.g. test_context_utils.py) can still import the
    real packages. agent_model_module already captured the mock classes it
    needs as module-level attributes, so swapping sys.modules back is safe
    for our own tests.

    Strategy: for every name we injected, drop it from sys.modules if it
    still points at a bare ModuleType (no __spec__, no __file__), then
    force-reimport so real packages reload from disk.
    """
    import importlib

    injected_names = list(_module_mocks.keys())

    for key in injected_names:
        mod = sys.modules.get(key)
        if mod is not None and getattr(mod, "__spec__", None) is None and not hasattr(mod, "__file__"):
            del sys.modules[key]

    for key in injected_names:
        try:
            importlib.import_module(key)
        except (ImportError, Exception):
            # Some mocked names (e.g. botocore.crt, sdk.nexent.core.agents.a2a_agent_proxy)
            # may not exist as real packages — tolerate.
            pass


_restore_real_modules()


class TestSystemPromptComponent:
    """Tests for SystemPromptComponent."""

    def test_creation_with_content(self):
        comp = agent_model_module.SystemPromptComponent(
            content="You are a helpful assistant.",
            priority=20
        )
        assert comp.component_type == "system_prompt"
        assert comp.content == "You are a helpful assistant."
        assert comp.priority == 20
        assert comp.template_name is None

    def test_to_messages_returns_system_role(self):
        comp = agent_model_module.SystemPromptComponent(
            content="Test prompt content"
        )
        messages = comp.to_messages()
        assert len(messages) == 1
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "Test prompt content"

    def test_with_template_name(self):
        comp = agent_model_module.SystemPromptComponent(
            content="Rendered content",
            template_name="managed_system_prompt_template_en.yaml"
        )
        assert comp.template_name == "managed_system_prompt_template_en.yaml"

    def test_estimate_tokens(self):
        comp = agent_model_module.SystemPromptComponent(
            content="This is a test prompt with some words."
        )
        tokens = comp.estimate_tokens(chars_per_token=1.5)
        assert tokens > 0
        assert tokens == int(len("This is a test prompt with some words.") / 1.5)

    def test_default_priority(self):
        comp = agent_model_module.SystemPromptComponent(content="test")
        assert comp.priority == 10


class TestToolsComponent:
    """Tests for ToolsComponent."""

    def test_creation_empty(self):
        comp = agent_model_module.ToolsComponent()
        assert comp.component_type == "tools"
        assert comp.tools == []
        assert comp.formatted_description == ""

    def test_creation_with_tools(self):
        comp = agent_model_module.ToolsComponent(
            tools=[{"name": "search", "description": "Web search"}],
            formatted_description="Available tools: search, calculator"
        )
        assert len(comp.tools) == 1
        assert comp.formatted_description == "Available tools: search, calculator"

    def test_to_messages_with_formatted_description(self):
        comp = agent_model_module.ToolsComponent(
            formatted_description="Tool descriptions here"
        )
        messages = comp.to_messages()
        assert len(messages) == 1
        assert messages[0]["role"] == "system"

    def test_to_messages_empty_returns_empty_list(self):
        comp = agent_model_module.ToolsComponent()
        messages = comp.to_messages()
        assert messages == []

    def test_add_tool(self):
        comp = agent_model_module.ToolsComponent()
        comp.add_tool("web_search", "Search the web", '{"query": "str"}', "string")
        assert len(comp.tools) == 1
        assert comp.tools[0]["name"] == "web_search"
        assert comp.tools[0]["description"] == "Search the web"

    def test_add_multiple_tools(self):
        comp = agent_model_module.ToolsComponent()
        comp.add_tool("tool1", "desc1", "input1", "output1")
        comp.add_tool("tool2", "desc2", "input2", "output2")
        assert len(comp.tools) == 2


class TestSkillsComponent:
    """Tests for SkillsComponent."""

    def test_creation_empty(self):
        comp = agent_model_module.SkillsComponent()
        assert comp.component_type == "skills"
        assert comp.skills == []
        assert comp.formatted_description == ""

    def test_creation_with_skills(self):
        comp = agent_model_module.SkillsComponent(
            skills=[{"name": "coding", "description": "Write code"}],
            formatted_description="Skills: coding, debugging"
        )
        assert len(comp.skills) == 1

    def test_to_messages_with_content(self):
        comp = agent_model_module.SkillsComponent(formatted_description="Skill summaries")
        messages = comp.to_messages()
        assert len(messages) == 1
        assert messages[0]["role"] == "system"

    def test_to_messages_empty(self):
        comp = agent_model_module.SkillsComponent()
        assert comp.to_messages() == []

    def test_add_skill(self):
        comp = agent_model_module.SkillsComponent()
        comp.add_skill("python_coding", "Write Python code", ["example1", "example2"])
        assert len(comp.skills) == 1
        assert comp.skills[0]["name"] == "python_coding"
        assert comp.skills[0]["examples"] == ["example1", "example2"]

    def test_add_skill_without_examples(self):
        comp = agent_model_module.SkillsComponent()
        comp.add_skill("skill_name", "skill desc")
        assert comp.skills[0]["examples"] == []


class TestMemoryComponent:
    """Tests for MemoryComponent."""

    def test_creation_empty(self):
        comp = agent_model_module.MemoryComponent()
        assert comp.component_type == "memory"
        assert comp.memories == []
        assert comp.formatted_content == ""
        assert comp.search_query is None

    def test_creation_with_memories(self):
        comp = agent_model_module.MemoryComponent(
            memories=[{"content": "User prefers Python"}],
            formatted_content="Memory context: user preferences",
            search_query="user preferences"
        )
        assert len(comp.memories) == 1
        assert comp.search_query == "user preferences"

    def test_to_messages_with_content(self):
        comp = agent_model_module.MemoryComponent(formatted_content="Retrieved memories")
        messages = comp.to_messages()
        assert len(messages) == 1

    def test_to_messages_empty(self):
        comp = agent_model_module.MemoryComponent()
        assert comp.to_messages() == []

    def test_add_memory(self):
        comp = agent_model_module.MemoryComponent()
        comp.add_memory("User likes dark mode", "user", {"timestamp": "2024-01-01"})
        assert len(comp.memories) == 1
        assert comp.memories[0]["content"] == "User likes dark mode"
        assert comp.memories[0]["memory_type"] == "user"

    def test_add_memory_without_metadata(self):
        comp = agent_model_module.MemoryComponent()
        comp.add_memory("test memory", "agent")
        assert comp.memories[0]["metadata"] == {}


class TestKnowledgeBaseComponent:
    """Tests for KnowledgeBaseComponent."""

    def test_creation_empty(self):
        comp = agent_model_module.KnowledgeBaseComponent()
        assert comp.component_type == "knowledge_base"
        assert comp.summary == ""
        assert comp.kb_ids == []

    def test_creation_with_summary(self):
        comp = agent_model_module.KnowledgeBaseComponent(
            summary="KB summary content",
            kb_ids=["kb-1", "kb-2"],
            priority=15
        )
        assert comp.summary == "KB summary content"
        assert comp.kb_ids == ["kb-1", "kb-2"]
        assert comp.priority == 15

    def test_to_messages_with_summary(self):
        comp = agent_model_module.KnowledgeBaseComponent(summary="Knowledge base summary")
        messages = comp.to_messages()
        assert len(messages) == 1

    def test_to_messages_empty(self):
        comp = agent_model_module.KnowledgeBaseComponent()
        assert comp.to_messages() == []


class TestManagedAgentsComponent:
    """Tests for ManagedAgentsComponent."""

    def test_creation_empty(self):
        comp = agent_model_module.ManagedAgentsComponent()
        assert comp.component_type == "managed_agents"
        assert comp.agents == []
        assert comp.formatted_description == ""

    def test_creation_with_agents(self):
        comp = agent_model_module.ManagedAgentsComponent(
            agents=[{"name": "sub_agent", "description": "A sub agent"}],
            formatted_description="Sub-agents available"
        )
        assert len(comp.agents) == 1

    def test_to_messages_with_content(self):
        comp = agent_model_module.ManagedAgentsComponent(formatted_description="Managed agents list")
        messages = comp.to_messages()
        assert len(messages) == 1

    def test_to_messages_empty(self):
        comp = agent_model_module.ManagedAgentsComponent()
        assert comp.to_messages() == []

    def test_add_agent(self):
        comp = agent_model_module.ManagedAgentsComponent()
        comp.add_agent("research_agent", "Research assistant", ["web_search", "read_file"])
        assert len(comp.agents) == 1
        assert comp.agents[0]["name"] == "research_agent"
        assert comp.agents[0]["tools"] == ["web_search", "read_file"]

    def test_add_agent_without_tools(self):
        comp = agent_model_module.ManagedAgentsComponent()
        comp.add_agent("agent_name", "agent desc")
        assert comp.agents[0]["tools"] == []


class TestExternalAgentsComponent:
    """Tests for ExternalAgentsComponent."""

    def test_creation_empty(self):
        comp = agent_model_module.ExternalAgentsComponent()
        assert comp.component_type == "external_a2a_agents"
        assert comp.agents == []
        assert comp.formatted_description == ""

    def test_creation_with_agents(self):
        comp = agent_model_module.ExternalAgentsComponent(
            agents=[{"agent_id": "ext-1", "name": "External Agent"}],
            formatted_description="External A2A agents"
        )
        assert len(comp.agents) == 1

    def test_to_messages_with_content(self):
        comp = agent_model_module.ExternalAgentsComponent(formatted_description="External agents")
        messages = comp.to_messages()
        assert len(messages) == 1

    def test_to_messages_empty(self):
        comp = agent_model_module.ExternalAgentsComponent()
        assert comp.to_messages() == []

    def test_add_agent(self):
        comp = agent_model_module.ExternalAgentsComponent()
        comp.add_agent("ext-agent-123", "External Helper", "An external A2A agent", "https://external.com/a2a")
        assert len(comp.agents) == 1
        assert comp.agents[0]["agent_id"] == "ext-agent-123"
        assert comp.agents[0]["url"] == "https://external.com/a2a"


class TestFullStrategy:
    """Tests for FullStrategy."""

    def test_select_components_returns_all(self):
        strategy = agent_model_module.FullStrategy()
        components = [
            agent_model_module.SystemPromptComponent(content="test1", priority=10),
            agent_model_module.ToolsComponent(formatted_description="test2", priority=20),
            agent_model_module.MemoryComponent(formatted_content="test3", priority=5),
        ]
        selected = strategy.select_components(components, 1000, {})
        assert len(selected) == 3

    def test_select_components_sorted_by_priority(self):
        strategy = agent_model_module.FullStrategy()
        components = [
            agent_model_module.SystemPromptComponent(content="low", priority=5),
            agent_model_module.ToolsComponent(formatted_description="high", priority=30),
            agent_model_module.MemoryComponent(formatted_content="mid", priority=15),
        ]
        selected = strategy.select_components(components, 1000, {})
        assert selected[0].priority == 30
        assert selected[1].priority == 15
        assert selected[2].priority == 5

    def test_get_strategy_name(self):
        strategy = agent_model_module.FullStrategy()
        assert strategy.get_strategy_name() == "full"


class TestTokenBudgetStrategy:
    """Tests for TokenBudgetStrategy."""

    def test_select_within_budget(self):
        strategy = agent_model_module.TokenBudgetStrategy()
        components = [
            agent_model_module.SystemPromptComponent(content="short", priority=10, token_estimate=100),
            agent_model_module.ToolsComponent(formatted_description="medium", priority=20, token_estimate=300),
            agent_model_module.MemoryComponent(formatted_content="large", priority=5, token_estimate=500),
        ]
        selected = strategy.select_components(components, 400, {})
        assert len(selected) == 2
        total_tokens = sum(c.token_estimate for c in selected)
        assert total_tokens <= 400

    def test_select_respects_component_budget(self):
        strategy = agent_model_module.TokenBudgetStrategy()
        components = [
            agent_model_module.SystemPromptComponent(content="test", priority=10, token_estimate=200),
            agent_model_module.ToolsComponent(formatted_description="test", priority=20, token_estimate=200),
        ]
        component_budgets = {"system_prompt": 100}
        selected = strategy.select_components(components, 1000, component_budgets)
        system_comps = [c for c in selected if c.component_type == "system_prompt"]
        assert len(system_comps) == 0

    def test_select_empty_components(self):
        strategy = agent_model_module.TokenBudgetStrategy()
        selected = strategy.select_components([], 1000, {})
        assert selected == []

    def test_get_strategy_name(self):
        strategy = agent_model_module.TokenBudgetStrategy()
        assert strategy.get_strategy_name() == "token_budget"

    def test_uses_estimate_tokens_when_no_token_estimate(self):
        strategy = agent_model_module.TokenBudgetStrategy()
        comp = agent_model_module.SystemPromptComponent(content="test content here")
        comp.token_estimate = 0
        tokens = comp.estimate_tokens()
        assert tokens > 0


class TestBufferedStrategy:
    """Tests for BufferedStrategy."""

    def test_default_buffer_size(self):
        strategy = agent_model_module.BufferedStrategy()
        assert strategy.buffer_size == 10

    def test_custom_buffer_size(self):
        strategy = agent_model_module.BufferedStrategy(buffer_size=5)
        assert strategy.buffer_size == 5

    def test_select_keeps_last_n_per_type(self):
        strategy = agent_model_module.BufferedStrategy(buffer_size=2)
        components = [
            agent_model_module.ToolsComponent(formatted_description="tool1", priority=10),
            agent_model_module.ToolsComponent(formatted_description="tool2", priority=11),
            agent_model_module.ToolsComponent(formatted_description="tool3", priority=12),
            agent_model_module.SkillsComponent(formatted_description="skill1", priority=20),
        ]
        selected = strategy.select_components(components, 1000, {})
        tools_selected = [c for c in selected if c.component_type == "tools"]
        assert len(tools_selected) == 2

    def test_select_empty_components(self):
        strategy = agent_model_module.BufferedStrategy()
        selected = strategy.select_components([], 1000, {})
        assert selected == []

    def test_get_strategy_name(self):
        strategy = agent_model_module.BufferedStrategy()
        assert strategy.get_strategy_name() == "buffered"


class TestPriorityWeightedStrategy:
    """Tests for PriorityWeightedStrategy."""

    def test_default_relevance_threshold(self):
        strategy = agent_model_module.PriorityWeightedStrategy()
        assert strategy.relevance_threshold == 0.5

    def test_custom_relevance_threshold(self):
        strategy = agent_model_module.PriorityWeightedStrategy(relevance_threshold=0.8)
        assert strategy.relevance_threshold == 0.8

    def test_select_with_relevance_scores(self):
        strategy = agent_model_module.PriorityWeightedStrategy(relevance_threshold=0.5)
        components = [
            agent_model_module.SystemPromptComponent(
                content="high relevance", priority=10,
                metadata={"relevance_score": 0.9}
            ),
            agent_model_module.ToolsComponent(
                formatted_description="low relevance", priority=20,
                metadata={"relevance_score": 0.3}
            ),
        ]
        selected = strategy.select_components(components, 1000, {})
        high_rel = [c for c in selected if c.metadata.get("relevance_score", 1.0) >= 0.5]
        assert len(high_rel) >= 1

    def test_select_filters_below_threshold(self):
        strategy = agent_model_module.PriorityWeightedStrategy(relevance_threshold=0.7)
        components = [
            agent_model_module.SystemPromptComponent(
                content="below", priority=10,
                metadata={"relevance_score": 0.5}
            ),
            agent_model_module.ToolsComponent(
                formatted_description="above", priority=20,
                metadata={"relevance_score": 0.8}
            ),
        ]
        selected = strategy.select_components(components, 1000, {})
        for c in selected:
            assert c.metadata.get("relevance_score", 1.0) >= 0.7

    def test_get_strategy_name(self):
        strategy = agent_model_module.PriorityWeightedStrategy()
        assert strategy.get_strategy_name() == "priority"


class TestExtendedContextManagerConfig:
    """Tests for extended ContextManagerConfig."""

    def test_default_strategy(self):
        config = summary_config_module.ContextManagerConfig()
        assert config.strategy == "token_budget"

    def test_all_injection_flags_default_true(self):
        config = summary_config_module.ContextManagerConfig()
        assert config.inject_system_prompt is True
        assert config.inject_tools is True
        assert config.inject_skills is True
        assert config.inject_memory is True
        assert config.inject_knowledge_base is True
        assert config.inject_agent_definitions is True
        assert config.inject_app_context is True

    def test_component_budgets_defaults(self):
        config = summary_config_module.ContextManagerConfig()
        assert "system_prompt" in config.component_budgets
        assert "tools" in config.component_budgets
        assert config.component_budgets["system_prompt"] == 4000

    def test_custom_strategy(self):
        config = summary_config_module.ContextManagerConfig(strategy="full")
        assert config.strategy == "full"

    def test_disable_injection_flags(self):
        config = summary_config_module.ContextManagerConfig(
            inject_memory=False,
            inject_knowledge_base=False
        )
        assert config.inject_memory is False
        assert config.inject_knowledge_base is False

    def test_custom_component_budgets(self):
        config = summary_config_module.ContextManagerConfig(
            component_budgets={"system_prompt": 2000, "tools": 1500}
        )
        assert config.component_budgets["system_prompt"] == 2000

    def test_buffer_size_per_component(self):
        config = summary_config_module.ContextManagerConfig()
        assert config.buffer_size_per_component == 10

    def test_existing_fields_preserved(self):
        config = summary_config_module.ContextManagerConfig(
            enabled=True,
            token_threshold=5000,
            keep_recent_steps=3
        )
        assert config.enabled is True
        assert config.token_threshold == 5000
        assert config.keep_recent_steps == 3


class TestAgentConfigWithContextComponents:
    """Tests for AgentConfig with context_components field."""

    def test_agent_config_with_context_components(self):
        components = [
            agent_model_module.SystemPromptComponent(content="test prompt"),
            agent_model_module.ToolsComponent(formatted_description="test tools"),
        ]
        config = agent_model_module.AgentConfig(
            name="test_agent",
            description="Test agent",
            tools=[],
            model_name="test-model",
            context_components=components
        )
        assert len(config.context_components) == 2
        assert config.context_components[0].component_type == "system_prompt"

    def test_agent_config_default_context_components_none(self):
        config = agent_model_module.AgentConfig(
            name="test_agent",
            description="Test agent",
            tools=[],
            model_name="test-model"
        )
        assert config.context_components is None


if __name__ == "__main__":
    pytest.main([__file__])