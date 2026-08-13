"""
Unit tests for _find_tool_call_calls and parse_code_blobs functions
in sdk.nexent.core.agents.core_agent module.

Focus: nested bracket handling in tool call parameters.
"""
import pytest
import importlib.util
import os
import sys
from types import ModuleType
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Mock setup for external dependencies (minimal set to load core_agent module)
# ---------------------------------------------------------------------------

def _create_minimal_mocks():
    """Create only the mock modules required to import core_agent."""
    mocks = {}

    # --- smolagents ---
    smolagents = ModuleType("smolagents")
    smolagents.__path__ = []

    agents_mod = ModuleType("smolagents.agents")
    for name in ["CodeAgent", "handle_agent_output_types", "AgentError", "ActionOutput", "RunResult"]:
        setattr(agents_mod, name, MagicMock(name=f"agents.{name}"))
    setattr(smolagents, "agents", agents_mod)

    local_python_mod = ModuleType("smolagents.local_python_executor")
    setattr(local_python_mod, "fix_final_answer_code", MagicMock())
    setattr(smolagents, "local_python_executor", local_python_mod)

    memory_mod = ModuleType("smolagents.memory")
    for name in ["ActionStep", "PlanningStep", "FinalAnswerStep", "ToolCall",
                 "TaskStep", "SystemPromptStep"]:
        setattr(memory_mod, name, MagicMock(name=f"memory.{name}"))
    setattr(smolagents, "memory", memory_mod)

    models_mod = ModuleType("smolagents.models")
    setattr(models_mod, "ChatMessage", MagicMock())
    setattr(models_mod, "MessageRole", MagicMock())
    setattr(models_mod, "CODEAGENT_RESPONSE_FORMAT", MagicMock())
    setattr(smolagents, "models", models_mod)

    monitoring_mod = ModuleType("smolagents.monitoring")
    for name in ["LogLevel", "Timing", "YELLOW_HEX", "TokenUsage"]:
        setattr(monitoring_mod, name, MagicMock(name=f"monitoring.{name}"))
    setattr(smolagents, "monitoring", monitoring_mod)

    utils_mod = ModuleType("smolagents.utils")
    for name in ["AgentExecutionError", "AgentGenerationError", "AgentMaxStepsError",
                 "truncate_content", "extract_code_from_text"]:
        setattr(utils_mod, name, MagicMock(name=f"utils.{name}"))
    setattr(smolagents, "utils", utils_mod)

    mocks["smolagents"] = smolagents
    mocks["smolagents.agents"] = agents_mod
    mocks["smolagents.local_python_executor"] = local_python_mod
    mocks["smolagents.memory"] = memory_mod
    mocks["smolagents.models"] = models_mod
    mocks["smolagents.monitoring"] = monitoring_mod
    mocks["smolagents.utils"] = utils_mod

    # --- rich ---
    rich_console = ModuleType("rich.console")
    rich_text = ModuleType("rich.text")
    rich = ModuleType("rich")
    setattr(rich, "console", rich_console)
    setattr(rich, "text", rich_text)
    setattr(rich_console, "Group", MagicMock())
    setattr(rich_text, "Text", MagicMock())
    mocks["rich"] = rich
    mocks["rich.console"] = rich_console
    mocks["rich.text"] = rich_text

    # --- jinja2 ---
    jinja2 = ModuleType("jinja2")
    setattr(jinja2, "Template", MagicMock())
    setattr(jinja2, "StrictUndefined", MagicMock())
    mocks["jinja2"] = jinja2

    # --- observer ---
    observer = ModuleType("sdk.nexent.core.utils.observer")

    class ProcessType:
        STEP_COUNT = "STEP_COUNT"
        PARSE = "PARSE"
        EXECUTION_LOGS = "EXECUTION_LOGS"
        AGENT_NEW_RUN = "AGENT_NEW_RUN"
        AGENT_FINISH = "AGENT_FINISH"
        FINAL_ANSWER = "FINAL_ANSWER"
        ERROR = "ERROR"
        OTHER = "OTHER"

    class MessageObserver:
        def __init__(self):
            self.add_message = MagicMock()

    setattr(observer, "MessageObserver", MessageObserver)
    setattr(observer, "ProcessType", ProcessType)
    mocks["sdk.nexent.core.utils.observer"] = observer

    # --- token_estimation ---
    token_est = ModuleType("sdk.nexent.core.utils.token_estimation")
    token_est.msg_token_count = MagicMock(return_value=0)
    mocks["sdk.nexent.core.utils.token_estimation"] = token_est

    # --- agent_model ---
    agent_model = ModuleType("sdk.nexent.core.agents.agent_model")
    agent_model.AgentVerificationConfig = MagicMock()
    mocks["sdk.nexent.core.agents.agent_model"] = agent_model

    # --- verification ---
    verification = ModuleType("sdk.nexent.core.agents.verification")
    for name in ["VerificationController", "VerificationResult",
                 "render_guardrail_refusal", "render_tool_input_refusal"]:
        setattr(verification, name, MagicMock(name=f"verification.{name}"))
    mocks["sdk.nexent.core.agents.verification"] = verification

    # --- context_runtime ---
    ctx_runtime = ModuleType("sdk.nexent.core.context_runtime")
    ctx_contracts = ModuleType("sdk.nexent.core.context_runtime.contracts")
    setattr(ctx_contracts, "ContextRuntime", MagicMock())
    setattr(ctx_contracts, "UnconfiguredContextRuntime", MagicMock())
    setattr(ctx_runtime, "context_runtime", ctx_contracts)
    mocks["sdk.nexent.core.context_runtime"] = ctx_runtime
    mocks["sdk.nexent.core.context_runtime.contracts"] = ctx_contracts

    # --- monitor ---
    monitor = ModuleType("sdk.nexent.monitor")
    monitor.get_monitoring_manager = MagicMock()
    mocks["sdk.nexent.monitor"] = monitor

    # --- plan_repo ---
    plan_repo = ModuleType("sdk.nexent.core.agents.plan_repo")
    plan_repo.PlanRepo = MagicMock()
    mocks["sdk.nexent.core.agents.plan_repo"] = plan_repo

    return mocks


