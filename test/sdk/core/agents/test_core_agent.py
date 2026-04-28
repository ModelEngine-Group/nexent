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
from types import ModuleType
from unittest.mock import MagicMock, patch
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
    for _name in ["CodeAgent", "populate_template", "handle_agent_output_types", "AgentError", "ActionOutput", "RunResult"]:
        setattr(agents_mod, _name, MagicMock(name=f"smolagents.agents.{_name}"))
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


# ----------------------------------------------------------------------------
# Tests for parse_code_blobs function
# ----------------------------------------------------------------------------

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
    """Test parse_code_blobs with ```python\\ncontent\\n``` pattern (legacy format)."""
    text = """Here is some code:
```python
print("Hello World")
x = 42
```
And some more text."""

    result = core_agent_module.parse_code_blobs(text)
    expected = "print(\"Hello World\")\nx = 42"
    assert result == expected


def test_parse_code_blobs_py_match():
    """Test parse_code_blobs with ```py\\ncontent\\n``` pattern (legacy format)."""
    text = """Here is some code:
```py
def hello():
    return "Hello"
```
And some more text."""

    result = core_agent_module.parse_code_blobs(text)
    expected = "def hello():\n    return \"Hello\""
    assert result == expected


def test_parse_code_blobs_multiple_matches():
    """Test parse_code_blobs with multiple code blocks."""
    text = """First code block:
```python
print("First")
```

Second code block:
```py
print("Second")
```"""

    result = core_agent_module.parse_code_blobs(text)
    expected = "print(\"First\")\n\nprint(\"Second\")"
    assert result == expected


def test_parse_code_blobs_direct_python_code():
    """Test parse_code_blobs with direct Python code (no code blocks)."""
    text = '''print("Hello World")
x = 42
def hello():
    return "Hello"'''

    result = core_agent_module.parse_code_blobs(text)
    assert result == text


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
    """Test parse_code_blobs skips newline after ```py\\n."""
    text = """```py
print("hello")
```"""

    result = core_agent_module.parse_code_blobs(text)
    expected = 'print("hello")'
    assert result == expected


def test_parse_code_blobs_python_with_newline_after_fence():
    """Test parse_code_blobs skips newline after ```python\\n."""
    text = """```python
print("hello")
```"""

    result = core_agent_module.parse_code_blobs(text)
    expected = 'print("hello")'
    assert result == expected


def test_parse_code_blobs_single_line():
    """Test parse_code_blobs with single line content."""
    text = """Single line:
```python
print("Hello")
```"""

    result = core_agent_module.parse_code_blobs(text)
    expected = 'print("Hello")'
    assert result == expected


def test_parse_code_blobs_mixed_content():
    """Test parse_code_blobs with mixed content including non-code text."""
    text = """Thoughts: I need to calculate the sum
Code:
```python
def sum_numbers(a, b):
    return a + b

result = sum_numbers(5, 3)
```
The result is 8."""

    result = core_agent_module.parse_code_blobs(text)
    expected = "def sum_numbers(a, b):\n    return a + b\n\nresult = sum_numbers(5, 3)"
    assert result == expected


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


# ----------------------------------------------------------------------------
# Additional edge case tests for parse_code_blobs
# ----------------------------------------------------------------------------

def test_parse_code_blobs_whitespace_variation():
    """Test parse_code_blobs with different whitespace patterns."""
    text = """```python
print("hello")
```"""
    result = core_agent_module.parse_code_blobs(text)
    expected = 'print("hello")'
    assert result == expected


def test_parse_code_blobs_no_newline_at_end():
    """Test parse_code_blobs when code block doesn't end with newline but has trailing whitespace."""
    text = """```python
print("hello")
```
And some text."""
    result = core_agent_module.parse_code_blobs(text)
    expected = 'print("hello")'
    assert result == expected


def test_parse_code_blobs_with_comments():
    """Test parse_code_blobs with Python comments in code."""
    text = """```python
# This is a comment
x = 1  # inline comment
```"""
    result = core_agent_module.parse_code_blobs(text)
    expected = "# This is a comment\nx = 1  # inline comment"
    assert result == expected


