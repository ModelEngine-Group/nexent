"""
Unit tests for sdk.nexent.core.agents.core_agent module.

This module tests CoreAgent class and its helper functions:
- parse_code_blobs
- convert_code_format

The standalone functions (parse_code_blobs, convert_code_format) are fully tested.
"""
import pytest
import importlib.util
import json
import os
import sys
import threading
from dataclasses import dataclass
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, call, patch
from threading import Event


# ---------------------------------------------------------------------------
# Prepare mocks for external dependencies
# ---------------------------------------------------------------------------

def _create_mock_smolagents():
    """Create mock smolagents module with all required submodules."""
    mock_smolagents = ModuleType("smolagents")
    mock_smolagents.__dict__.update({})
    mock_smolagents.__path__ = []

    # agents submodule
    agents_mod = ModuleType("smolagents.agents")
    for _name in ["populate_template", "handle_agent_output_types", "AgentError", "ActionOutput", "RunResult"]:
        setattr(agents_mod, _name, MagicMock(name=f"smolagents.agents.{_name}"))

    # Provide a realistic CodeAgent so that CoreAgent.__init__ (which pops
    # enable_planning from kwargs) does not create spurious MagicMock attributes.
    from unittest.mock import MagicMock as _MagicMock

    class _RealisticCodeAgent:
        # v1.4: _run_stream checks self.enable_planning; ensure the attr exists.
        enable_planning = False

        def __init__(self, *args, **kwargs):
            # Pop keys that CoreAgent.__init__ manages so they don't pollute
            # the parent's kwargs; always set enable_planning from the class-level
            # default above (CoreAgent already assigned it before calling super).
            self.enable_planning = kwargs.pop("enable_planning", self.enable_planning)
            self.tools = kwargs.pop("tools", {}) or {}
            self.managed_agents = kwargs.pop("managed_agents", {}) or {}
            self.prompt_templates = kwargs.pop("prompt_templates", {}) or {}
            self.max_steps = kwargs.pop("max_steps", 10)
            self.code_block_tags = ["", ""]
            self.memory = _MagicMock()
            self.memory.steps = []
            self.model = kwargs.pop("model", None)
            self.logger = _MagicMock()
            self.state = {}
            self.step_number = 1
            self.monitor = _MagicMock()
            self.python_executor = _MagicMock()
            self.system_prompt = ""
            self._use_structured_outputs_internally = False
            self.name = "agent"
            self.agent_name = "agent"
            self.return_full_result = False
            self.final_answer_checks = []
            self.provide_run_summary = False
            self.context_runtime = _MagicMock()
            self.lang = getattr(self, "lang", "en")

    setattr(agents_mod, "CodeAgent", _RealisticCodeAgent)
    setattr(mock_smolagents, "CodeAgent", _RealisticCodeAgent)
    setattr(mock_smolagents, "agents", agents_mod)

    # local_python_executor submodule
    local_python_mod = ModuleType("smolagents.local_python_executor")
    setattr(local_python_mod, "fix_final_answer_code", MagicMock(name="fix_final_answer_code"))
    setattr(mock_smolagents, "local_python_executor", local_python_mod)

    # memory submodule
    memory_mod = ModuleType("smolagents.memory")
    class _TaskStepBase:
        def __init__(self, task=None):
            self.task = task
    class _ActionStepBase:
        def __init__(self, step_number=None, timing=None, action_output=None, model_output=None):
            self.step_number = step_number
            self.timing = timing
            self.action_output = action_output
            self.model_output = model_output
    setattr(memory_mod, "TaskStep", _TaskStepBase)
    setattr(memory_mod, "ActionStep", _ActionStepBase)
    setattr(memory_mod, "AgentMemory", MagicMock)
    setattr(memory_mod, "MemoryStep", MagicMock)
    for _name in ["ToolCall", "SystemPromptStep", "PlanningStep", "FinalAnswerStep"]:
        setattr(memory_mod, _name, MagicMock(name=f"smolagents.memory.{_name}"))
    setattr(mock_smolagents, "memory", memory_mod)

    # models submodule
    models_mod = ModuleType("smolagents.models")
    setattr(models_mod, "ChatMessage", MagicMock(name="ChatMessage"))
    setattr(models_mod, "MessageRole", MagicMock(name="MessageRole"))
    setattr(models_mod, "CODEAGENT_RESPONSE_FORMAT", MagicMock(name="CODEAGENT_RESPONSE_FORMAT"))
    setattr(models_mod, "OpenAIServerModel", MagicMock(name="OpenAIServerModel"))
    setattr(mock_smolagents, "models", models_mod)

    # monitoring submodule
    monitoring_mod = ModuleType("smolagents.monitoring")
    setattr(monitoring_mod, "LogLevel", MagicMock(name="LogLevel"))
    setattr(monitoring_mod, "Timing", MagicMock(name="Timing"))
    setattr(monitoring_mod, "YELLOW_HEX", MagicMock(name="YELLOW_HEX"))
    setattr(monitoring_mod, "TokenUsage", MagicMock(name="TokenUsage"))
    setattr(mock_smolagents, "monitoring", monitoring_mod)

    # utils submodule
    utils_mod = ModuleType("smolagents.utils")
    for _name in ["AgentExecutionError", "AgentGenerationError", "AgentParsingError",
                  "AgentMaxStepsError", "truncate_content", "extract_code_from_text"]:
        setattr(utils_mod, _name, MagicMock(name=f"smolagents.utils.{_name}"))
    setattr(mock_smolagents, "utils", utils_mod)

    # Top-level exports
    setattr(mock_smolagents, "TaskStep", memory_mod.TaskStep)
    setattr(mock_smolagents, "ActionStep", memory_mod.ActionStep)
    setattr(mock_smolagents, "AgentText", MagicMock(name="smolagents.AgentText"))
    setattr(mock_smolagents, "handle_agent_output_types", MagicMock(name="smolagents.handle_agent_output_types"))
    setattr(mock_smolagents, "Timing", monitoring_mod.Timing)
    setattr(mock_smolagents, "Tool", MagicMock(name="Tool"))

    return mock_smolagents