# Register mocks
_mocks = _create_minimal_mocks()
for _name, _mod in _mocks.items():
    sys.modules.setdefault(_name, _mod)

# Ensure package hierarchy exists
for _pkg in ["sdk", "sdk.nexent", "sdk.nexent.core", "sdk.nexent.core.agents",
             "sdk.nexent.core.utils", "sdk.nexent.core.context_runtime"]:
    if _pkg not in sys.modules:
        _m = ModuleType(_pkg)
        _m.__path__ = []
        sys.modules[_pkg] = _m


# ---------------------------------------------------------------------------
# Load core_agent module
# ---------------------------------------------------------------------------

def _load_module():
    project_root = os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
    core_agent_path = os.path.join(project_root, "sdk", "nexent", "core", "agents", "core_agent.py")

    spec = importlib.util.spec_from_file_location("sdk.nexent.core.agents.core_agent", core_agent_path)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "sdk.nexent.core.agents"
    sys.modules["sdk.nexent.core.agents.core_agent"] = module
    spec.loader.exec_module(module)
    return module


_module = _load_module()
_find_tool_call_calls = _module._find_tool_call_calls
parse_code_blobs = _module.parse_code_blobs


# ---------------------------------------------------------------------------
# Tests for _find_tool_call_calls
# ---------------------------------------------------------------------------

class TestFindToolCallCalls:
    """Tests for _find_tool_call_calls function."""

    def test_simple_params(self):
        """Tool call with simple string parameters."""
        text = 'output_card(card_type="info", title="Hello", message="World")'
        results = _find_tool_call_calls(text)
        assert len(results) == 1
        assert results[0] == 'output_card(card_type="info", title="Hello", message="World")'

    def test_nested_json_dict(self):
        """Tool call with nested JSON/dict parameters containing brackets."""
        text = '''output_card(
            card_type="chart",
            config={"data": [1, 2, 3], "labels": ["a", "b"]}
        )'''
        results = _find_tool_call_calls(text)
        assert len(results) == 1
        assert "output_card(" in results[0]
        assert '"data": [1, 2, 3]' in results[0]
        assert '"labels": ["a", "b"]' in results[0]

    def test_brackets_in_string(self):
        """Tool call where string values contain parentheses."""
        text = 'output_card(title="Hello (World)", message="See (this)")'
        results = _find_tool_call_calls(text)
        assert len(results) == 1
        assert "Hello (World)" in results[0]
        assert "See (this)" in results[0]

    def test_complex_nested_structure(self):
        """Tool call with deeply nested dicts and lists."""
        text = '''final_answer(result={
            "items": [{"name": "test", "value": (1+2)}],
            "meta": {"count": 3, "tags": ["a", "b"]}
        })'''
        results = _find_tool_call_calls(text)
        assert len(results) == 1
        assert "final_answer(" in results[0]
        assert '"items"' in results[0]
        assert '(1+2)' in results[0]
        assert '"tags": ["a", "b"]' in results[0]

    def test_no_tool_calls_returns_empty(self):
        """Text without any tool calls should return empty list."""
        text = "This is just a normal text without any tool calls."
        results = _find_tool_call_calls(text)
        assert results == []

    def test_mixed_text_with_tool_call(self):
        """Tool call surrounded by other text."""
        text = 'Some prefix text\noutput_card(card_type="info", title="T", message="M")\nsome suffix'
        results = _find_tool_call_calls(text)
        assert len(results) == 1
        assert 'output_card(card_type="info", title="T", message="M")' in results[0]

    def test_multiple_tool_calls(self):
        """Multiple tool calls in one text."""
        text = 'output_card(card_type="info", title="A", message="B")\nfinal_answer(result="done")'
        results = _find_tool_call_calls(text)
        assert len(results) == 2

    def test_escaped_string_in_params(self):
        """Tool call with escaped quotes inside string parameters."""
        text = 'output_card(title="He said \\"hello\\"", message="ok")'
        results = _find_tool_call_calls(text)
        assert len(results) == 1

    def test_single_quoted_strings(self):
        """Tool call with single-quoted strings."""
        text = "output_card(title='Hello', message='World')"
        results = _find_tool_call_calls(text)
        assert len(results) == 1
        assert "Hello" in results[0]

    def test_create_scheduled_task(self):
        """Tool call with create_scheduled_task_proposal."""
        text = 'create_scheduled_task_proposal(name="daily", schedule={"every": 1, "unit": "day"})'
        results = _find_tool_call_calls(text)
        assert len(results) == 1
        assert 'create_scheduled_task_proposal(' in results[0]
        assert '"every": 1' in results[0]