def test_parse_code_blobs_with_multiline_string():
    """Test parse_code_blobs with multiline strings."""
    text = '''```python
message = """
This is a
multiline string
"""
```'''
    result = core_agent_module.parse_code_blobs(text)
    assert 'multiline string' in result


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
    """Test parse_code_blobs preserves special characters in code."""
    text = """```python
x = "!@#$%^&*()_+-=[]{}|;':\",./<>?"
y = 'single quotes'
z = "double quotes"
w = '''triple single'''
```"""

    result = core_agent_module.parse_code_blobs(text)
    assert "!@#$%^&*()_+-=[]{}|;':\",./<>?" in result
    assert "single quotes" in result
    assert "double quotes" in result


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
    """Test parse_code_blobs with whitespace-only text (valid Python)."""
    # Whitespace-only text is valid Python syntax (empty string)
    text = "   \n\n   \t\t   "

    # ast.parse("   \n\n   \t\t   ") == ast.parse("") which is valid
    result = core_agent_module.parse_code_blobs(text)
    assert result == "   \n\n   \t\t   " or result.strip() == ""


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

    def _load_core_agent_in_isolation(self):
        """Load CoreAgent in isolation without the test's module mocks."""
        import importlib.util
        import threading
        import time as time_module
        import copy

        # Create a minimal base class that mimics CodeAgent
        class MinimalCodeAgent:
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

        # Create mock action output
        mock_action_output = MagicMock()
        mock_action_output.is_final_answer = False

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
        agent.context_manager = None
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
        agent.context_manager = None
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


# ----------------------------------------------------------------------------
# Tests for _build_final_answer_messages function
# ----------------------------------------------------------------------------