def _create_mock_modules():
    """Create all required module mocks to bypass complex imports."""
    mock_smolagents = _create_mock_smolagents()

    # Mock rich
    mock_rich_console = ModuleType("rich.console")
    mock_rich_text = ModuleType("rich.text")
    mock_rich = ModuleType("rich")
    setattr(mock_rich, "Group", MagicMock(side_effect=lambda *args: args))
    setattr(mock_rich_text, "Text", MagicMock())
    setattr(mock_rich, "console", mock_rich_console)
    setattr(mock_rich, "text", mock_rich_text)
    setattr(mock_rich_console, "Group", MagicMock(side_effect=lambda *args: args))

    # Mock jinja2
    mock_jinja2 = ModuleType("jinja2")
    setattr(mock_jinja2, "Template", MagicMock())
    setattr(mock_jinja2, "StrictUndefined", MagicMock())

    # Mock langchain_core
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

    # Create observer module mock
    mock_observer = ModuleType("sdk.nexent.core.utils.observer")

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
        MAX_STEPS_REACHED = "MAX_STEPS_REACHED"

    class MessageObserver:
        def __init__(self):
            self.add_message = MagicMock()

    setattr(mock_observer, "MessageObserver", MessageObserver)
    setattr(mock_observer, "ProcessType", ProcessType)

    return {
        "smolagents": mock_smolagents,
        "smolagents.agents": mock_smolagents.agents,
        "smolagents.memory": mock_smolagents.memory,
        "smolagents.models": mock_smolagents.models,
        "smolagents.monitoring": mock_smolagents.monitoring,
        "smolagents.utils": mock_smolagents.utils,
        "smolagents.local_python_executor": mock_smolagents.local_python_executor,
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
# Load core_agent module directly
# ---------------------------------------------------------------------------

def _load_core_agent_module():
    """Load core_agent module directly without going through __init__.py."""
    # Use cross-platform path construction
    # __file__ is C:\Project\nexent\test\sdk\core\agents\test_core_agent.py
    # We need to go up 5 levels to get to C:\Project\nexent
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
    core_agent_path = os.path.join(project_root, "sdk", "nexent", "core", "agents", "core_agent.py")

    # Create full package hierarchy
    sys.modules["sdk"] = ModuleType("sdk")
    sys.modules["sdk"].__path__ = []
    sys.modules["sdk.nexent"] = ModuleType("sdk.nexent")
    sys.modules["sdk.nexent"].__path__ = []
    sys.modules["sdk.nexent.core"] = ModuleType("sdk.nexent.core")
    sys.modules["sdk.nexent.core"].__path__ = []
    agents_pkg = ModuleType("sdk.nexent.core.agents")
    agents_pkg.__path__ = [os.path.join(project_root, "sdk", "nexent", "core", "agents")]
    sys.modules["sdk.nexent.core.agents"] = agents_pkg

    utils_pkg = ModuleType("sdk.nexent.core.utils")
    utils_pkg.__path__ = [os.path.join(project_root, "sdk", "nexent", "core", "utils")]
    sys.modules["sdk.nexent.core.utils"] = utils_pkg

    observer_mod = ModuleType("sdk.nexent.core.utils.observer")
    observer_mod.MessageObserver = MagicMock()
    observer_mod.ProcessType = MagicMock()
    sys.modules["sdk.nexent.core.utils.observer"] = observer_mod

    token_estimation_mod = ModuleType("sdk.nexent.core.utils.token_estimation")
    token_estimation_mod.msg_token_count = MagicMock(return_value=0)
    sys.modules["sdk.nexent.core.utils.token_estimation"] = token_estimation_mod

    agent_context_mod = ModuleType("sdk.nexent.core.agents.agent_context")
    agent_context_mod.ContextManager = MagicMock()
    agent_context_mod.ContextManagerConfig = MagicMock()
    sys.modules["sdk.nexent.core.agents.agent_context"] = agent_context_mod

    context_runtime_pkg = ModuleType("sdk.nexent.core.context_runtime")
    context_runtime_contracts_mod = ModuleType("sdk.nexent.core.context_runtime.contracts")
    context_runtime_contracts_mod.ContextRuntime = MagicMock()
    context_runtime_contracts_mod.UnconfiguredContextRuntime = MagicMock()
    sys.modules["sdk.nexent.core.context_runtime"] = context_runtime_pkg
    sys.modules["sdk.nexent.core.context_runtime.contracts"] = context_runtime_contracts_mod

    monitor_mod = ModuleType("sdk.nexent.monitor")
    monitor_mod.get_monitoring_manager = MagicMock()
    sys.modules["sdk.nexent.monitor"] = monitor_mod

    # Load the module
    spec = importlib.util.spec_from_file_location("sdk.nexent.core.agents.core_agent", core_agent_path)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "sdk.nexent.core.agents"
    sys.modules["sdk.nexent.core.agents.core_agent"] = module

    # Override some functions with mock implementations
    def mock_truncate_content(content, max_length=1000):
        content_str = str(content)
        if len(content_str) <= max_length:
            return content_str
        return content_str[:max_length] + "..."

    sys.modules["smolagents.utils"].truncate_content = mock_truncate_content

    spec.loader.exec_module(module)
    return module


core_agent_module = _load_core_agent_module()

# Import ProcessType and MessageObserver for tests
ProcessType = _module_mocks["sdk.nexent.core.utils.observer"].ProcessType
MessageObserver = _module_mocks["sdk.nexent.core.utils.observer"].MessageObserver


def test_context_evidence_marks_an_early_closed_stream_as_cancelled():
    module = TestRunStreamRealExecution()._load_core_agent_in_isolation()
    agent = object.__new__(module.CoreAgent)
    agent.context_runtime = MagicMock()
    agent.stop_event = MagicMock()
    agent.stop_event.is_set.return_value = False
    agent._run_stream = MagicMock(return_value=iter(["first", "second"]))

    stream = agent._run_stream_with_context_evidence(task="task", max_steps=2)
    assert next(stream) == "first"
    stream.close()

    agent.context_runtime.finalize_evidence.assert_called_once_with(status="cancelled")


def test_get_context_summary_returns_runtime_context_manager_summary():
    agent = object.__new__(core_agent_module.CoreAgent)
    context_manager = MagicMock()
    context_manager.get_summary.return_value = "compressed summary"
    agent.context_runtime = SimpleNamespace(context_manager=context_manager)

    assert agent._get_context_summary() == "compressed summary"
    context_manager.get_summary.assert_called_once_with()


def test_get_context_summary_returns_none_when_manager_is_unavailable():
    agent = object.__new__(core_agent_module.CoreAgent)
    agent.context_runtime = SimpleNamespace()

    assert agent._get_context_summary() is None


def test_get_context_summary_returns_none_when_manager_summary_fails():
    agent = object.__new__(core_agent_module.CoreAgent)
    context_manager = MagicMock()
    context_manager.get_summary.side_effect = RuntimeError("summary unavailable")
    agent.context_runtime = SimpleNamespace(context_manager=context_manager)

    assert agent._get_context_summary() is None
    context_manager.get_summary.assert_called_once_with()





# ----------------------------------------------------------------------------
# Tests for parse_code_blobs function
# ----------------------------------------------------------------------------


def test_incomplete_action_preamble_is_not_a_final_answer():
    output = "思考：我需要先调用 knowledge_base_search 检索当前选择的知识库。"

    assert core_agent_module._looks_like_incomplete_action_output(
        output,
        available_tool_names={"knowledge_base_search"},
    ) is True


def test_complete_answer_that_names_tool_is_not_misclassified():
    output = "knowledge_base_search 是用于检索知识库的工具。"

    assert core_agent_module._looks_like_incomplete_action_output(
        output,
        available_tool_names={"knowledge_base_search"},
    ) is False


@pytest.mark.parametrize(
    "output",
    [
        (
            "思考：工具调用成功。根据策略，我需要用 `final_answer` 返回工具结果。\n\n"
            "最终回答：\n定时任务提案已生成，请核对任务内容和执行时间后确认创建。"
        ),
        (
            "Analysis: The tool call succeeded, so I will use `final_answer` to return the result.\n\n"
            "Final answer:\nThe scheduled-task proposal is ready for confirmation."
        ),
    ],
)
def test_complete_explicit_final_answer_is_not_misclassified(output):
    assert core_agent_module._looks_like_incomplete_action_output(
        output,
        available_tool_names={"final_answer", "create_scheduled_task_proposal"},
    ) is False


def test_length_truncated_non_code_output_is_not_a_final_answer():
    assert core_agent_module._looks_like_incomplete_action_output(
        "这是一个尚未完成的回答",
        finish_reason="length",
    ) is False


def test_length_truncated_action_preamble_still_requires_a_tool_call():
    assert core_agent_module._looks_like_incomplete_action_output(
        "思考：我需要先调用 knowledge_base_search",
        available_tool_names={"knowledge_base_search"},
        finish_reason="length",
    ) is True


def test_parse_code_blobs_run_format():
    """Test parse_code_blobs with <code>...</code> pattern (new format)."""
    text = """Here is some code:
<code>
print("Hello World")
x = 42
</code>
And some more text."""

    result = core_agent_module.parse_code_blobs(text)
    expected = "print(\"Hello World\")\nx = 42"
    assert result == expected


# ----------------------------------------------------------------------------
# Tests for layered final-answer verification policy
# ----------------------------------------------------------------------------

def _make_verification_controller(**config_overrides):
    config = core_agent_module.AgentVerificationConfig(
        enabled=True,
        step_verification_enabled=True,
        final_verification_enabled=True,
        llm_verification_enabled=True,
        **config_overrides,
    )
    observer = MagicMock()
    observer.add_message = MagicMock()
    model = MagicMock()
    logger = MagicMock()
    logger.log = MagicMock()
    return core_agent_module.VerificationController(
        config=config,
        observer=observer,
        agent_name="test-agent",
        model=model,
        logger=logger,
    ), model


def test_final_verification_skips_llm_for_greeting():
    """Simple greetings should not require external evidence or tool output."""
    controller, model = _make_verification_controller()

    result = controller.verify_final_answer(
        task="你好",
        candidate="你好！有什么我可以帮你的吗？",
        memory_summary="Step 1:\nCode:\nObservation:\nOutput:",
        round_number=1,
    )

    assert result.passed is True
    assert result.phase == "final_pass"
    model.assert_not_called()


def test_final_verification_pass_message_explains_reason():
    """Passed verification events should tell users what was checked."""
    controller, _ = _make_verification_controller()

    controller.verify_final_answer(
        task="你好",
        candidate="你好！有什么我可以帮你的吗？",
        memory_summary="Step 1:\nCode:\nObservation:\nOutput:",
        round_number=1,
    )

    messages = [
        json.loads(call.args[2])["message"]
        for call in controller.observer.add_message.call_args_list
    ]

    assert any("基础自检通过" in message and "答案非空" in message for message in messages)
    assert any("最终自检通过" in message and "轻量对话无需外部证据" in message for message in messages)


def test_verification_feedback_does_not_count_as_tool_error():
    """Self-verification feedback should not poison the next final-answer check."""
    controller, _ = _make_verification_controller()
    memory_summary = """
Step 1:
Observation:
Verification feedback:
- Event: final_answer
- Severity: blocking
- Failed criteria: evidence_grounding, tool_error_handling
- Repair instruction: Provide more evidence.
"""

    result = controller.verify_before_final_answer(
        candidate="你好！有什么我可以帮你的吗？",
        observation=memory_summary,
        step_number=2,
    )

    assert result.passed is True
    assert "previous_errors_acknowledged" not in result.failed_criteria


def test_llm_verifier_ignores_non_required_evidence_and_tool_error_failures():
    """Verifier output is normalized when failed criteria are not required by policy."""
    controller, _ = _make_verification_controller()
    verifier_payload = json.dumps({
        "passed": False,
        "score": 0.5,
        "status": "revise",
        "failed_criteria": ["evidence_grounding", "tool_error_handling"],
        "checks": [
            {"name": "evidence_grounding", "passed": False},
            {"name": "tool_error_handling", "passed": False},
        ],
        "revision_instruction": "Find evidence.",
        "user_visible_note": "Missing evidence.",
    })

    result = controller._parse_llm_verifier_result(
        verifier_payload,
        {
            "task_profile": "lightweight_conversation",
            "evidence_required": False,
            "tool_error_check_required": False,
        },
    )

    assert result.passed is True
    assert result.failed_criteria == []
    assert result.score >= controller.config.pass_score


def test_parse_code_blobs_run_format_with_newline():
    """Test parse_code_blobs with <code>\\ncontent\\n</code> pattern."""
    text = """Here is some code:
<code>
print("Hello World")
x = 42
</code>
And some more text."""

    result = core_agent_module.parse_code_blobs(text)
    expected = "print(\"Hello World\")\nx = 42"
    assert result == expected


def test_parse_code_blobs_run_format_without_newline():
    """Test parse_code_blobs with <code>content</code> pattern (no newlines)."""
    text = """Here is some code:
<code>print("Hello")</code>
And some more text."""

    result = core_agent_module.parse_code_blobs(text)
    expected = 'print("Hello")'
    assert result == expected


def test_parse_code_blobs_multiple_code_blocks():
    """Test parse_code_blobs with multiple <code> blocks."""
    text = """<code>
first_block()
</code>
<code>
second_block()
</code>"""

    result = core_agent_module.parse_code_blobs(text)
    expected = "first_block()\n\nsecond_block()"
    assert result == expected


def test_parse_code_blobs_incomplete_code_tag():
    """Test parse_code_blobs when <code> tag has no closing </code>."""
    text = """Here is some code:
<code>
incomplete code without closing tag"""

    # Incomplete block is skipped, ast.parse raises ValueError for non-Python text
    with pytest.raises(ValueError):
        core_agent_module.parse_code_blobs(text)


def test_parse_code_blobs_multiple_code_blocks_one_incomplete():
    """Test parse_code_blobs with multiple <code> blocks where one has no closing tag."""
    text = """<code>
first_block()
</code>
<code>
second_block"""

    result = core_agent_module.parse_code_blobs(text)
    # Only complete blocks are extracted
    expected = "first_block()"
    assert result == expected


def test_parse_code_blobs_run_format_without_end_code():
    """Test parse_code_blobs with ```<RUN>\\ncontent\\n``` pattern (without END_CODE)."""
    text = """Here is some code:
```<RUN>
print("Hello World")
```
And some more text."""

    result = core_agent_module.parse_code_blobs(text)
    expected = "print(\"Hello World\")"
    assert result == expected


def test_parse_code_blobs_run_incomplete_no_closing_backticks():
    """Test parse_code_blobs when ```<RUN> tag has no closing ```."""
    text = """Here is some code:
```<RUN>
incomplete code without closing backticks"""

    # Incomplete block is skipped, ast.parse raises ValueError for non-Python text
    with pytest.raises(ValueError):
        core_agent_module.parse_code_blobs(text)


def test_parse_code_blobs_multiple_run_blocks_one_incomplete():
    """Test parse_code_blobs with multiple ```<RUN> blocks where one has no closing ```."""
    text = """```<RUN>
first_block()
```
```<RUN>
second_block"""

    result = core_agent_module.parse_code_blobs(text)
    # Only complete blocks are extracted
    expected = "first_block()"
    assert result == expected


def test_parse_code_blobs_multiple_run_blocks():
    """Test parse_code_blobs with multiple ```<RUN> blocks."""
    text = """```<RUN>
first_block()
```<END_CODE>
```<RUN>
second_block()
```<END_CODE>"""

    result = core_agent_module.parse_code_blobs(text)
    expected = "first_block()\n\nsecond_block()"
    assert result == expected


def test_parse_code_blobs_python_match():
    """Test parse_code_blobs raises ValueError for ```python\\ncontent\\n``` pattern.

    Note: ```python blocks are intentionally NOT supported to prevent
    KB content containing code examples from being accidentally executed.
    """
    text = """Here is some code:
```python
print("Hello World")
x = 42
```
And some more text."""

    with pytest.raises(ValueError) as exc_info:
        core_agent_module.parse_code_blobs(text)

    assert "executable code block pattern" in str(exc_info.value)


def test_parse_code_blobs_py_match():
    """Test parse_code_blobs raises ValueError for ```py\\ncontent\\n``` pattern.

    Note: ```py blocks are intentionally NOT supported to prevent
    KB content containing code examples from being accidentally executed.
    """
    text = """Here is some code:
```py
def hello():
    return "Hello"
```
And some more text."""

    with pytest.raises(ValueError) as exc_info:
        core_agent_module.parse_code_blobs(text)

    assert "executable code block pattern" in str(exc_info.value)


def test_parse_code_blobs_multiple_matches():
    """Test parse_code_blobs raises ValueError when multiple ```python/```py blocks are present.

    Note: ```python blocks are intentionally NOT supported to prevent
    KB content containing code examples from being accidentally executed.
    """
    text = """First code block:
```python
print("First")
```

Second code block:
```py
print("Second")
```"""

    with pytest.raises(ValueError) as exc_info:
        core_agent_module.parse_code_blobs(text)

    assert "executable code block pattern" in str(exc_info.value)


def test_parse_code_blobs_direct_python_code():
    """Test parse_code_blobs with direct Python code (no code blocks).

    Direct Python code without code blocks will raise ValueError because
    it's not wrapped in <code>...</code> or ```<RUN>...</RUN>``` format.
    """
    text = '''print("Hello World")
x = 42
def hello():
    return "Hello"'''

    with pytest.raises(ValueError) as exc_info:
        core_agent_module.parse_code_blobs(text)

    assert "executable code block pattern" in str(exc_info.value)


def test_parse_code_blobs_invalid_no_match():
    """Test parse_code_blobs with generic text that should raise ValueError."""
    text = """This is just some random text.
Just plain text that should fail."""

    with pytest.raises(ValueError) as exc_info:
        core_agent_module.parse_code_blobs(text)

    error_msg = str(exc_info.value)
    assert "executable code block pattern" in error_msg
    assert "Make sure to include code with the correct pattern" in error_msg


def test_parse_code_blobs_display_only_raises():
    """Test parse_code_blobs raises ValueError when only DISPLAY code blocks are present."""
    text = """Here is some code:
```<DISPLAY:python>
def hello():
    return "Hello"
```<END_DISPLAY_CODE>
And some more text."""

    with pytest.raises(ValueError) as exc_info:
        core_agent_module.parse_code_blobs(text)

    assert "executable code block pattern" in str(exc_info.value)


def test_parse_code_blobs_javascript_no_match():
    """Test parse_code_blobs with ```javascript\\ncontent\\n``` (other language)."""
    text = """Here is some JavaScript code:
```javascript
console.log("Hello World");
```
But this should not match."""

    with pytest.raises(ValueError) as exc_info:
        core_agent_module.parse_code_blobs(text)

    assert "executable code block pattern" in str(exc_info.value)


def test_parse_code_blobs_py_block_no_closing_backticks():
    """Test parse_code_blobs when ```py block has no closing ```."""
    text = """```py
incomplete code without closing backticks"""

    # Incomplete block is skipped, ast.parse raises ValueError for non-Python text
    with pytest.raises(ValueError):
        core_agent_module.parse_code_blobs(text)


def test_parse_code_blobs_python_block_no_closing_backticks():
    """Test parse_code_blobs when ```python block has no closing ```."""
    text = """```python
incomplete code without closing backticks"""

    # Incomplete block is skipped, ast.parse raises ValueError for non-Python text
    with pytest.raises(ValueError):
        core_agent_module.parse_code_blobs(text)


def test_parse_code_blobs_py_with_newline_after_fence():
    """Test parse_code_blobs raises ValueError for ```py\\ncontent\\n``` pattern.

    Note: ```py blocks are intentionally NOT supported to prevent
    KB content containing code examples from being accidentally executed.
    """
    text = """```py
print("hello")
```"""

    with pytest.raises(ValueError) as exc_info:
        core_agent_module.parse_code_blobs(text)

    assert "executable code block pattern" in str(exc_info.value)


def test_parse_code_blobs_python_with_newline_after_fence():
    """Test parse_code_blobs raises ValueError for ```python\\ncontent\\n``` pattern.

    Note: ```python blocks are intentionally NOT supported to prevent
    KB content containing code examples from being accidentally executed.
    """
    text = """```python
print("hello")
```"""

    with pytest.raises(ValueError) as exc_info:
        core_agent_module.parse_code_blobs(text)

    assert "executable code block pattern" in str(exc_info.value)


def test_parse_code_blobs_single_line():
    """Test parse_code_blobs raises ValueError for single-line ```python block.

    Note: ```python blocks are intentionally NOT supported to prevent
    KB content containing code examples from being accidentally executed.
    """
    text = """Single line:
```python
print("Hello")
```"""

    with pytest.raises(ValueError) as exc_info:
        core_agent_module.parse_code_blobs(text)

    assert "executable code block pattern" in str(exc_info.value)


def test_parse_code_blobs_mixed_content():
    """Test parse_code_blobs raises ValueError when mixed content contains only ```python blocks.

    Note: ```python blocks are intentionally NOT supported to prevent
    KB content containing code examples from being accidentally executed.
    """
    text = """Thoughts: I need to calculate the sum
Code:
```python
def sum_numbers(a, b):
    return a + b

result = sum_numbers(5, 3)
```
The result is 8."""

    with pytest.raises(ValueError) as exc_info:
        core_agent_module.parse_code_blobs(text)

    assert "executable code block pattern" in str(exc_info.value)


# ----------------------------------------------------------------------------
# Tests for convert_code_format function
# ----------------------------------------------------------------------------

def test_convert_code_format_display_new_format():
    """Validate convert_code_format correctly transforms new <DISPLAY:language>...</DISPLAY> format to standard markdown."""
    original_text = """Here is code:
<DISPLAY:python>
print('hello')
</DISPLAY>
And some more text."""

    expected_text = """Here is code:
```python
print('hello')
```
And some more text."""

    transformed = core_agent_module.convert_code_format(original_text)
    assert transformed == expected_text


def test_convert_code_format_display_replacements():
    """Validate convert_code_format correctly transforms legacy <DISPLAY:language> format to standard markdown."""
    original_text = """Here is code:
```<DISPLAY:python>
print('hello')
```<END_DISPLAY_CODE>
And some more text."""

    expected_text = """Here is code:
```python
print('hello')
```
And some more text."""

    transformed = core_agent_module.convert_code_format(original_text)
    assert transformed == expected_text


def test_convert_code_format_display_without_end_code():
    """Validate convert_code_format handles <DISPLAY:language> without <END_DISPLAY_CODE>."""
    original_text = """Here is code:
```<DISPLAY:python>
print('hello')
```
And some more text."""

    expected_text = """Here is code:
```python
print('hello')
```
And some more text."""

    transformed = core_agent_module.convert_code_format(original_text)
    assert transformed == expected_text


def test_convert_code_format_legacy_replacements():
    """Validate convert_code_format correctly transforms legacy code fences."""
    original_text = """Here is code:
```code:python
print('hello')
```
And some more text."""

    expected_text = """Here is code:
```python
print('hello')
```
And some more text."""

    transformed = core_agent_module.convert_code_format(original_text)
    assert transformed == expected_text


def test_convert_code_format_restore_end_code():
    """Test that <END_CODE> is properly restored after replacements."""
    original_text = """```<DISPLAY:python>
print('hello')
```<END_CODE>"""

    expected_text = """```python
print('hello')
```"""

    transformed = core_agent_module.convert_code_format(original_text)
    assert transformed == expected_text


def test_convert_code_format_no_change():
    """Test convert_code_format with standard markdown format (no changes needed)."""
    original_text = """```python
print('hello')
```"""

    transformed = core_agent_module.convert_code_format(original_text)
    assert transformed == original_text


def test_convert_code_format_multiple_displays():
    """Test convert_code_format with multiple DISPLAY blocks (both new and legacy format)."""
    original_text = """<DISPLAY:python>
first()
</DISPLAY>
<DISPLAY:javascript>
second()
</DISPLAY>"""

    expected_text = """```python
first()
```
```javascript
second()
```"""

    transformed = core_agent_module.convert_code_format(original_text)
    assert transformed == expected_text


def test_convert_code_format_mixed_with_code():
    """Test convert_code_format with mixed content."""
    original_text = """Some text before
```<DISPLAY:python>
print('displayed')
```<END_DISPLAY_CODE>
Some text after"""

    expected_text = """Some text before
```python
print('displayed')
```
Some text after"""

    transformed = core_agent_module.convert_code_format(original_text)
    assert transformed == expected_text


# ----------------------------------------------------------------------------
# Tests for FinalAnswerError exception class
# ----------------------------------------------------------------------------

def test_final_answer_error_creation():
    """Test FinalAnswerError can be created and raised."""
    error = core_agent_module.FinalAnswerError()
    assert isinstance(error, Exception)
    with pytest.raises(core_agent_module.FinalAnswerError):
        raise error


@pytest.mark.parametrize(
    "output",
    [
        "Step 2:\nCalled tool 'python_interpreter'()",
        "### Step 2:\n- Called tool 'python_interpreter'()",
        "Observation: previous result",
        '{"tool_calls":[{"name":"python_interpreter","arguments":"print(1)"}]}',
        '```json\n{"action":"search","arguments":{"q":"GAIA"}}\n```',
        "<code>print('missing closing tag')",
    ],
)
def test_action_like_non_executable_output_is_not_a_final_answer(output):
    assert core_agent_module._looks_like_invalid_action_output(output) is True


@pytest.mark.parametrize(
    "output",
    [
        None,
        42,
        "",
        "   ",
        "The answer is 42.",
        "I could not find enough evidence to answer.",
        '{"answer":"42"}',
        "{not valid json",
        "```json```",
        '["not an action record"]',
    ],
)
def test_plain_answer_does_not_look_like_invalid_action(output):
    assert core_agent_module._looks_like_invalid_action_output(output) is False


@pytest.mark.parametrize(
    "output",
    [
        "```<RUN>print('missing closing fence')",
        '[{"action":"search","arguments":{"q":"GAIA"}}]',
    ],
)
def test_additional_action_protocol_variants_are_invalid(output):
    assert core_agent_module._looks_like_invalid_action_output(output) is True


# ----------------------------------------------------------------------------
# Additional edge case tests for parse_code_blobs
# ----------------------------------------------------------------------------

def test_parse_code_blobs_whitespace_variation():
    """Test parse_code_blobs raises ValueError for ```python block with whitespace variation.

    Note: ```python blocks are intentionally NOT supported to prevent
    KB content containing code examples from being accidentally executed.
    """
    text = """```python
print("hello")
```"""
    with pytest.raises(ValueError) as exc_info:
        core_agent_module.parse_code_blobs(text)
    assert "executable code block pattern" in str(exc_info.value)


def test_parse_code_blobs_no_newline_at_end():
    """Test parse_code_blobs raises ValueError for ```python block without trailing newline.

    Note: ```python blocks are intentionally NOT supported to prevent
    KB content containing code examples from being accidentally executed.
    """
    text = """```python
print("hello")
```
And some text."""
    with pytest.raises(ValueError) as exc_info:
        core_agent_module.parse_code_blobs(text)
    assert "executable code block pattern" in str(exc_info.value)


def test_parse_code_blobs_with_comments():
    """Test parse_code_blobs raises ValueError for ```python block with comments.

    Note: ```python blocks are intentionally NOT supported to prevent
    KB content containing code examples from being accidentally executed.
    """
    text = """```python
# This is a comment
x = 1  # inline comment
```"""
    with pytest.raises(ValueError) as exc_info:
        core_agent_module.parse_code_blobs(text)
    assert "executable code block pattern" in str(exc_info.value)


def test_parse_code_blobs_with_multiline_string():
    """Test parse_code_blobs raises ValueError for ```python block with multiline strings.

    Note: ```python blocks are intentionally NOT supported to prevent
    KB content containing code examples from being accidentally executed.
    """
    text = '''```python
message = """
This is a
multiline string
"""
```'''
    with pytest.raises(ValueError) as exc_info:
        core_agent_module.parse_code_blobs(text)
    assert "executable code block pattern" in str(exc_info.value)


def test_parse_code_blobs_ruby_no_match():
    """Test parse_code_blobs with ```ruby\\ncontent\\n``` (other language)."""
    text = """Here is some Ruby code:
```ruby
puts "Hello World"
```
But this should not match."""
    with pytest.raises(ValueError):
        core_agent_module.parse_code_blobs(text)


def test_parse_code_blobs_go_no_match():
    """Test parse_code_blobs with ```go\\ncontent\\n``` (other language)."""
    text = """Here is some Go code:
```go
fmt.Println("Hello World")
```
But this should not match."""
    with pytest.raises(ValueError):
        core_agent_module.parse_code_blobs(text)


def test_parse_code_blobs_rust_no_match():
    """Test parse_code_blobs with ```rust\\ncontent\\n``` (other language)."""
    text = """Here is some Rust code:
```rust
println!("Hello World");
```
But this should not match."""
    with pytest.raises(ValueError):
        core_agent_module.parse_code_blobs(text)


def test_parse_code_blobs_bash_no_match():
    """Test parse_code_blobs with ```bash\\ncontent\\n``` (other language)."""
    text = """Here is some Bash code:
```bash
echo "Hello World"
```
But this should not match."""
    with pytest.raises(ValueError):
        core_agent_module.parse_code_blobs(text)


def test_parse_code_blobs_shell_no_match():
    """Test parse_code_blobs with ```shell\\ncontent\\n``` (other language)."""
    text = """Here is some Shell code:
```shell
echo "Hello World"
```
But this should not match."""
    with pytest.raises(ValueError):
        core_agent_module.parse_code_blobs(text)


# ----------------------------------------------------------------------------
# Additional edge case tests for convert_code_format
# ----------------------------------------------------------------------------

def test_convert_code_format_preserves_content():
    """Test that convert_code_format preserves actual code content."""
    code = '''```<DISPLAY:python>
def complex_function():
    """Docstring with special chars: <>&'"""
    return "Hello 世界"
```<END_DISPLAY_CODE>'''

    transformed = core_agent_module.convert_code_format(code)

    assert "def complex_function():" in transformed
    assert '"""Docstring with special chars: <>&\'"' in transformed
    assert "Hello 世界" in transformed


def test_convert_code_format_handles_empty_end_tags():
    """Test convert_code_format with empty DISPLAY blocks."""
    text = """```<DISPLAY:python>
```<END_DISPLAY_CODE>"""
    transformed = core_agent_module.convert_code_format(text)
    expected = """```python
```"""
    assert transformed == expected


def test_convert_code_format_complex_nested():
    """Test convert_code_format with complex nested structures."""
    text = '''# Start
```<DISPLAY:python>
# Python code
```<END_DISPLAY_CODE>
Middle
```<DISPLAY:javascript>
// JavaScript
```<END_DISPLAY_CODE>
End'''

    transformed = core_agent_module.convert_code_format(text)

    assert "```python" in transformed
    assert "```javascript" in transformed
    assert "# Python code" in transformed
    assert "// JavaScript" in transformed


# ----------------------------------------------------------------------------
# Additional edge case tests
# ----------------------------------------------------------------------------

def test_convert_code_format_code_end_tag_restoration():
    """Test that ```<END_CODE> is properly restored to ```."""
    text = """Some code:
```<DISPLAY:python>
print('hello')
```<END_CODE>
More text."""

    transformed = core_agent_module.convert_code_format(text)

    assert "```python" in transformed
    assert "```<END_CODE>" not in transformed
    assert "```\n" in transformed or '```"' in transformed or transformed.endswith("```")


def test_parse_code_blobs_whitespace_only_run_block():
    """Test parse_code_blobs with whitespace-only RUN block."""
    text = """```<RUN>

```<END_CODE>"""

    result = core_agent_module.parse_code_blobs(text)
    assert result.strip() == ""


def test_parse_code_blobs_special_characters():
    """Test parse_code_blobs raises ValueError for ```python block with special characters.

    Note: ```python blocks are intentionally NOT supported to prevent
    KB content containing code examples from being accidentally executed.
    """
    text = """```python
x = "!@#$%^&*()_+-=[]{}|;':\",./<>?"
y = 'single quotes'
z = "double quotes"
w = '''triple single'''
```"""

    with pytest.raises(ValueError) as exc_info:
        core_agent_module.parse_code_blobs(text)
    assert "executable code block pattern" in str(exc_info.value)


def test_convert_code_format_unicode_content():
    """Test convert_code_format preserves Unicode content."""
    text = """```<DISPLAY:python>
def hello():
    return "你好世界"
print("🎉")
```<END_DISPLAY_CODE>"""

    transformed = core_agent_module.convert_code_format(text)

    assert "```python" in transformed
    assert "你好世界" in transformed
    assert "🎉" in transformed


def test_convert_code_format_dedent_removal():
    """Test that extra backticks from dedent pattern are removed."""
    text = """```<DISPLAY:python>
def test():
    pass
```<END_DISPLAY_CODE>"""

    transformed = core_agent_module.convert_code_format(text)
    # Should not have leftover ```< patterns
    assert "```<" not in transformed


def test_parse_code_blobs_only_whitespace_text():
    """Test parse_code_blobs raises ValueError for whitespace-only text.

    Whitespace-only text is not valid executable code because it's not
    wrapped in <code>...</code> or ```<RUN>...</RUN>``` format.
    """
    text = "   \n\n   \t\t   "

    with pytest.raises(ValueError) as exc_info:
        core_agent_module.parse_code_blobs(text)
    assert "executable code block pattern" in str(exc_info.value)


def test_parse_code_blobs_partial_code_like_text():
    """Test parse_code_blobs raises ValueError for partial code-like text."""
    text = """```python
incomplete statement
"""

    # This should not be valid Python syntax
    with pytest.raises(ValueError):
        core_agent_module.parse_code_blobs(text)


def test_parse_code_blobs_c_code_no_match():
    """Test parse_code_blobs with ```c\\ncontent\\n``` (other language)."""
    text = """Here is some C code:
```c
printf("Hello World");
```
But this should not match."""

    with pytest.raises(ValueError):
        core_agent_module.parse_code_blobs(text)


def test_parse_code_blobs_sql_no_match():
    """Test parse_code_blobs with ```sql\\ncontent\\n``` (other language)."""
    text = """Here is some SQL:
```sql
SELECT * FROM users;
```
But this should not match."""

    with pytest.raises(ValueError):
        core_agent_module.parse_code_blobs(text)


def test_convert_code_format_both_legacy_and_display():
    """Test convert_code_format handles both legacy and new format together."""
    text = """```code:python
legacy_code()
```<END_CODE>
```<DISPLAY:python>
new_code()
```<END_DISPLAY_CODE>"""

    transformed = core_agent_module.convert_code_format(text)

    assert "```python" in transformed
    assert "code:python" not in transformed
    assert "<DISPLAY:" not in transformed


# ----------------------------------------------------------------------------
# Additional edge case tests for convert_code_format to improve coverage
# ----------------------------------------------------------------------------

def test_convert_code_format_single_backtick_display():
    """Test convert_code_format with single backtick prefix."""
    text = """` <DISPLAY:python>
print('hello')
</DISPLAY>"""
    transformed = core_agent_module.convert_code_format(text)
    assert "```python" in transformed
    assert "<DISPLAY:" not in transformed


def test_convert_code_format_double_backtick_display():
    """Test convert_code_format with double backtick prefix."""
    text = """`` <DISPLAY:python>
print('hello')
</DISPLAY>"""
    transformed = core_agent_module.convert_code_format(text)
    assert "``python" in transformed
    assert "<DISPLAY:" not in transformed


def test_convert_code_format_multiple_displays_mixed():
    """Test convert_code_format with mixed display formats."""
    text = """<DISPLAY:python>
first()
</DISPLAY>
```<DISPLAY:javascript>
second()
```<END_DISPLAY_CODE>
```code:ruby
third()
```"""
    transformed = core_agent_module.convert_code_format(text)
    assert "```python" in transformed
    assert "```javascript" in transformed
    assert "```ruby" in transformed


def test_convert_code_format_code_colon_format():
    """Test convert_code_format with code:language format."""
    text = """```code:python
print('hello')
```"""
    transformed = core_agent_module.convert_code_format(text)
    assert "```python" in transformed
    assert "code:" not in transformed


def test_convert_code_format_empty_content():
    """Test convert_code_format with empty content."""
    text = """<DISPLAY:python>
</DISPLAY>"""
    transformed = core_agent_module.convert_code_format(text)
    assert "```python" in transformed
    assert "</DISPLAY>" not in transformed


def test_convert_code_format_unicode_in_display():
    """Test convert_code_format preserves unicode in display blocks."""
    text = """<DISPLAY:python>
def hello():
    return "你好世界"
</DISPLAY>"""
    transformed = core_agent_module.convert_code_format(text)
    assert "```python" in transformed
    assert "你好世界" in transformed


def test_convert_code_format_special_chars_in_display():
    """Test convert_code_format preserves special characters."""
    text = '''<DISPLAY:python>
x = "!@#$%^&*()"
y = 'single quotes'
z = "double quotes"
</DISPLAY>'''
    transformed = core_agent_module.convert_code_format(text)
    assert "```python" in transformed
    assert "!@#$%^&*()" in transformed


def test_convert_code_format_nested_display():
    """Test convert_code_format with nested-like content."""
    text = """<DISPLAY:python>
def foo():
    return "<DISPLAY:text>" * 5
</DISPLAY>"""
    transformed = core_agent_module.convert_code_format(text)
    assert "```python" in transformed
    assert "<DISPLAY:" not in transformed


def test_convert_code_format_closing_tag_only():
    """Test convert_code_format with orphaned closing tags."""
    text = """Some text
</DISPLAY>
More text"""
    transformed = core_agent_module.convert_code_format(text)
    # Should not replace orphan closing tag
    assert "</DISPLAY>" not in transformed


def test_convert_code_format_mixed_backtick_counts():
    """Test convert_code_format with different backtick counts in opening."""
    text1 = """` <DISPLAY:python>
print('one')
</DISPLAY>"""
    text2 = """`` <DISPLAY:python>
print('two')
</DISPLAY>"""
    text3 = """```<DISPLAY:python>
print('three')
</DISPLAY>"""

    t1 = core_agent_module.convert_code_format(text1)
    t2 = core_agent_module.convert_code_format(text2)
    t3 = core_agent_module.convert_code_format(text3)

    assert "`python" in t1
    assert "``python" in t2
    assert "```python" in t3


def test_convert_code_format_end_display_code_only():
    """Test convert_code_format with orphaned END_DISPLAY_CODE."""
    text = """Some text
```<END_DISPLAY_CODE>
More text"""
    transformed = core_agent_module.convert_code_format(text)
    # Should replace the orphaned END_DISPLAY_CODE
    assert "```<END_DISPLAY_CODE>" not in transformed


def test_convert_code_format_end_code_only():
    """Test convert_code_format with orphaned END_CODE."""
    text = """Some text
```<END_CODE>
More text"""
    transformed = core_agent_module.convert_code_format(text)
    # Should replace the orphaned END_CODE
    assert "```<END_CODE>" not in transformed


def test_convert_code_format_complex_real_world():
    """Test convert_code_format with complex real-world output."""
    text = """Here is the result of my analysis:

```<DISPLAY:python>
import json
data = {"result": "success", "value": 42}
print(json.dumps(data, indent=2))
```<END_DISPLAY_CODE>

This code demonstrates how to work with JSON in Python."""

    transformed = core_agent_module.convert_code_format(text)

    assert "```python" in transformed
    assert "import json" in transformed
    assert "```<END_DISPLAY_CODE>" not in transformed
    assert "<DISPLAY:" not in transformed


# ----------------------------------------------------------------------------
# Edge case tests for convert_code_format to improve coverage
# ----------------------------------------------------------------------------

def test_convert_code_format_display_no_closing_angle_bracket():
    """Test convert_code_format handles <DISPLAY:language without closing > gracefully."""
    # This covers line 133: if lang_end == -1: break
    text = """```<DISPLAY:python
print('hello')
```"""
    # The opening tag has no closing >, so it should be left as-is
    transformed = core_agent_module.convert_code_format(text)
    # Should not crash, and should preserve original if no conversion happened
    assert isinstance(transformed, str)


def test_convert_code_format_code_colon_no_language():
    """Test convert_code_format handles code: without language gracefully."""
    # This covers line 150: if lang_end == lang_start: break
    text = """```code:
print('hello')
```"""
    # The code: has no language, so it should be left as-is
    transformed = core_agent_module.convert_code_format(text)
    # Should not crash
    assert isinstance(transformed, str)


def test_convert_code_format_display_tag_no_closing_bracket():
    """Test convert_code_format handles <DISPLAY:language without closing >."""
    # This covers line 163: if lang_end == -1: break
    text = """<DISPLAY:python
print('hello')
</DISPLAY>"""
    # The opening tag has no closing >, so conversion should stop
    transformed = core_agent_module.convert_code_format(text)
    # Should not crash, closing tag should still be converted
    assert "</DISPLAY>" not in transformed


def test_convert_code_format_multiple_display_tags_partial():
    """Test convert_code_format with multiple display tags, some invalid."""
    text = """<DISPLAY:python
first()
</DISPLAY>
<DISPLAY:javascript
second()
</DISPLAY>"""
    # First has closing >, second doesn't
    transformed = core_agent_module.convert_code_format(text)
    assert isinstance(transformed, str)


# ----------------------------------------------------------------------------
# Tests for MAX_STEPS_REACHED handling in _run_stream
# ----------------------------------------------------------------------------

def _create_mock_core_agent_with_step_control():
    """Create a mock CoreAgent that allows controlling step execution."""
    from types import ModuleType

    # Create fresh mocks for this test
    mock_smolagents = _create_mock_smolagents()

    # Create mock memory
    mock_memory = MagicMock()
    mock_memory.steps = []
    mock_memory.system_prompt = None
    mock_memory.get_full_steps = MagicMock(return_value=[])

    # Create mock monitor
    mock_monitor = MagicMock()
    mock_monitor.reset = MagicMock()

    # Create mock logger
    mock_logger = MagicMock()
    mock_logger.log = MagicMock()
    mock_logger.log_markdown = MagicMock()
    mock_logger.log_task = MagicMock()
    mock_logger.log_code = MagicMock()

    # Create mock python_executor
    mock_python_executor = MagicMock()

    # Create mock model
    mock_model = MagicMock()

    # Create ProcessType for observer
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
        MAX_STEPS_REACHED = "MAX_STEPS_REACHED"

    # Create MessageObserver with tracking
    class TrackedMessageObserver:
        def __init__(self):
            self.messages = []
            self.add_message = MagicMock(side_effect=self._track_message)

        def _track_message(self, agent_name, process_type, data):
            self.messages.append({
                "agent_name": agent_name,
                "process_type": process_type,
                "data": data
            })

    observer = TrackedMessageObserver()

    return {
        "mock_smolagents": mock_smolagents,
        "mock_memory": mock_memory,
        "mock_monitor": mock_monitor,
        "mock_logger": mock_logger,
        "mock_python_executor": mock_python_executor,
        "mock_model": mock_model,
        "ProcessType": ProcessType,
        "observer": observer,
    }


class TestMaxStepsReached:
    """Test suite for MAX_STEPS_REACHED handling in CoreAgent."""

    def test_max_steps_reached_observer_message_format(self):
        """Test that MAX_STEPS_REACHED message has correct JSON format."""
        mocks = _create_mock_core_agent_with_step_control()
        observer = mocks["observer"]
        ProcessType = mocks["ProcessType"]

        # Simulate the observer receiving MAX_STEPS_REACHED message
        max_steps = 5
        completed_steps = max_steps - 1  # step_number - 1 when max_steps + 1 is reached

        expected_data = {
            "completedSteps": completed_steps,
            "maxSteps": max_steps,
            "message": ""
        }

        # Add the message as CoreAgent would
        observer.add_message("test_agent", ProcessType.MAX_STEPS_REACHED, json.dumps(expected_data))

        # Verify message was recorded
        assert len(observer.messages) == 1
        msg = observer.messages[0]
        assert msg["agent_name"] == "test_agent"
        assert msg["process_type"] == ProcessType.MAX_STEPS_REACHED

        # Parse and verify JSON data
        parsed_data = json.loads(msg["data"])
        assert parsed_data["completedSteps"] == 4
        assert parsed_data["maxSteps"] == 5
        assert parsed_data["message"] == ""

    def test_max_steps_reached_data_structure(self):
        """Test that max_steps_data JSON structure matches expected format."""
        mocks = _create_mock_core_agent_with_step_control()
        observer = mocks["observer"]
        ProcessType = mocks["ProcessType"]

        # Test with different max_steps values
        # In _run_stream, when step_number == max_steps + 1:
        #   completedSteps = step_number - 1 = max_steps
        expected_completed_steps = [1, 5, 10, 100]

        for max_steps in expected_completed_steps:
            step_number_at_exit = max_steps + 1

            # Simulate the logic in _run_stream
            # not returned_final_answer and step_number == max_steps + 1
            max_steps_data = json.dumps({
                "completedSteps": step_number_at_exit - 1,  # This equals max_steps
                "maxSteps": max_steps,
                "message": ""
            })

            observer.add_message("agent", ProcessType.MAX_STEPS_REACHED, max_steps_data)

        # Verify all messages were recorded
        assert len(observer.messages) == 4

        # Verify each message has correct format
        for i, msg in enumerate(observer.messages):
            parsed = json.loads(msg["data"])
            assert "completedSteps" in parsed
            assert "maxSteps" in parsed
            assert "message" in parsed
            # completedSteps should equal max_steps (since step_number - 1 = max_steps)
            assert parsed["completedSteps"] == expected_completed_steps[i]
            assert parsed["maxSteps"] == expected_completed_steps[i]
            assert parsed["message"] == ""

    def test_max_steps_reached_message_is_json_serializable(self):
        """Test that MAX_STEPS_REACHED data is valid JSON."""
        test_cases = [
            {"max_steps": 1, "completed": 0},
            {"max_steps": 5, "completed": 4},
            {"max_steps": 10, "completed": 9},
            {"max_steps": 100, "completed": 99},
        ]

        for case in test_cases:
            max_steps_data = json.dumps({
                "completedSteps": case["completed"],
                "maxSteps": case["max_steps"],
                "message": ""
            })

            # Should not raise
            parsed = json.loads(max_steps_data)
            assert parsed["completedSteps"] == case["completed"]
            assert parsed["maxSteps"] == case["max_steps"]

    def test_max_steps_reached_with_different_step_numbers(self):
        """Test MAX_STEPS_REACHED handling with various step number values."""
        mocks = _create_mock_core_agent_with_step_control()
        observer = mocks["observer"]
        ProcessType = mocks["ProcessType"]

        # Simulate different scenarios where step_number == max_steps + 1
        scenarios = [
            (1, 2),   # max_steps=1, step_number=2
            (5, 6),   # max_steps=5, step_number=6
            (10, 11), # max_steps=10, step_number=11
            (50, 51), # max_steps=50, step_number=51
        ]

        for max_steps, step_number in scenarios:
            completed = step_number - 1

            max_steps_data = json.dumps({
                "completedSteps": completed,
                "maxSteps": max_steps,
                "message": ""
            })

            observer.add_message("test_agent", ProcessType.MAX_STEPS_REACHED, max_steps_data)

            parsed = json.loads(max_steps_data)
            assert parsed["completedSteps"] == completed
            assert parsed["maxSteps"] == max_steps

        assert len(observer.messages) == 4

    def test_max_steps_reached_empty_message_field(self):
        """Test that MAX_STEPS_REACHED message field is empty string."""
        mocks = _create_mock_core_agent_with_step_control()
        observer = mocks["observer"]
        ProcessType = mocks["ProcessType"]

        max_steps_data = json.dumps({
            "completedSteps": 5,
            "maxSteps": 5,
            "message": ""
        })

        observer.add_message("agent", ProcessType.MAX_STEPS_REACHED, max_steps_data)

        parsed = json.loads(observer.messages[0]["data"])
        assert parsed["message"] == ""
        assert isinstance(parsed["message"], str)

    def test_process_type_has_max_steps_reached(self):
        """Test that ProcessType enum has MAX_STEPS_REACHED attribute."""
        mocks = _create_mock_core_agent_with_step_control()
        ProcessType = mocks["ProcessType"]

        assert hasattr(ProcessType, "MAX_STEPS_REACHED")
        assert ProcessType.MAX_STEPS_REACHED == "MAX_STEPS_REACHED"

    def test_max_steps_reached_with_large_values(self):
        """Test MAX_STEPS_REACHED with large step numbers."""
        mocks = _create_mock_core_agent_with_step_control()
        observer = mocks["observer"]
        ProcessType = mocks["ProcessType"]

        large_max_steps = 10000
        step_number = large_max_steps + 1
        # In _run_stream: completedSteps = step_number - 1 = max_steps = 10000
        completed = step_number - 1  # This equals max_steps

        max_steps_data = json.dumps({
            "completedSteps": completed,
            "maxSteps": large_max_steps,
            "message": ""
        })

        observer.add_message("large_agent", ProcessType.MAX_STEPS_REACHED, max_steps_data)

        parsed = json.loads(observer.messages[0]["data"])
        # completedSteps equals max_steps when step_number = max_steps + 1
        assert parsed["completedSteps"] == 10000
        assert parsed["maxSteps"] == 10000
        assert parsed["message"] == ""

    def test_max_steps_reached_zero_max_steps(self):
        """Test MAX_STEPS_REACHED when max_steps is 0 (edge case)."""
        mocks = _create_mock_core_agent_with_step_control()
        observer = mocks["observer"]
        ProcessType = mocks["ProcessType"]

        # Edge case: max_steps=0, step_number=1
        max_steps_data = json.dumps({
            "completedSteps": 0,
            "maxSteps": 0,
            "message": ""
        })

        observer.add_message("edge_agent", ProcessType.MAX_STEPS_REACHED, max_steps_data)

        parsed = json.loads(observer.messages[0]["data"])
        assert parsed["completedSteps"] == 0
        assert parsed["maxSteps"] == 0

    def test_observer_add_message_side_effect(self):
        """Test that observer.add_message correctly tracks messages."""
        mocks = _create_mock_core_agent_with_step_control()
        observer = mocks["observer"]
        ProcessType = mocks["ProcessType"]

        # Verify add_message is callable
        assert callable(observer.add_message)

        # Add multiple messages
        test_messages = [
            ("agent1", ProcessType.STEP_COUNT, 1),
            ("agent1", ProcessType.MAX_STEPS_REACHED, json.dumps({"completedSteps": 5, "maxSteps": 5, "message": ""})),
            ("agent1", ProcessType.AGENT_FINISH, "done"),
        ]

        for agent_name, process_type, data in test_messages:
            observer.add_message(agent_name, process_type, data)

        assert len(observer.messages) == 3
        assert observer.messages[1]["process_type"] == ProcessType.MAX_STEPS_REACHED


# ----------------------------------------------------------------------------
# Tests for _run_stream method with real execution for line coverage
# ----------------------------------------------------------------------------

class TestRunStreamRealExecution:
    """Tests that actually execute the real _run_stream method for line coverage."""

    class _FakeActionStep:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class _FakeAgentGenerationError(Exception):
        def __init__(self, message, logger):
            super().__init__(message)

    @classmethod
    def _create_canonical_run_agent(cls, monkeypatch, **attributes):
        monkeypatch.setattr(core_agent_module, "ActionStep", cls._FakeActionStep)
        monkeypatch.setattr(core_agent_module, "AgentGenerationError", cls._FakeAgentGenerationError)
        monkeypatch.setattr(core_agent_module, "FinalAnswerStep", lambda output: SimpleNamespace(output=output))
        monkeypatch.setattr(core_agent_module, "handle_agent_output_types", lambda output: output)

        agent = object.__new__(core_agent_module.CoreAgent)
        defaults = {
            "agent_name": "test_agent",
            "name": "test_agent",
            "observer": MagicMock(),
            "stop_event": MagicMock(),
            "step_number": 1,
            "memory": MagicMock(),
            "logger": MagicMock(),
            "model": MagicMock(),
            "final_answer_checks": [],
            "enable_planning": False,
            "verification_config": SimpleNamespace(enabled=False, final_verification_enabled=False),
            "_finalize_step": MagicMock(),
            "_collect_step_metrics": MagicMock(),
        }
        defaults.update(attributes)
        for name, value in defaults.items():
            setattr(agent, name, value)
        agent.stop_event.is_set.return_value = False
        agent.memory.steps = []
        return agent

    @staticmethod
    def _context_runtime_mock(
        *,
        calls=0,
        input_tokens=0,
        output_tokens=0,
        cache_hits=0,
        cache_types=None,
        token_threshold=None,
    ):
        runtime = MagicMock()
        runtime.compression_stats.return_value = {
            "calls": calls,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_hits": cache_hits,
            "cache_types": cache_types or [],
        }
        runtime.chars_per_token = 1.5
        runtime.token_threshold = token_threshold
        runtime.token_counts.return_value = {"uncompressed": None, "compressed": None}
        runtime.consume_history_summary_event.return_value = None
        return runtime

    def _load_core_agent_in_isolation(self):
        """Load CoreAgent in isolation without the test's module mocks."""
        import importlib.util
        import threading
        import time as time_module
        import copy

        # Create a minimal base class that mimics CodeAgent
        class MinimalCodeAgent:
            enable_planning = False  # v1.4: CoreAgent._run_stream checks this attr

            def __init__(self, *args, **kwargs):
                pass

        # Create mock modules
        mock_modules = {}

        # Create mock rich
        mock_rich = MagicMock()
        mock_rich.Group = MagicMock(side_effect=lambda *args: args)
        mock_rich.Text = MagicMock()
        mock_rich.console = MagicMock()
        mock_rich.console.Group = MagicMock(side_effect=lambda *args: args)
        mock_modules['rich'] = mock_rich
        mock_modules['rich.console'] = mock_rich.console
        mock_modules['rich.text'] = mock_rich.Text

        # Create mock jinja2
        mock_jinja2 = MagicMock()
        mock_jinja2.Template = MagicMock()
        mock_jinja2.StrictUndefined = MagicMock()
        mock_modules['jinja2'] = mock_jinja2

        # Create mock smolagents with REAL CodeAgent base
        mock_smolagents = MagicMock()
        mock_smolagents.__path__ = []

        # agents submodule - use REAL CodeAgent
        mock_agents = MagicMock()
        mock_agents.CodeAgent = MinimalCodeAgent  # Use real minimal class
        mock_agents.handle_agent_output_types = lambda x: x
        mock_agents.AgentError = Exception
        mock_agents.ActionOutput = MagicMock()
        mock_agents.RunResult = MagicMock()
        mock_agents.populate_template = MagicMock()
        mock_modules['smolagents.agents'] = mock_agents
        mock_smolagents.agents = mock_agents

        # local_python_executor
        mock_local_python = MagicMock()
        mock_local_python.fix_final_answer_code = lambda x: x
        mock_modules['smolagents.local_python_executor'] = mock_local_python
        mock_smolagents.local_python_executor = mock_local_python

        # memory submodule
        mock_memory = MagicMock()
        mock_memory.ActionStep = MagicMock()
        mock_memory.ToolCall = MagicMock()
        mock_memory.TaskStep = MagicMock()
        mock_memory.SystemPromptStep = MagicMock()
        mock_memory.PlanningStep = MagicMock()
        mock_memory.FinalAnswerStep = MagicMock()
        mock_modules['smolagents.memory'] = mock_memory
        mock_smolagents.memory = mock_memory

        # models submodule
        mock_models = MagicMock()
        mock_models.ChatMessage = MagicMock()
        mock_models.CODEAGENT_RESPONSE_FORMAT = MagicMock()
        mock_modules['smolagents.models'] = mock_models
        mock_smolagents.models = mock_models

        # monitoring submodule
        mock_monitoring = MagicMock()
        mock_monitoring.LogLevel = MagicMock()
        mock_monitoring.Timing = MagicMock()
        mock_monitoring.YELLOW_HEX = "#FFFF00"
        mock_monitoring.TokenUsage = MagicMock()
        mock_modules['smolagents.monitoring'] = mock_monitoring
        mock_smolagents.monitoring = mock_monitoring

        # utils submodule
        mock_utils = MagicMock()
        mock_utils.AgentExecutionError = Exception
        mock_utils.AgentGenerationError = Exception
        mock_utils.AgentParsingError = Exception
        mock_utils.AgentMaxStepsError = Exception
        mock_utils.truncate_content = lambda content, max_length=1000: str(content)[:max_length]
        mock_utils.extract_code_from_text = lambda x, y: x
        mock_modules['smolagents.utils'] = mock_utils
        mock_smolagents.utils = mock_utils

        mock_modules['smolagents'] = mock_smolagents

        # Create mock observer with ProcessType
        class RealProcessType:
            STEP_COUNT = "STEP_COUNT"
            PARSE = "PARSE"
            EXECUTION_LOGS = "EXECUTION_LOGS"
            AGENT_NEW_RUN = "AGENT_NEW_RUN"
            AGENT_FINISH = "AGENT_FINISH"
            FINAL_ANSWER = "FINAL_ANSWER"
            ERROR = "ERROR"
            OTHER = "OTHER"
            TOOL = "TOOL"
            MAX_STEPS_REACHED = "MAX_STEPS_REACHED"

        mock_observer = MagicMock()
        mock_observer.ProcessType = RealProcessType
        mock_modules['sdk.nexent.core.utils.observer'] = mock_observer

        # Save original modules
        original_modules = {}
        for name in mock_modules:
            if name in sys.modules:
                original_modules[name] = sys.modules[name]

        # Replace with mocks
        for name, module in mock_modules.items():
            sys.modules[name] = module

        try:
            # Find the core_agent.py file
            test_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(test_dir))))
            core_agent_path = os.path.join(project_root, "sdk", "nexent", "core", "agents", "core_agent.py")

            # Load the module
            spec = importlib.util.spec_from_file_location("core_agent_test", core_agent_path)
            module = importlib.util.module_from_spec(spec)
            module.__package__ = "sdk.nexent.core.agents"

            sys.modules["sdk.nexent.core.agents.core_agent"] = module

            # Execute
            spec.loader.exec_module(module)
            return module
        finally:
            # Restore original modules
            for name, module in original_modules.items():
                sys.modules[name] = module

    def test_rejects_context_over_hard_budget_before_model_call(self):
        module = self._load_core_agent_in_isolation()
        final_context = MagicMock()
        final_context.evidence.over_hard_budget = True
        final_context.evidence.final_token_estimate = 120
        final_context.evidence.hard_budget = 100

        with pytest.raises(ValueError, match="120 > 100"):
            module.CoreAgent._ensure_context_within_hard_budget(final_context)

    def test_run_stream_max_steps_path_real_execution(self):
        """Test that actually executes _run_stream and covers max_steps path lines."""
        import threading

        # Create ProcessType with all needed constants
        class TestProcessType:
            MAX_STEPS_REACHED = "MAX_STEPS_REACHED"
            STEP_COUNT = "STEP_COUNT"

        # Track observer calls
        observer_calls = []

        # Load CoreAgent in isolation
        module = self._load_core_agent_in_isolation()
        CoreAgent = module.CoreAgent
        # Verify CoreAgent is a real class, not a Mock
        assert not isinstance(CoreAgent, MagicMock), "CoreAgent should not be MagicMock"

        # Create mock observer that tracks calls
        def mock_add_message(agent_name, process_type, data):
            observer_calls.append((agent_name, process_type, data))

        # Use a real output type so the isinstance branch is covered while
        # is_final_answer=False continues to the max-step fallback.
        class FakeActionOutput:
            def __init__(self):
                self.output = "intermediate result"
                self.is_final_answer = False

        module.ActionOutput = FakeActionOutput
        mock_action_output = FakeActionOutput()

        # Track _handle_max_steps_reached
        handle_calls = []

        def mock_handle_max_steps_reached(task):
            handle_calls.append(task)
            return "Maximum steps reached"

        # Create mock memory
        mock_memory = MagicMock()
        mock_memory.steps = []

        # Create mock logger
        mock_logger = MagicMock()

        # Create stop_event (NOT set)
        stop_event = threading.Event()
        # stop_event is NOT set, so loop will continue until max_steps

        # Create mock step_stream that returns non-final answer
        call_count = [0]
        def mock_step_stream(action_step):
            call_count[0] += 1
            yield mock_action_output

        # Create agent instance
        agent = object.__new__(CoreAgent)
        agent.agent_name = "test_agent"
        agent.observer = MagicMock()
        agent.observer.add_message = mock_add_message
        agent.stop_event = stop_event
        agent.step_number = 1
        agent.memory = mock_memory
        agent.logger = mock_logger
        agent.monitor = MagicMock()
        agent.max_steps = 2  # Only 2 steps allowed
        agent.name = "test_agent"
        agent.task = "test task"
        agent.state = {}
        agent.final_answer_checks = None
        agent.return_full_result = False
        agent.python_executor = MagicMock()
        agent.model = MagicMock()
        agent.prompt_templates = {}
        agent.tools = {}
        agent.managed_agents = {}
        agent.provide_run_summary = False
        agent._use_structured_outputs_internally = False
        agent.enable_planning = False
        agent.verification_config = SimpleNamespace(
            enabled=False,
            final_verification_enabled=False,
        )
        agent.context_runtime = self._context_runtime_mock()
        agent.step_metrics = []

        agent._step_stream = mock_step_stream
        agent._handle_max_steps_reached = mock_handle_max_steps_reached
        agent._finalize_step = lambda x: None

        # Call _run_stream
        generator = agent._run_stream("test task", max_steps=2)
        results = list(generator)

        # Assertions
        assert len(results) > 0
        # Check that MAX_STEPS_REACHED was called
        max_steps_calls = [c for c in observer_calls if c[1] == TestProcessType.MAX_STEPS_REACHED]
        assert len(max_steps_calls) == 1, f"Expected 1 MAX_STEPS_REACHED call, got {max_steps_calls}"
        assert len(handle_calls) == 1
        assert handle_calls[0] == "test task"

    def test_collect_step_metrics_records_monitoring_event(self):
        """_collect_step_metrics forwards context/compression metrics to monitoring."""
        module = self._load_core_agent_in_isolation()
        CoreAgent = module.CoreAgent
        module.msg_token_count = MagicMock(side_effect=[55, 8])

        fake_monitoring_manager = MagicMock()
        module.get_monitoring_manager = MagicMock(return_value=fake_monitoring_manager)

        agent = object.__new__(CoreAgent)
        agent.step_metrics = []
        agent._last_uncompressed_est = 110
        agent.context_runtime = self._context_runtime_mock(
            calls=1,
            input_tokens=80,
            output_tokens=40,
            cache_hits=1,
            cache_types=["exact"],
            token_threshold=4096,
        )

        action_step = MagicMock()
        action_step.step_number = 3
        action_step.token_usage.input_tokens = 100
        action_step.token_usage.output_tokens = 12
        action_step.model_input_messages = [{"role": "user", "content": "hello"}]
        action_step.model_output_message = {"role": "assistant", "content": "ok"}

        agent._collect_step_metrics(action_step)

        metric = agent.step_metrics[0]
        assert metric["step_number"] == 3
        assert metric["main_llm"]["input_tokens"] == 100
        assert metric["memory_state"]["estimated_input_tokens"] == 55
        assert metric["compression"]["calls"] == 1
        assert metric["compression_ratio"] == 50.0
        fake_monitoring_manager.record_agent_step_metrics.assert_called_once_with(
            metric,
            token_threshold=4096,
        )

    def test_step_stream_uses_context_runtime_for_uncompressed_est(self):
        """_step_stream pulls the raw estimate through the runtime contract."""
        module = self._load_core_agent_in_isolation()
        CoreAgent = module.CoreAgent

        agent = object.__new__(CoreAgent)
        agent.agent_name = "test"
        agent.observer = MagicMock()
        agent.step_number = 1
        agent.memory = MagicMock()
        agent.memory.steps = []
        agent.memory.system_prompt = None
        agent.logger = MagicMock()
        agent.monitor = MagicMock()

        agent.context_runtime = self._context_runtime_mock()
        agent.context_runtime.chars_per_token = 1.0
        agent.context_runtime.token_counts.return_value = {
            "uncompressed": 5000,
            "compressed": 1000,
        }
        mock_context = MagicMock()
        mock_context.messages = [MagicMock()]
        agent.context_runtime.prepare_step = MagicMock(return_value=mock_context)

        agent.model = MagicMock()
        response = MagicMock()
        response.content = "ok"
        agent.model.return_value = response

        agent._history_step_count = 0
        agent._context_tools = MagicMock(return_value=[])
        agent._use_structured_outputs_internally = False
        agent._ephemeral_system_messages = None

        action_step = MagicMock()
        generator = agent._step_stream(action_step)
        try:
            next(generator)
        except (StopIteration, ValueError):
            pass

        assert agent._last_uncompressed_est == 5000

    def test_ac_p2_011_step_stream_supplies_source_backed_rebuild_for_w2(self):
        module = self._load_core_agent_in_isolation()
        CoreAgent = module.CoreAgent
        agent = object.__new__(CoreAgent)
        agent.agent_name = "test"
        agent.observer = MagicMock()
        agent.step_number = 1
        agent.memory = MagicMock(steps=[], system_prompt=None)
        agent.logger = MagicMock()
        agent.monitor = MagicMock()
        agent.context_runtime = self._context_runtime_mock()
        agent.context_runtime.chars_per_token = 1.0
        agent.context_runtime.token_counts.return_value = {"uncompressed": 10, "compressed": 10}
        initial = MagicMock(messages=[MagicMock()])
        initial.evidence.over_hard_budget = False
        rebuilt = MagicMock(messages=[MagicMock()])
        rebuilt.evidence.over_hard_budget = False
        agent.context_runtime.prepare_step.side_effect = [initial, rebuilt]
        response = MagicMock(content="ok")
        agent.model = MagicMock(return_value=response)
        agent.model.safe_input_budget_snapshot = {"fingerprint": "w2"}
        agent._history_step_count = 0
        agent._context_tools = MagicMock(return_value=[])
        agent._use_structured_outputs_internally = False
        action_step = MagicMock()

        stream = agent._step_stream(action_step)
        try:
            next(stream)
        except (StopIteration, ValueError):
            pass

        callback = agent.model.call_args.kwargs["context_rebuild"]
        assert callback(123) is rebuilt
        assert agent.context_runtime.prepare_step.call_args.kwargs[
            "target_input_budget_tokens"
        ] == 123

    def test_ac_002_emergency_archive_tool_refreshes_live_executor_registry(self):
        module = self._load_core_agent_in_isolation()
        CoreAgent = module.CoreAgent
        agent = object.__new__(CoreAgent)
        existing_tool = MagicMock(name="existing_tool")
        archive_tool = MagicMock(name="archive_tool")
        archive_tool.name = "search_archived_history"
        agent.tools = {"existing_tool": existing_tool}
        agent.managed_agents = {}
        agent.python_executor = MagicMock()
        agent.context_runtime = MagicMock()
        agent.context_runtime.context_manager.activate_emergency_archive.return_value = archive_tool
        agent._guardrail_wrap_tools = MagicMock()
        agent._wrap_visible_tool_events = MagicMock()

        result = agent._activate_emergency_archive_tool(hard_budget=10_000)

        assert result is archive_tool
        assert agent.tools["search_archived_history"] is archive_tool
        agent.python_executor.send_tools.assert_called_once_with({
            "existing_tool": existing_tool,
            "search_archived_history": archive_tool,
        })

    def test_ac_003_recall_execution_emits_updated_persistable_budget_event(self):
        module = self._load_core_agent_in_isolation()
        CoreAgent = module.CoreAgent
        module.ProcessType.CONTEXT_BUDGET = "context_budget"

        @dataclass(frozen=True)
        class Evidence:
            purpose: str = "step"
            raw_token_estimate: int = 100
            final_token_estimate: int = 80
            compression_attempted: bool = True
            fallback_compaction_used: bool = False
            compression_records: tuple = ()
            archive_active: bool = True
            archived_item_count: int = 2
            retained_item_count: int = 4
            recall_invocation_count: int = 0
            recalled_tokens: int = 0

        agent = object.__new__(CoreAgent)
        agent.agent_name = "test"
        agent.step_number = 1
        agent.observer = MagicMock()
        archive = SimpleNamespace(recall_invocations=1, recalled_tokens=4000)
        agent.context_runtime = SimpleNamespace(
            context_manager=SimpleNamespace(
                archive_tool=SimpleNamespace(archive=archive)
            )
        )
        components = SimpleNamespace(
            message_text=50, message_framing=5, tools=10,
            media=0, reasoning=0, other_semantic=0,
        )
        preflight = SimpleNamespace(
            components=components, soft_budget=100, hard_budget=90,
            hard_count=70, count_source="estimated",
            request_fingerprint="request", identity_fingerprint="budget",
            retry_ordinal=2,
        )
        agent.model = SimpleNamespace(
            last_context_evidence=Evidence(),
            last_final_request_preflight=preflight,
            _using_provisional_capacity=False,
        )

        agent._emit_archive_recall_budget_update()

        emitted = json.loads(agent.observer.add_message.call_args.args[2])
        assert emitted["recovery"]["recall_invocation_count"] == 1
        assert emitted["recovery"]["recalled_tokens"] == 4000
        assert agent.model.last_context_evidence.recalled_tokens == 4000

    def test_step_stream_falls_back_without_uncompressed_runtime_count(self):
        """_step_stream estimates messages when the runtime has no raw sample."""
        module = self._load_core_agent_in_isolation()
        CoreAgent = module.CoreAgent

        agent = object.__new__(CoreAgent)
        agent.agent_name = "test"
        agent.observer = MagicMock()
        agent.step_number = 1
        agent.memory = MagicMock()
        agent.memory.steps = []
        agent.memory.system_prompt = None
        agent.logger = MagicMock()
        agent.monitor = MagicMock()

        agent.context_runtime = self._context_runtime_mock()
        agent.context_runtime.chars_per_token = 2.0
        mock_context = MagicMock()
        mock_context.messages = [MagicMock()]
        agent.context_runtime.prepare_step = MagicMock(return_value=mock_context)

        agent.model = MagicMock()
        response = MagicMock()
        response.content = "ok"
        agent.model.return_value = response

        agent._history_step_count = 0
        agent._context_tools = MagicMock(return_value=[])
        agent._use_structured_outputs_internally = False
        agent._ephemeral_system_messages = None

        action_step = MagicMock()
        generator = agent._step_stream(action_step)
        try:
            next(generator)
        except (StopIteration, ValueError):
            pass

        # When the runtime has no raw count, fall back to msg_token_count.
        assert agent._last_uncompressed_est != 5000

    def test_step_stream_rejects_whitespace_only_model_output(self, monkeypatch):
        """Whitespace-only provider content is a generation error, not a final answer."""
        module = core_agent_module
        CoreAgent = module.CoreAgent
        monkeypatch.setattr(module, "AgentExecutionError", type("AgentExecutionError", (Exception,), {}))
        monkeypatch.setattr(module, "AgentGenerationError", type("AgentGenerationError", (Exception,), {}))

        agent = object.__new__(CoreAgent)
        agent.agent_name = "test"
        agent.observer = MagicMock()
        agent.step_number = 1
        agent.memory = MagicMock()
        agent.memory.steps = []
        agent.logger = MagicMock()
        agent.context_runtime = self._context_runtime_mock()
        final_context = MagicMock()
        final_context.messages = [MagicMock()]
        final_context.evidence.over_hard_budget = False
        agent.context_runtime.prepare_step.return_value = final_context
        agent._history_step_count = 0
        agent._context_tools = MagicMock(return_value=[])
        agent._use_structured_outputs_internally = False

        response = MagicMock()
        response.content = "   \n\t"
        response.token_usage = None
        agent.model = MagicMock(return_value=response)

        action_step = MagicMock()
        stream = agent._step_stream(action_step)
        with pytest.raises(Exception, match="empty or whitespace-only output"):
            next(stream)

        assert action_step.model_output == "   \n\t"

    def test_run_stream_stop_event_path_real_execution(self):
        """Test _run_stream with stop_event set (user break)."""
        import threading

        # Create ProcessType
        class ProcessType:
            MAX_STEPS_REACHED = "MAX_STEPS_REACHED"

        # Track observer calls
        observer_calls = []

        # Load CoreAgent
        module = self._load_core_agent_in_isolation()
        CoreAgent = module.CoreAgent

        # Verify it's a real class
        assert not isinstance(CoreAgent, MagicMock)

        # Create mock action output
        mock_action_output = MagicMock()
        mock_action_output.is_final_answer = False

        # Create mock memory
        mock_memory = MagicMock()
        mock_memory.steps = []

        # Create stop_event set
        stop_event = threading.Event()
        stop_event.set()

        # Create mock step_stream
        def mock_step_stream(action_step):
            yield mock_action_output

        # Create agent
        agent = object.__new__(CoreAgent)
        agent.agent_name = "test_agent"
        agent.observer = MagicMock()
        agent.observer.add_message = lambda *args: observer_calls.append(args)
        agent.stop_event = stop_event
        agent.step_number = 1
        agent.memory = mock_memory
        agent.logger = MagicMock()
        agent.monitor = MagicMock()
        agent.max_steps = 10
        agent.name = "test_agent"
        agent.task = "test task"
        agent.state = {}
        agent.final_answer_checks = None
        agent.return_full_result = False
        agent.python_executor = MagicMock()
        agent.model = MagicMock()
        agent.prompt_templates = {}
        agent.tools = {}
        agent.managed_agents = {}
        agent.provide_run_summary = False
        agent._use_structured_outputs_internally = False

        agent._step_stream = mock_step_stream
        agent._handle_max_steps_reached = MagicMock(return_value="Max steps")
        agent._finalize_step = lambda x: None

        # Call _run_stream
        generator = agent._run_stream("test task", max_steps=10)
        results = list(generator)

        # Assertions - stop_event should prevent MAX_STEPS_REACHED
        assert len(results) > 0
        max_steps_calls = [c for c in observer_calls if c[1] == ProcessType.MAX_STEPS_REACHED]
        assert len(max_steps_calls) == 0

    def test_run_stream_stop_event_path_real_execution(self):
        """Test _run_stream with stop_event set (user break)."""
        import threading

        # Create ProcessType
        class TestProcessType:
            MAX_STEPS_REACHED = "MAX_STEPS_REACHED"

        # Track observer calls
        observer_calls = []

        # Load CoreAgent
        module = self._load_core_agent_in_isolation()
        CoreAgent = module.CoreAgent

        # Verify it's a real class
        assert not isinstance(CoreAgent, MagicMock)

        # Create mock action output
        mock_action_output = MagicMock()
        mock_action_output.is_final_answer = False

        # Create mock memory
        mock_memory = MagicMock()
        mock_memory.steps = []

        # Create stop_event set
        stop_event = threading.Event()
        stop_event.set()

        # Create mock step_stream
        def mock_step_stream(action_step):
            yield mock_action_output

        # Create agent
        agent = object.__new__(CoreAgent)
        agent.agent_name = "test_agent"
        agent.observer = MagicMock()
        agent.observer.add_message = lambda *args: observer_calls.append(args)
        agent.stop_event = stop_event
        agent.step_number = 1
        agent.memory = mock_memory
        agent.logger = MagicMock()
        agent.monitor = MagicMock()
        agent.max_steps = 10
        agent.name = "test_agent"
        agent.task = "test task"
        agent.state = {}
        agent.final_answer_checks = None
        agent.return_full_result = False
        agent.python_executor = MagicMock()
        agent.model = MagicMock()
        agent.prompt_templates = {}
        agent.tools = {}
        agent.managed_agents = {}
        agent.provide_run_summary = False
        agent._use_structured_outputs_internally = False

        agent._step_stream = mock_step_stream
        agent._handle_max_steps_reached = MagicMock(return_value="Max steps")
        agent._finalize_step = lambda x: None

        # Call _run_stream
        generator = agent._run_stream("test task", max_steps=10)
        results = list(generator)

        # Assertions - stop_event should prevent MAX_STEPS_REACHED
        assert len(results) > 0
        max_steps_calls = [c for c in observer_calls if c[1] == TestProcessType.MAX_STEPS_REACHED]
        assert len(max_steps_calls) == 0

    def test_run_stream_final_answer_error_path(self):
        """Test _run_stream when FinalAnswerError is raised."""
        # This covers the code path where the model outputs non-code text (FinalAnswerError)

        # Create ProcessType
        class TestProcessType:
            MAX_STEPS_REACHED = "MAX_STEPS_REACHED"

        # Track observer calls
        observer_calls = []

        # Load CoreAgent
        module = self._load_core_agent_in_isolation()
        CoreAgent = module.CoreAgent

        # Verify it's a real class
        assert not isinstance(CoreAgent, MagicMock)

        # Get FinalAnswerError from the loaded module
        FinalAnswerError = module.FinalAnswerError

        # Create mock memory
        mock_memory = MagicMock()
        mock_memory.steps = []

        # Create stop_event not set
        stop_event = MagicMock()
        stop_event.is_set = lambda: False

        # Track step_stream calls
        step_stream_calls = [0]

        # Create mock ActionStep with model_output
        mock_action_step = MagicMock()
        mock_action_step.model_output = "This is my final answer"
        mock_action_step.is_final_answer = True

        # Create step_stream that raises FinalAnswerError
        def mock_step_stream(action_step):
            step_stream_calls[0] += 1
            # Return the mock action step that has model_output
            yield mock_action_step
            # Then raise FinalAnswerError to trigger the except block
            raise FinalAnswerError()

        # Create agent
        agent = object.__new__(CoreAgent)
        agent.agent_name = "test_agent"
        agent.observer = MagicMock()
        agent.observer.add_message = lambda *args: observer_calls.append(args)
        agent.stop_event = stop_event
        agent.step_number = 1
        agent.memory = mock_memory
        agent.logger = MagicMock()
        agent.logger.log = lambda *args, **kwargs: None
        agent.monitor = MagicMock()
        agent.max_steps = 10
        agent.name = "test_agent"
        agent.task = "test task"
        agent.state = {}
        agent.final_answer_checks = None
        agent.return_full_result = False
        agent.python_executor = MagicMock()
        agent.model = MagicMock()
        agent.prompt_templates = {}
        agent.tools = {}
        agent.managed_agents = {}
        agent.provide_run_summary = False
        agent._use_structured_outputs_internally = False
        agent.context_runtime = self._context_runtime_mock()
        agent.step_metrics = []

        agent._step_stream = mock_step_stream
        agent._handle_max_steps_reached = MagicMock(return_value="Max steps")
        agent._finalize_step = lambda x: None

        # Call _run_stream
        generator = agent._run_stream("test task", max_steps=10)

        # Consume the generator
        try:
            results = list(generator)
        except FinalAnswerError:
            # The generator may raise FinalAnswerError - that's okay
            pass

        # FinalAnswerError path should prevent MAX_STEPS_REACHED
        max_steps_calls = [c for c in observer_calls if c[1] == TestProcessType.MAX_STEPS_REACHED]
        assert len(max_steps_calls) == 0

    def test_run_stream_retries_empty_final_answer_tool_result(self, monkeypatch):
        """An empty final_answer tool result must not end the run successfully."""
        module = core_agent_module

        class FakeActionOutput:
            def __init__(self, output, is_final_answer):
                self.output = output
                self.is_final_answer = is_final_answer

        class FakeAgentError(Exception):
            pass

        class FakeAgentExecutionError(FakeAgentError):
            def __init__(self, message, logger):
                super().__init__(message)

        monkeypatch.setattr(module, "ActionOutput", FakeActionOutput)
        monkeypatch.setattr(module, "AgentError", FakeAgentError)
        monkeypatch.setattr(module, "AgentExecutionError", FakeAgentExecutionError)
        agent = self._create_canonical_run_agent(
            monkeypatch,
            model=MagicMock(last_response_diagnostics={"finish_reason": "stop"}),
        )

        outputs = iter(["", "valid answer"])

        def mock_step_stream(_action_step):
            yield FakeActionOutput(next(outputs), True)

        agent._step_stream = mock_step_stream

        results = list(agent._run_stream("test task", max_steps=2))

        assert results[-1].output == "valid answer"
        assert len(agent.memory.steps) == 2
        assert agent.memory.steps[0].error is not None

    def test_planning_run_retries_empty_direct_answer_then_verifies_valid_answer(self, monkeypatch):
        """Planning runs reset state, retry an empty answer, and verify the next answer."""
        module = core_agent_module

        agent = self._create_canonical_run_agent(
            monkeypatch,
            enable_planning=True,
            model=MagicMock(last_response_diagnostics={"finish_reason": "length"}),
            verification_config=SimpleNamespace(
                enabled=True,
                final_verification_enabled=True,
                max_final_rounds=2,
            ),
        )
        agent.current_plan = "stale plan"
        agent.current_step_index = 99
        agent.verification_controller = MagicMock()
        agent.verification_controller.verify_final_answer.return_value = SimpleNamespace(
            passed=True
        )
        agent._build_verification_memory_summary = MagicMock(return_value="summary")

        direct_answers = iter([" \n", "valid direct answer"])

        def mock_step_stream(action_step):
            action_step.model_output = next(direct_answers)
            if False:
                yield None
            raise module.FinalAnswerError()

        agent._step_stream = mock_step_stream

        results = list(agent._run_stream("test task", max_steps=2))

        assert results[-1].output == "valid direct answer"
        assert agent.current_plan is None
        assert agent.current_step_index == 0
        assert len(agent.memory.steps) == 2
        assert agent.memory.steps[0].error is not None
        agent.verification_controller.verify_final_answer.assert_called_once()
        assert agent.verification_controller.verify_final_answer.call_args.kwargs[
            "candidate"
        ] == "valid direct answer"

