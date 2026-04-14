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
    for _name in ["ActionStep", "ToolCall", "TaskStep", "SystemPromptStep", "PlanningStep", "FinalAnswerStep"]:
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
    for _name in ["ActionStep", "TaskStep", "AgentText", "handle_agent_output_types"]:
        setattr(mock_smolagents, _name, MagicMock(name=f"smolagents.{_name}"))
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
    sys.modules["sdk.nexent"] = ModuleType("sdk.nexent")
    sys.modules["sdk.nexent.core"] = ModuleType("sdk.nexent.core")
    sys.modules["sdk.nexent.core.agents"] = ModuleType("sdk.nexent.core.agents")
    sys.modules["sdk.nexent.core.utils"] = _module_mocks["sdk.nexent.core.utils.observer"]

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