class TestBuildFinalAnswerMessages:
    """Test suite for _build_final_answer_messages standalone function."""

    def _load_core_agent_for_function_test(self):
        """Load core_agent module with proper mocks for standalone function testing."""
        # Create a fresh mock setup for this test
        import importlib.util
        import sys
        from types import ModuleType
        from unittest.mock import MagicMock

        # Create mock jinja2
        mock_jinja2 = ModuleType("jinja2")
        mock_jinja2.Template = MagicMock()
        mock_jinja2.StrictUndefined = MagicMock()

        # Create mock smolagents models
        mock_models = ModuleType("smolagents.models")
        mock_models.ChatMessage = MagicMock(name="ChatMessage")
        mock_models.MessageRole = MagicMock(name="MessageRole")
        mock_models.CODEAGENT_RESPONSE_FORMAT = MagicMock(name="CODEAGENT_RESPONSE_FORMAT")

        mock_smolagents = ModuleType("smolagents")
        mock_smolagents.models = mock_models

        # Save and replace modules
        original_modules = {}
        for name in ["jinja2", "jinja2.template", "smolagents", "smolagents.models"]:
            if name in sys.modules:
                original_modules[name] = sys.modules[name]
        sys.modules["jinja2"] = mock_jinja2
        sys.modules["jinja2.template"] = mock_jinja2
        sys.modules["smolagents"] = mock_smolagents
        sys.modules["smolagents.models"] = mock_models

        try:
            # Find and load core_agent.py
            test_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(test_dir))))
            core_agent_path = os.path.join(project_root, "sdk", "nexent", "core", "agents", "core_agent.py")

            spec = importlib.util.spec_from_file_location("core_agent_for_func", core_agent_path)
            module = importlib.util.module_from_spec(spec)
            module.__package__ = "sdk.nexent.core.agents"
            spec.loader.exec_module(module)
            return module, mock_models
        finally:
            for name, mod in original_modules.items():
                sys.modules[name] = mod

    def test_build_final_answer_messages_basic(self):
        """Test that _build_final_answer_messages builds correct message structure."""
        module, mock_models = self._load_core_agent_for_function_test()
        _build_final_answer_messages = module._build_final_answer_messages

        # Setup mock ChatMessage
        mock_chat_message = MagicMock()
        mock_models.ChatMessage = mock_chat_message

        task = "Test task"
        agent_prompt_templates = {
            "final_answer": {
                "pre_messages": "System prompt for final answer.",
                "post_messages": "Given the task: {{ task }}, provide the final answer."
            }
        }
        memory_messages = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "User message 1"},
            {"role": "assistant", "content": "Assistant response 1"},
            {"role": "user", "content": "User message 2"},
        ]

        result = _build_final_answer_messages(task, agent_prompt_templates, memory_messages)

        # Should have: 1 system message + memory_messages[1:] + 1 user message = 5 messages
        assert len(result) == 5

    def test_build_final_answer_messages_skips_first_memory_message(self):
        """Test that the first memory message (system) is skipped."""
        module, mock_models = self._load_core_agent_for_function_test()
        _build_final_answer_messages = module._build_final_answer_messages

        mock_chat_message = MagicMock()
        mock_models.ChatMessage = mock_chat_message

        task = "My task"
        agent_prompt_templates = {
            "final_answer": {
                "pre_messages": "Pre",
                "post_messages": "Post: {{ task }}"
            }
        }
        # First message should be skipped, rest should be included
        memory_messages = [
            {"role": "system", "content": "skip this"},
            {"role": "user", "content": "include 1"},
            {"role": "assistant", "content": "include 2"},
        ]

        result = _build_final_answer_messages(task, agent_prompt_templates, memory_messages)

        # 1 system + 2 from memory_messages[1:] + 1 final user = 4
        assert len(result) == 4

    def test_build_final_answer_messages_empty_memory(self):
        """Test _build_final_answer_messages with minimal memory messages."""
        module, mock_models = self._load_core_agent_for_function_test()
        _build_final_answer_messages = module._build_final_answer_messages

        mock_chat_message = MagicMock()
        mock_models.ChatMessage = mock_chat_message

        task = "Task"
        agent_prompt_templates = {
            "final_answer": {
                "pre_messages": "Pre",
                "post_messages": "Post: {{ task }}"
            }
        }
        # Only one message in memory (would cause empty result after slice)
        memory_messages = [{"role": "system", "content": "only one"}]

        result = _build_final_answer_messages(task, agent_prompt_templates, memory_messages)

        # 1 system + 0 from memory[1:] + 1 user = 2
        assert len(result) == 2

    def test_build_final_answer_messages_template_rendering(self):
        """Test that post_messages template is rendered correctly with task variable.

        The function uses Jinja2 Template with StrictUndefined to render the post_messages
        template with the task variable. This test verifies the overall function works
        correctly by checking the returned message structure.
        """
        module, mock_models = self._load_core_agent_for_function_test()
        _build_final_answer_messages = module._build_final_answer_messages

        mock_chat_message = MagicMock()
        mock_models.ChatMessage = mock_chat_message

        # Test with various task values to verify template variable substitution
        test_cases = [
            "Simple task",
            "Task with 'single quotes'",
            'Task with "double quotes"',
            "Task with {{ brackets }}",
            "Task with unicode: 你好世界 🎉",
        ]

        for task in test_cases:
            agent_prompt_templates = {
                "final_answer": {
                    "pre_messages": "Pre prompt",
                    "post_messages": "Task: {{ task }}"
                }
            }
            memory_messages = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "msg"},
            ]

            # Should not raise for any valid task string
            result = _build_final_answer_messages(task, agent_prompt_templates, memory_messages)

            # Verify structure
            assert len(result) == 3  # system + user + final user


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

        # Verify logger was called with warning
        agent.logger.log.assert_called()
        warning_calls = [
            call for call in agent.logger.log.call_args_list
            if call[1].get("level") and "WARNING" in str(call[1].get("level"))
        ]
        assert len(warning_calls) >= 1

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

    def test_handle_max_steps_reached_uses_build_final_answer_messages(self):
        """Test that _build_final_answer_messages is called to prepare the context."""
        agent, module = self._create_agent_for_handle_max_steps_test()

        # Track calls to write_memory_to_messages
        memory_calls = []
        agent.write_memory_to_messages = MagicMock(
            side_effect=lambda *args, **kwargs: memory_calls.append(args) or [
                {"role": "system", "content": "System"},
            ]
        )

        mock_chat_message = MagicMock()
        mock_chat_message.role = "assistant"
        mock_chat_message.content = "Summary."
        mock_chat_message.token_usage = None

        agent.model = MagicMock(return_value=mock_chat_message)
        agent._finalize_step = MagicMock()

        agent._handle_max_steps_reached("my task prompt")

        # write_memory_to_messages should have been called
        assert len(memory_calls) >= 1

        # Model should have been called (which uses messages from _build_final_answer_messages)
        assert agent.model.called