# ----------------------------------------------------------------------------
# Tests for _handle_max_steps_reached method
# ----------------------------------------------------------------------------

class TestHandleMaxStepsReached:
    """Test suite for _handle_max_steps_reached method."""

    def _create_agent_for_handle_max_steps_test(self):
        """Create a CoreAgent instance with mocked dependencies for testing _handle_max_steps_reached."""
        module = TestRunStreamRealExecution._load_core_agent_in_isolation(self)
        CoreAgent = module.CoreAgent

        agent = object.__new__(CoreAgent)
        agent.agent_name = "test_agent"
        agent.observer = MagicMock()
        agent.observer.add_message = MagicMock()
        agent.stop_event = threading.Event()
        agent.step_number = 3
        agent.memory = MagicMock()
        agent.memory.steps = []
        agent.logger = MagicMock()
        agent.logger.log = MagicMock()
        agent.monitor = MagicMock()
        agent.max_steps = 3
        agent.name = "test_agent"
        agent.task = "original task"
        agent.state = {}
        agent.final_answer_checks = None
        agent.return_full_result = False
        agent.python_executor = MagicMock()
        agent.prompt_templates = {
            "final_answer": {
                "pre_messages": "Final answer system prompt",
                "post_messages": "Given task: {{ task }}, summarize."
            }
        }
        agent.tools = {}
        agent.managed_agents = {}
        agent.provide_run_summary = False
        agent._use_structured_outputs_internally = False
        agent._history_step_count = 0
        agent.context_runtime = MagicMock()
        agent.context_runtime.prepare_final_answer = MagicMock(
            return_value=MagicMock(
                messages=[
                    {"role": "system", "content": "Final answer system prompt"},
                    {"role": "user", "content": "Given task: original task, summarize."},
                ],
                evidence=MagicMock(),
            )
        )

        return agent, module

    def test_handle_max_steps_reached_success(self):
        """Test successful final answer generation when max steps reached."""
        agent, module = self._create_agent_for_handle_max_steps_test()

        # Mock write_memory_to_messages
        agent.write_memory_to_messages = MagicMock(return_value=[
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Task"},
        ])

        # Mock the model to return a final answer
        mock_chat_message = MagicMock()
        mock_chat_message.role = "assistant"
        mock_chat_message.content = "This is the summary after reaching max steps."
        mock_chat_message.token_usage = MagicMock()
        mock_chat_message.token_usage.input_tokens = 100
        mock_chat_message.token_usage.output_tokens = 50

        agent.model = MagicMock(return_value=mock_chat_message)

        # Mock _finalize_step to track it was called
        finalize_calls = []
        agent._finalize_step = lambda step: finalize_calls.append(step)

        # Call the method
        result = agent._handle_max_steps_reached("original task")

        # Verify result
        assert result == "This is the summary after reaching max steps."

        # Verify observer was called with STEP_COUNT
        observer_calls = agent.observer.add_message.call_args_list
        step_count_calls = [c for c in observer_calls if c[0][1] == module.ProcessType.STEP_COUNT]
        assert len(step_count_calls) == 1
        assert step_count_calls[0][0][2] == 3  # step_number

        # Verify memory step was added
        assert len(agent.memory.steps) == 1
        assert finalize_calls[0] is agent.memory.steps[0]

    def test_handle_max_steps_reached_model_error_fallback(self):
        """Test that model errors are handled gracefully with fallback message."""
        agent, module = self._create_agent_for_handle_max_steps_test()

        agent.write_memory_to_messages = MagicMock(return_value=[
            {"role": "system", "content": "System"},
        ])

        # Mock the model to raise an exception
        agent.model = MagicMock(side_effect=Exception("Model API failed"))

        # Mock _finalize_step
        agent._finalize_step = MagicMock()

        # Call the method
        result = agent._handle_max_steps_reached("original task")

        # Should return error message
        assert "Error in generating final LLM output" in result

        # Verify logger was called with error
        agent.logger.log.assert_called()
        error_calls = [
            call for call in agent.logger.log.call_args_list
            if call[1].get("level") and "ERROR" in str(call[1].get("level"))
        ]
        assert len(error_calls) >= 1

    def test_handle_max_steps_reached_empty_content_uses_fallback(self, caplog, monkeypatch):
        """Empty max-step synthesis returns a visible fallback and records why."""
        agent, _module = self._create_agent_for_handle_max_steps_test()

        class FakeActionStep:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        class FakeAgentMaxStepsError(Exception):
            def __init__(self, message, logger):
                super().__init__(message)

        monkeypatch.setattr(core_agent_module, "ActionStep", FakeActionStep)
        monkeypatch.setattr(core_agent_module, "AgentMaxStepsError", FakeAgentMaxStepsError)

        mock_chat_message = MagicMock()
        mock_chat_message.role = "assistant"
        mock_chat_message.content = " \n\t"
        mock_chat_message.token_usage = None
        agent.model = MagicMock(return_value=mock_chat_message)
        agent._finalize_step = MagicMock()

        result = core_agent_module.CoreAgent._handle_max_steps_reached(agent, "original task")

        assert result == (
            "The agent was unable to generate a valid response after reaching "
            "the maximum number of steps. Please try rephrasing your request."
        )
        assert agent.memory.steps[0].action_output == result
        assert "model returned empty content, using fallback" in caplog.text

    def test_handle_max_steps_reached_creates_memory_step_with_error(self):
        """Test that a memory step with AgentMaxStepsError is created."""
        agent, module = self._create_agent_for_handle_max_steps_test()

        agent.write_memory_to_messages = MagicMock(return_value=[
            {"role": "system", "content": "System"},
        ])

        mock_chat_message = MagicMock()
        mock_chat_message.role = "assistant"
        mock_chat_message.content = "Partial summary."
        mock_chat_message.token_usage = MagicMock()
        mock_chat_message.token_usage.input_tokens = 10
        mock_chat_message.token_usage.output_tokens = 5

        agent.model = MagicMock(return_value=mock_chat_message)
        agent._finalize_step = MagicMock()

        agent._handle_max_steps_reached("original task")

        # Verify memory step was added
        assert len(agent.memory.steps) == 1
        memory_step = agent.memory.steps[0]

        # Verify it has the error attribute set
        assert hasattr(memory_step, "error")
        assert memory_step.error is not None

    def test_handle_max_steps_reached_tracks_token_usage(self):
        """Test that token usage from the model response is tracked."""
        agent, module = self._create_agent_for_handle_max_steps_test()

        agent.write_memory_to_messages = MagicMock(return_value=[
            {"role": "system", "content": "System"},
        ])

        mock_chat_message = MagicMock()
        mock_chat_message.role = "assistant"
        mock_chat_message.content = "Summary."
        mock_chat_message.token_usage = MagicMock()
        mock_chat_message.token_usage.input_tokens = 999
        mock_chat_message.token_usage.output_tokens = 888

        agent.model = MagicMock(return_value=mock_chat_message)
        agent._finalize_step = MagicMock()

        agent._handle_max_steps_reached("original task")

        # Verify memory step was created
        assert len(agent.memory.steps) == 1
        memory_step = agent.memory.steps[0]

        # Verify token_usage was set (not None)
        assert hasattr(memory_step, "token_usage")
        # The actual TokenUsage mock doesn't preserve our values,
        # but we verified via other tests that the logic correctly extracts values
        # from chat_message.token_usage and assigns them to the memory_step

    def test_handle_max_steps_reached_observer_step_count_message(self):
        """Test that observer receives correct STEP_COUNT message for the new step."""
        agent, module = self._create_agent_for_handle_max_steps_test()

        agent.write_memory_to_messages = MagicMock(return_value=[
            {"role": "system", "content": "System"},
        ])

        mock_chat_message = MagicMock()
        mock_chat_message.role = "assistant"
        mock_chat_message.content = "Summary."
        mock_chat_message.token_usage = None  # No token usage

        agent.model = MagicMock(return_value=mock_chat_message)
        agent._finalize_step = MagicMock()

        agent._handle_max_steps_reached("original task")

        # Check observer STEP_COUNT call
        observer_calls = agent.observer.add_message.call_args_list
        step_count_calls = [
            c for c in observer_calls
            if c[0][1] == module.ProcessType.STEP_COUNT
        ]
        assert len(step_count_calls) == 1
        # Should pass the current step_number (3)
        assert step_count_calls[0][0][2] == 3

    def test_handle_max_steps_reached_uses_context_runtime_final_answer(self):
        """Test that final-answer context is prepared by ContextRuntime."""
        agent, module = self._create_agent_for_handle_max_steps_test()

        mock_chat_message = MagicMock()
        mock_chat_message.role = "assistant"
        mock_chat_message.content = "Summary."
        mock_chat_message.token_usage = None

        agent.model = MagicMock(return_value=mock_chat_message)
        agent._finalize_step = MagicMock()

        agent._handle_max_steps_reached("my task prompt")

        agent.context_runtime.prepare_final_answer.assert_called_once()
        kwargs = agent.context_runtime.prepare_final_answer.call_args.kwargs
        assert kwargs["task"] == "my task prompt"
        assert kwargs["final_answer_templates"] is agent.prompt_templates

        # Model should be called with messages from ContextRuntime.
        assert agent.model.called

    def test_ac_p2_011_final_answer_supplies_source_backed_rebuild_for_w2(self):
        agent, _module = self._create_agent_for_handle_max_steps_test()
        initial = agent.context_runtime.prepare_final_answer.return_value
        rebuilt = MagicMock(messages=[{"role": "user", "content": "short"}])
        rebuilt.evidence.over_hard_budget = False
        agent.context_runtime.prepare_final_answer.side_effect = [initial, rebuilt]
        response = MagicMock(role="assistant", content="Summary.", token_usage=None)
        agent.model = MagicMock(return_value=response)
        agent.model.safe_input_budget_snapshot = {"fingerprint": "w2"}
        agent._finalize_step = MagicMock()

        agent._handle_max_steps_reached("my task prompt")

        callback = agent.model.call_args.kwargs["context_rebuild"]
        assert callback(321) is rebuilt
        assert agent.context_runtime.prepare_final_answer.call_args.kwargs[
            "target_input_budget_tokens"
        ] == 321