# ---------------------------------------------------------------------------
# Tests for parse_code_blobs (bare tool call path)
# ---------------------------------------------------------------------------

class TestParseCodeBlobsBareToolCalls:
    """Tests for parse_code_blobs via the bare tool call fallback path."""

    def test_simple_params_extraction(self):
        """Bare tool call with simple parameters."""
        text = 'output_card(card_type="info", title="Hello", message="World")'
        result = parse_code_blobs(text)
        assert 'output_card(card_type="info", title="Hello", message="World")' in result

    def test_nested_json_params(self):
        """Bare tool call with nested JSON parameters (core scenario)."""
        text = '''output_card(
            card_type="chart",
            config={"data": [1, 2, 3], "labels": ["a", "b"]}
        )'''
        result = parse_code_blobs(text)
        assert "output_card(" in result
        assert '"data": [1, 2, 3]' in result
        assert '"labels": ["a", "b"]' in result

    def test_brackets_in_string_handling(self):
        """Bare tool call where string values contain parentheses."""
        text = 'output_card(title="Hello (World)", message="See (this)")'
        result = parse_code_blobs(text)
        assert "Hello (World)" in result
        assert "See (this)" in result

    def test_complex_nested_bare(self):
        """Bare tool call with deeply nested structure."""
        text = '''final_answer(result={
            "items": [{"name": "test", "value": (1+2)}],
            "meta": {"count": 3}
        })'''
        result = parse_code_blobs(text)
        assert "final_answer(" in result
        assert '"items"' in result
        assert '(1+2)' in result

    def test_no_code_raises_value_error(self):
        """Text without any tool calls or code blocks should raise ValueError."""
        text = "Just some random text without any structure."
        with pytest.raises(ValueError):
            parse_code_blobs(text)

    def test_multiple_bare_tool_calls(self):
        """Multiple bare tool calls separated by whitespace."""
        text = 'output_card(card_type="info", title="A", message="B")\nfinal_answer(result="done")'
        result = parse_code_blobs(text)
        assert 'output_card(card_type="info", title="A", message="B")' in result
        assert 'final_answer(result="done")' in result

    def test_bare_with_escaped_quotes(self):
        """Bare tool call with escaped quotes in parameters."""
        text = 'output_card(title="He said \\"hello\\"", message="ok")'
        result = parse_code_blobs(text)
        assert "He said" in result

    def test_code_block_takes_priority(self):
        """When both <code> block and bare tool call exist, <code> wins."""
        text = '<code>output_card(card_type="info", title="A", message="B")</code>\nfinal_answer(x=1)'
        result = parse_code_blobs(text)
        assert "output_card(" in result
        assert "final_answer(x=1)" not in result

    def test_run_block_takes_priority_over_bare(self):
        """When <RUN> block exists, bare tool calls are not used."""
        text = '```<RUN>\noutput_card(card_type="info", title="A", message="B")\n```\nfinal_answer(x=1)'
        result = parse_code_blobs(text)
        assert "output_card(" in result
        assert "final_answer(x=1)" not in result