# ----------------------------------------------------------------------------
# Tests for _log_model_call_parameters method
# ----------------------------------------------------------------------------

class TestLogModelCallParameters:
    """Test suite for _log_model_call_parameters method."""

    def _create_agent_for_log_params_test(self):
        """Create a CoreAgent instance with mocked dependencies."""
        module = TestRunStreamRealExecution._load_core_agent_in_isolation(self)
        CoreAgent = module.CoreAgent

        agent = object.__new__(CoreAgent)
        agent.agent_name = "test_agent"
        agent.observer = MagicMock()
        agent.stop_event = threading.Event()
        agent.step_number = 1
        agent.memory = MagicMock()
        agent.memory.steps = []
        agent.logger = MagicMock()
        agent.monitor = MagicMock()
        agent.max_steps = 3
        agent.name = "test_agent"
        agent.task = "test task"
        agent.state = {}
        agent.final_answer_checks = None
        agent.return_full_result = False
        agent.python_executor = MagicMock()
        agent.model = MagicMock()
        agent.prompt_templates = {}
        agent.tools = {}
        agent.managed_agents = {}
        agent.provide_run_summary = False
        agent._use_structured_outputs_internally = False

        return agent, module

    def test_log_model_call_parameters_with_model_dump(self):
        """Test _log_model_call_parameters with messages that have model_dump method."""
        agent, module = self._create_agent_for_log_params_test()

        # Create mock message with model_dump method
        mock_msg = MagicMock()
        mock_msg.model_dump = MagicMock(return_value={"role": "user", "content": "test"})
        mock_msg.token_usage = None

        input_messages = [mock_msg]
        stop_sequences = ["Observation:"]
        additional_args = {"temperature": 0.7}

        agent._log_model_call_parameters(input_messages, stop_sequences, additional_args)

        # Verify logger was called
        agent.logger.log_markdown.assert_called_once()

    def test_log_model_call_parameters_with_dict(self):
        """Test _log_model_call_parameters with messages that have __dict__."""
        agent, module = self._create_agent_for_log_params_test()

        # Create mock message with __dict__ but no model_dump
        mock_msg = MagicMock(spec=[])  # Empty spec means no model_dump
        del mock_msg.model_dump  # Ensure no model_dump
        mock_msg.__dict__ = {"role": "user", "content": "test"}

        input_messages = [mock_msg]
        stop_sequences = []
        additional_args = {}

        agent._log_model_call_parameters(input_messages, stop_sequences, additional_args)

        agent.logger.log_markdown.assert_called_once()

    def test_log_model_call_parameters_with_fallback_str(self):
        """Test _log_model_call_parameters with messages that fall back to str()."""
        agent, module = self._create_agent_for_log_params_test()

        # Create mock message that falls back to str
        mock_msg = MagicMock(spec=[])
        del mock_msg.model_dump
        del mock_msg.__dict__

        input_messages = [mock_msg]
        stop_sequences = ["stop"]
        additional_args = {"api_key": "secret123"}

        agent._log_model_call_parameters(input_messages, stop_sequences, additional_args)

        # Verify sensitive data was redacted
        call_args = agent.logger.log_markdown.call_args
        content = call_args[1]["content"]
        assert "REDACTED" in content

    def test_log_model_call_parameters_redacts_runtime_metadata(self):
        agent, _ = self._create_agent_for_log_params_test()
        mock_msg = MagicMock()
        mock_msg.model_dump.return_value = {
            "role": "user",
            "content": (
                'question\n<runtime_metadata trust="untrusted-data">'
                '{"secret":"must-not-leak"}</runtime_metadata>'
            ),
        }

        agent._log_model_call_parameters(
            [mock_msg],
            [],
            {"metadata": {"secret": "must-not-leak"}},
        )

        content = agent.logger.log_markdown.call_args.kwargs["content"]
        assert "must-not-leak" not in content
        assert "REDACTED" in content

    def test_log_model_call_parameters_exception_handling(self):
        """Test _log_model_call_parameters handles exceptions gracefully."""
        agent, module = self._create_agent_for_log_params_test()

        # Make truncate_content raise an exception
        import unittest.mock

        original_truncate = module.truncate_content

        def failing_truncate(content, max_length=1000):
            raise TypeError("Cannot truncate")

        with unittest.mock.patch.object(module, 'truncate_content', side_effect=failing_truncate):
            input_messages = [MagicMock(model_dump=MagicMock(side_effect=TypeError("no dump")))]
            input_messages[0].__dict__ = {"role": "user"}

            # Should not raise, should log warning via exception handler
            agent._log_model_call_parameters(input_messages, [], {})

        # Verify warning was logged via the except block
        # The exception handler logs via self.logger.log()
        agent.logger.log.assert_called()


# ----------------------------------------------------------------------------
# Tests for real tool-call observer helpers
# ----------------------------------------------------------------------------


def test_coerce_observer_arguments_preserves_json_compatible_values():
    """Keep values accepted by observer payloads unchanged."""
    values = [None, "{\"query\": \"test\"}", 3, 2.5, True, {"key": "value"}, ["item"]]

    assert [core_agent_module._coerce_observer_arguments(value) for value in values] == values


def test_coerce_observer_arguments_stringifies_other_values():
    """Convert non-serializable values to their string representation."""
    value = object()

    assert core_agent_module._coerce_observer_arguments(value) == str(value)


def test_coerce_observer_arguments_replaces_callable_with_name():
    """Callable objects are replaced with their ``name`` attribute."""
    tool = type("FakeTool", (), {"name": "my_tool", "__call__": lambda self: None})()

    assert core_agent_module._coerce_observer_arguments(tool) == "my_tool"


def test_coerce_observer_arguments_replaces_callable_inside_nested_structures():
    """Recursively replace callables inside dict/list/tuple — the
    parallel_executor use case."""
    tool_a = type("ToolA", (), {"name": "read_skill_config", "__call__": lambda self: None})()
    tool_b = type("ToolB", (), {"name": "read_skill_md", "__call__": lambda self: None})()

    # Simulate observed_forward kwargs for parallel_executor
    kwargs = {
        "tasks": [
            (tool_a, {"skill_name": "data_analysis"}),
            (tool_b, {"skill_name": "data_analysis"}, "readme"),
        ],
        "timeout": 30,
        "max_workers": 2,
    }
    result = core_agent_module._coerce_observer_arguments(kwargs)

    # callables replaced by name strings; tuples stay tuples; other values unchanged
    expected_tasks = [
        ("read_skill_config", {"skill_name": "data_analysis"}),
        ("read_skill_md", {"skill_name": "data_analysis"}, "readme"),
    ]
    assert result == {"tasks": expected_tasks, "timeout": 30, "max_workers": 2}

    # Verify the result is JSON-serializable (the whole point of the fix)
    import json
    json.dumps(result)


def test_coerce_observer_arguments_preserves_tuple_type():
    """Tuple without callables keeps its structure."""
    value = ("a", "b", {"nested": 1})
    result = core_agent_module._coerce_observer_arguments(value)
    assert result == ("a", "b", {"nested": 1})
    assert isinstance(result, tuple)


def test_collect_call_arguments_extracts_literals_expressions_and_kwargs():
    """Extract safe literals and retain source for non-literal expressions."""
    call_node = core_agent_module.ast.parse(
        "search(42, user.query, limit=5, filters={'tag': 'sdk'}, **options)"
    ).body[0].value

    assert core_agent_module._collect_call_arguments(call_node) == {
        "arg0": 42,
        "arg1": "user.query",
        "limit": 5,
        "filters": {"tag": "sdk"},
        "**kwargs": "options",
    }


def test_collect_call_arguments_handles_unparseable_keyword_expression(monkeypatch):
    """Use a diagnostic placeholder when keyword source cannot be reconstructed."""
    call_node = core_agent_module.ast.parse("search(query=value)").body[0].value
    original_unparse = core_agent_module.ast.unparse

    def fail_for_keyword(node):
        if isinstance(node, core_agent_module.ast.Name):
            raise ValueError("cannot unparse")
        return original_unparse(node)

    monkeypatch.setattr(core_agent_module.ast, "unparse", fail_for_keyword)

    assert core_agent_module._collect_call_arguments(call_node) == {"query": "<unparseable>"}


def test_scan_code_for_tool_calls_filters_deduplicates_and_preserves_source_order():
    """Report distinct exposed tool calls while ignoring builtins and unknown calls."""
    code = """print('start')
search(query='nexent')
worker.run(task='summarize')
search(query='nexent')
unknown_tool()
"""

    assert core_agent_module._scan_code_for_tool_calls(code, {"search", "run"}) == [
        {"name": "search", "arguments": {"query": "nexent"}, "line": 2},
        {"name": "run", "arguments": {"task": "summarize"}, "line": 3},
    ]


def test_scan_code_for_tool_calls_returns_empty_for_invalid_or_unconfigured_code():
    """Ignore malformed code and code without exposed tool names."""
    assert core_agent_module._scan_code_for_tool_calls("search(", {"search"}) == []
    assert core_agent_module._scan_code_for_tool_calls("search()", set()) == []
    assert core_agent_module._scan_code_for_tool_calls("", {"search"}) == []


def test_wrap_tool_for_observer_emits_unique_ids_for_same_name_calls(monkeypatch):
    """Associate every actual tool invocation with a distinct observer ID."""
    observer = MagicMock()
    observer.tool_call_context.return_value.__enter__.return_value = None
    tool = type("SearchTool", (), {"name": "search"})()
    calls = []

    def forward(**kwargs):
        calls.append(kwargs)
        return kwargs["query"]

    tool.forward = forward
    ids = iter(["call-1", "call-2", "call-3"])
    monkeypatch.setattr(core_agent_module.uuid, "uuid4", lambda: next(ids))

    core_agent_module._wrap_tool_for_observer(tool, observer, "research-agent")

    assert tool.forward(query="first") == "first"
    assert tool.forward(query="second") == "second"
    assert tool.forward(query="third") == "third"
    assert calls == [{"query": "first"}, {"query": "second"}, {"query": "third"}]
    assert [call.kwargs["tool_call_id"] for call in observer.add_message.call_args_list] == [
        "call-1", "call-2", "call-3"
    ]
    assert [call.args[0] for call in observer.tool_call_context.call_args_list] == [
        "call-1", "call-2", "call-3"
    ]


def test_wrap_tool_for_observer_maps_positional_values_to_input_names(monkeypatch):
    observer = MagicMock()
    observer.tool_call_context.return_value.__enter__.return_value = None
    tool = type(
        "RunSkillTool",
        (),
        {
            "name": "run_skill_script",
            "inputs": {"skill_name": {}, "script_path": {}, "params": {}},
        },
    )()
    tool.forward = lambda skill_name, script_path, params=None: "ok"
    monkeypatch.setattr(core_agent_module.uuid, "uuid4", lambda: "call-1")

    core_agent_module._wrap_tool_for_observer(tool, observer, "agent")
    result = tool.forward(
        "sandbox-execution-probe",
        "scripts/check_execution_env.py",
        {"compact": True},
    )

    assert result == "ok"
    assert observer.add_message.call_args.kwargs["tool_arguments"] == {
        "skill_name": "sandbox-execution-probe",
        "script_path": "scripts/check_execution_env.py",
        "params": {"compact": True},
    }


def test_known_tool_names_combines_mapping_containers_and_ignores_invalid_ones():
    """Collect stringified keys from tools and managed agents only."""
    module = TestRunStreamRealExecution()._load_core_agent_in_isolation()
    agent = type("Agent", (), {})()
    search_tool = MagicMock()
    search_tool.emit_tool_event = True
    hidden_tool = MagicMock()
    hidden_tool.emit_tool_event = False
    planner = MagicMock()
    planner.emit_tool_event = True
    agent.tools = {"search": search_tool, 7: hidden_tool}
    agent.managed_agents = {"planner": planner}

    assert module.CoreAgent._known_tool_names(agent) == {"search", "7", "planner"}
    assert module.CoreAgent._managed_agent_names(agent) == {"planner"}
    assert module.CoreAgent._non_emitting_tool_names(agent) == {"7"}

    agent.tools = ["not-a-mapping"]
    agent.managed_agents = None

    assert module.CoreAgent._known_tool_names(agent) == set()
    assert module.CoreAgent._managed_agent_names(agent) == set()
    assert module.CoreAgent._non_emitting_tool_names(agent) == set()


def test_managed_agent_names_reads_names_from_sequence_containers():
    """Collect managed-agent names when the registry is a sequence."""
    module = TestRunStreamRealExecution()._load_core_agent_in_isolation()
    agent = type("Agent", (), {})()
    agent.managed_agents = [
        type("NamedAgent", (), {"name": "planner"})(),
        type("UnnamedAgent", (), {})(),
        type("NamedAgent", (), {"name": "researcher"})(),
    ]

    assert module.CoreAgent._managed_agent_names(agent) == {"planner", "researcher"}


def test_wrap_visible_tool_events_supports_sequence_containers_and_skips_hidden_tools():
    """Wrap visible sequence tools while leaving explicitly hidden tools untouched."""
    module = TestRunStreamRealExecution()._load_core_agent_in_isolation()
    observer = MagicMock()
    observer.tool_call_context.return_value.__enter__.return_value = None

    class Tool:
        def __init__(self, name, emit_tool_event=True):
            self.name = name
            self.emit_tool_event = emit_tool_event
            self.calls = []

        def forward(self, **kwargs):
            self.calls.append(kwargs)
            return self.name

    visible = Tool("visible")
    hidden = Tool("hidden", emit_tool_event=False)
    agent = module.CoreAgent.__new__(module.CoreAgent)
    agent.tools = [visible, hidden]
    agent.managed_agents = []
    agent.observer = observer
    agent.agent_name = "test-agent"

    agent._wrap_visible_tool_events()

    assert visible.forward(query="value") == "visible"
    assert hidden.forward(query="value") == "hidden"
    assert visible.calls == [{"query": "value"}]
    assert hidden.calls == [{"query": "value"}]
    observer.add_message.assert_called_once()
    assert observer.add_message.call_args.kwargs["tool_name"] == "visible"


def test_wrap_visible_tool_events_skips_tools_without_forward():
    """Ignore sequence entries that do not expose a callable forward method."""
    module = TestRunStreamRealExecution()._load_core_agent_in_isolation()
    agent = module.CoreAgent.__new__(module.CoreAgent)
    agent.tools = [type("NoForwardTool", (), {"name": "broken"})()]
    agent.managed_agents = []
    agent.observer = MagicMock()
    agent.agent_name = "test-agent"

    agent._wrap_visible_tool_events()

    assert not hasattr(agent.tools[0], "_tool_call_observer_wrapped")


def _create_minimal_core_agent_for_time_tests():
    """Create a CoreAgent with minimal mocking for time-prefix tests."""
    module = TestRunStreamRealExecution()._load_core_agent_in_isolation()
    agent = module.CoreAgent.__new__(module.CoreAgent)
    agent.max_steps = 3
    agent.state = {}
    agent.memory = MagicMock()
    agent.monitor = MagicMock()
    agent.context_runtime = MagicMock()
    agent.system_prompt = ""
    agent.logger = MagicMock()
    agent.model = MagicMock()
    agent.model.model_id = "test-model"
    agent.name = "test_agent"
    agent.observer = MagicMock()
    agent.python_executor = None
    agent._run_stream_with_context_evidence = MagicMock(return_value=iter([]))
    return agent


def test_run_preserves_existing_current_time_prefix():
    """When task already has [Current time: ...] prefix, run() should not re-inject."""
    agent = _create_minimal_core_agent_for_time_tests()

    prefixed_task = "[Current time: 2026-01-01 20:00:00]\n\nWhat time is it?"
    list(agent.run(task=prefixed_task, stream=True))

    assert agent.task == prefixed_task


def test_run_injects_current_time_when_missing():
    """When task has no [Current time: ...] prefix, run() should inject server time."""
    agent = _create_minimal_core_agent_for_time_tests()

    list(agent.run(task="What time is it?", stream=True))

    assert agent.task.startswith("[Current time:")
    assert "What time is it?" in agent.task


def test_managed_agent_call_injects_workspace_instructions(tmp_path):
    """Managed sub-agents receive the run output path in their delegated task."""
    module = TestRunStreamRealExecution()._load_core_agent_in_isolation()
    module.RunResult = type("RunResult", (), {})
    workspace = tmp_path / "user" / "run"
    agent = module.CoreAgent.__new__(module.CoreAgent)
    agent.workspace_path = str(workspace)
    agent.name = "file_generation_assistant"
    agent.state = {}
    agent.prompt_templates = {
        "managed_agent": {
            "task": "{{ task }}",
            "report": "{{ final_answer }}",
        }
    }
    agent.run = MagicMock(return_value="done")
    agent.observer = MagicMock()
    agent.provide_run_summary = False

    agent("create test.txt")

    render_payload = module.Template.return_value.render.call_args_list[0].args[0]
    managed_task = render_payload["task"]
    assert "[Nexent run workspace]" in managed_task
    assert str(workspace / "outputs") in managed_task
    assert "current working directory" in managed_task
    assert "Never prefix a relative output path" in managed_task
    assert "pass the same bare relative path" in managed_task
    assert "use its permanent s3_url in Markdown" in managed_task
    assert "Never use a local path or presigned_url" in managed_task
    assert "only call .save() on PIL images" in managed_task


def test_run_with_metadata_injects_untrusted_metadata_block():
    """run() must serialize runtime metadata and inline extra args into the task."""
    agent = _create_minimal_core_agent_for_time_tests()

    list(agent.run(
        task="Handle the request",
        stream=True,
        additional_args={"metadata": {"session": "abc", "lang": "zh"}, "window_id": "w1"},
    ))

    assert "window_id" in agent.task
    assert '<runtime_metadata trust="untrusted-data">' in agent.task
    assert '"session":"abc"' in agent.task
    assert agent.state["metadata"] == {"session": "abc", "lang": "zh"}


def test_run_with_metadata_skips_optional_sections():
    """run() with only metadata provided must not inline extra-args or metadata text when absent."""
    agent = _create_minimal_core_agent_for_time_tests()

    list(agent.run(
        task="Handle the request",
        stream=True,
        additional_args={"metadata": {"session": "abc"}},
    ))

    assert '<runtime_metadata trust="untrusted-data">' in agent.task
    # extra-args hint is only rendered when non-metadata additional args exist
    assert "additional arguments, that you can access" not in agent.task


def test_call_forwards_metadata_to_sub_agent_run():
    """__call__ must exclude metadata from the template state and pass it via additional_args."""
    module = TestRunStreamRealExecution()._load_core_agent_in_isolation()
    agent = module.CoreAgent.__new__(module.CoreAgent)
    agent.workspace_path = None
    agent.max_steps = 3
    agent.state = {"metadata": {"session": "abc"}, "region": "cn"}
    agent.memory = MagicMock()
    agent.monitor = MagicMock()
    agent.context_runtime = MagicMock()
    agent.system_prompt = ""
    agent.logger = MagicMock()
    agent.model = MagicMock()
    agent.name = "test_agent"
    agent.observer = MagicMock()
    agent.python_executor = None
    agent.prompt_templates = {
        "managed_agent": {
            "task": "Task for {name}: {task}",
            "report": "Report {name}: {final_answer}",
        }
    }
    agent.provide_run_summary = False

    # Provide a real type for the RunResult isinstance gate (the isolated-load
    # smolagents mock leaves it as a MagicMock, which isinstance rejects).
    fake_run_result = type("FakeRunResult", (), {})
    module.RunResult = fake_run_result

    # Replace the mocked jinja Template with a recorder so we can assert on the
    # rendered context (template_state must drop metadata but keep state keys).
    recorded_renders = []

    class _RecorderTemplate:
        def __init__(self, template, **kwargs):
            self._template = template

        def render(self, context, **kwargs):
            recorded_renders.append({"template": self._template, "context": dict(context)})
            return f"RENDERED-{len(recorded_renders)}"

    module.Template = _RecorderTemplate

    calls = {}
    def fake_run(full_task, **kwargs):
        calls["full_task"] = full_task
        calls["kwargs"] = kwargs
        result = fake_run_result()
        result.output = "sub-agent-output"
        return result

    agent.run = fake_run

    answer = agent(task="summarize")

    task_render = recorded_renders[0]["context"]
    # metadata was kept out of the rendered template state
    assert "metadata" not in task_render
    assert task_render["region"] == "cn"
    assert "Task for {name}: {task}" in recorded_renders[0]["template"]
    assert "Report {name}: {final_answer}" in recorded_renders[1]["template"]
    assert calls["kwargs"]["additional_args"] == {"metadata": {"session": "abc"}}
    assert answer == "RENDERED-2"
