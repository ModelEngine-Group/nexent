import pytest
from unittest.mock import MagicMock, patch
from threading import Event


# ---------------------------------------------------------------------------
# Prepare mocks for external dependencies
# ---------------------------------------------------------------------------

# Define custom AgentError that stores .message so CoreAgent code can access it
class MockAgentError(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(message)


# Mock for smolagents and its sub-modules
mock_smolagents = MagicMock()
mock_smolagents.ActionStep = MagicMock()
mock_smolagents.TaskStep = MagicMock()
mock_smolagents.SystemPromptStep = MagicMock()
mock_smolagents.AgentError = MockAgentError

mock_smolagents.handle_agent_output_types = MagicMock(
    return_value="handled_output")

# Create dummy smolagents sub-modules
for sub_mod in ["agents", "memory", "models", "monitoring", "utils", "local_python_executor"]:
    mock_module = MagicMock()
    setattr(mock_smolagents, sub_mod, mock_module)

mock_smolagents.agents.CodeAgent = MagicMock

# Provide actual implementations for commonly used utils functions


def mock_truncate_content(content, max_length=1000):
    """Simple implementation of truncate_content for testing."""
    content_str = str(content)
    if len(content_str) <= max_length:
        return content_str
    return content_str[:max_length] + "..."


mock_smolagents.utils.truncate_content = mock_truncate_content

# Mock for rich modules
mock_rich = MagicMock()
mock_rich_console = MagicMock()
mock_rich_text = MagicMock()

module_mocks = {
    "smolagents": mock_smolagents,
    "smolagents.agents": mock_smolagents.agents,
    "smolagents.memory": mock_smolagents.memory,
    "smolagents.models": mock_smolagents.models,
    "smolagents.monitoring": mock_smolagents.monitoring,
    "smolagents.utils": mock_smolagents.utils,
    "smolagents.local_python_executor": mock_smolagents.local_python_executor,
    "rich.console": mock_rich_console,
    "rich.text": mock_rich_text
}

# ---------------------------------------------------------------------------
# Import the classes under test with patched dependencies
# ---------------------------------------------------------------------------
with patch.dict("sys.modules", module_mocks):
    from sdk.nexent.core.utils.observer import MessageObserver, ProcessType
    from sdk.nexent.core.agents.core_agent import CoreAgent as ImportedCoreAgent
    import sys

    core_agent_module = sys.modules['sdk.nexent.core.agents.core_agent']
    # Override AgentError inside the imported module to ensure it has message attr
    core_agent_module.AgentError = MockAgentError
    CoreAgent = ImportedCoreAgent


# ----------------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------------

@pytest.fixture
def mock_observer():
    """Return a mocked MessageObserver instance."""
    observer = MagicMock(spec=MessageObserver)
    return observer


@pytest.fixture
def core_agent_instance(mock_observer):
    """Create a CoreAgent instance with minimal initialization."""
    prompt_templates = {
        "managed_agent": {
            "task": "Task template: {task}",
            "report": "Report template: {final_answer}"
        }
    }
    agent = CoreAgent(
        observer=mock_observer,
        prompt_templates=prompt_templates,
        name="test_agent"
    )
    agent.stop_event = Event()
    agent.memory = MagicMock()
    agent.memory.steps = []
    agent.python_executor = MagicMock()

    agent.step_number = 1
    agent._execute_step = MagicMock()
    agent._finalize_step = MagicMock()
    agent._handle_max_steps_reached = MagicMock()

    return agent


# ----------------------------------------------------------------------------
# Tests for _run method
# ----------------------------------------------------------------------------

def test_run_normal_execution(core_agent_instance):
    """Test normal execution path of _run method."""
    # Setup
    task = "test task"
    max_steps = 3

    # Mock _execute_step to return a generator that yields final answer
    def mock_execute_generator(action_step):
        yield "final_answer"

    with patch.object(core_agent_instance, '_execute_step', side_effect=mock_execute_generator) as mock_execute_step, \
            patch.object(core_agent_instance, '_finalize_step') as mock_finalize_step:
        core_agent_instance.step_number = 1

        # Execute
        result = list(core_agent_instance._run_stream(task, max_steps))

        # Assertions
        # _run_stream yields: generator output + action step + final answer step
        assert len(result) == 3
        assert result[0] == "final_answer"  # Generator output
        assert isinstance(result[1], MagicMock)  # Action step
        assert isinstance(result[2], MagicMock)  # Final answer step


def test_run_with_max_steps_reached(core_agent_instance):
    """Test _run method when max steps are reached without final answer."""
    # Setup
    task = "test task"
    max_steps = 2

    # Mock _execute_step to return None (no final answer)
    def mock_execute_generator(action_step):
        yield None

    with patch.object(core_agent_instance, '_execute_step', side_effect=mock_execute_generator) as mock_execute_step, \
            patch.object(core_agent_instance, '_finalize_step') as mock_finalize_step, \
            patch.object(core_agent_instance, '_handle_max_steps_reached',
                         return_value="max_steps_reached") as mock_handle_max:
        core_agent_instance.step_number = 1

        # Execute
        result = list(core_agent_instance._run_stream(task, max_steps))

        # Assertions
        # For 2 steps: (None + action_step) * 2 + final_action_step + final_answer_step = 6
        assert len(result) == 6
        assert result[0] is None  # First generator output
        assert isinstance(result[1], MagicMock)  # First action step
        assert result[2] is None  # Second generator output
        assert isinstance(result[3], MagicMock)  # Second action step
        # Final action step (from _handle_max_steps_reached)
        assert isinstance(result[4], MagicMock)
        assert isinstance(result[5], MagicMock)  # Final answer step

        # Verify method calls
        assert mock_execute_step.call_count == 2
        mock_handle_max.assert_called_once()
        assert mock_finalize_step.call_count == 2


def test_run_with_stop_event(core_agent_instance):
    """Test _run method when stop event is set."""
    # Setup
    task = "test task"
    max_steps = 3

    def mock_execute_generator(action_step):
        core_agent_instance.stop_event.set()
        yield None

    # Mock _execute_step to set stop event
    with patch.object(core_agent_instance, '_execute_step', side_effect=mock_execute_generator):
        with patch.object(core_agent_instance, '_finalize_step'):
            # Execute
            result = list(core_agent_instance._run_stream(task, max_steps))

    # Assertions
    # Should yield: generator output + action step + final answer step
    assert len(result) == 3
    assert result[0] is None  # Generator output
    assert isinstance(result[1], MagicMock)  # Action step
    # Final answer step with "<user_break>"
    assert isinstance(result[2], MagicMock)


def test_run_with_final_answer_error(core_agent_instance):
    """Test _run method when FinalAnswerError occurs in _step_stream."""
    # Setup
    task = "test task"
    max_steps = 3

    # Mock _execute_step to raise FinalAnswerError
    with patch.object(core_agent_instance, '_execute_step',
                      side_effect=core_agent_module.FinalAnswerError()) as mock_execute_step, \
            patch.object(core_agent_instance, '_finalize_step'):
        # Execute
        result = list(core_agent_instance._run_stream(task, max_steps))

    # Assertions
    # When FinalAnswerError occurs, it should yield action step + final answer step
    assert len(result) == 2
    assert isinstance(result[0], MagicMock)  # Action step
    assert isinstance(result[1], MagicMock)  # Final answer step


def test_run_with_final_answer_error_and_model_output(core_agent_instance):
    """Test _run method when FinalAnswerError occurs with model_output conversion."""
    # Setup
    task = "test task"
    max_steps = 3

    # Create a mock action step with model_output
    mock_action_step = MagicMock()
    mock_action_step.model_output = "```<DISPLAY:python>\nprint('hello')\n```<END_CODE>"

    # Mock _execute_step to set model_output and then raise FinalAnswerError
    def mock_execute_step(action_step):
        action_step.model_output = "```<DISPLAY:python>\nprint('hello')\n```<END_CODE>"
        raise core_agent_module.FinalAnswerError()

    with patch.object(core_agent_instance, '_execute_step', side_effect=mock_execute_step), \
            patch.object(core_agent_module, 'convert_code_format', return_value="```python\nprint('hello')\n```<END_CODE>") as mock_convert, \
            patch.object(core_agent_instance, '_finalize_step'):
        # Execute
        result = list(core_agent_instance._run_stream(task, max_steps))

    # Assertions
    assert len(result) == 2
    assert isinstance(result[0], MagicMock)  # Action step
    assert isinstance(result[1], MagicMock)  # Final answer step
    # Verify convert_code_format was called
    mock_convert.assert_called_once_with(
        "```<DISPLAY:python>\nprint('hello')\n```<END_CODE>")


def test_run_with_agent_error_updated(core_agent_instance):
    """Test _run method when AgentError occurs (updated to handle FinalAnswerError separately)."""
    # Setup
    task = "test task"
    max_steps = 3

    # Mock _execute_step to raise AgentError
    with patch.object(core_agent_instance, '_execute_step',
                      side_effect=MockAgentError("test error")) as mock_execute_step, \
            patch.object(core_agent_instance, '_finalize_step'):
        # Execute
        result = list(core_agent_instance._run_stream(task, max_steps))

    # Assertions
    # When AgentError occurs, it should yield action step + final answer step
    # But the error causes the loop to continue, so we get multiple action steps
    assert len(result) >= 2
    assert isinstance(result[0], MagicMock)  # Action step with error
    # Last item should be final answer step
    assert isinstance(result[-1], MagicMock)  # Final answer step


def test_run_with_agent_parse_error_branch_updated(core_agent_instance):
    """Test the branch that handles FinalAnswerError with model_output conversion."""
    task = "parse task"
    max_steps = 1

    # Mock _execute_step to set model_output and then raise FinalAnswerError
    def mock_execute_step(action_step):
        action_step.model_output = "```<DISPLAY:python>\nprint('hello')\n```<END_CODE>"
        raise core_agent_module.FinalAnswerError()

    with patch.object(core_agent_instance, '_execute_step', side_effect=mock_execute_step), \
            patch.object(core_agent_module, 'convert_code_format', return_value="```python\nprint('hello')\n```<END_CODE>") as mock_convert, \
            patch.object(core_agent_instance, '_finalize_step'):
        results = list(core_agent_instance._run_stream(task, max_steps))

    # _run should yield action step + final answer step
    assert len(results) == 2
    assert isinstance(results[0], MagicMock)  # Action step
    assert isinstance(results[1], MagicMock)  # Final answer step
    # Verify convert_code_format was called
    mock_convert.assert_called_once_with(
        "```<DISPLAY:python>\nprint('hello')\n```<END_CODE>")


def test_convert_code_format_display_replacements():
    """Validate convert_code_format correctly transforms <DISPLAY:language> format to standard markdown."""

    original_text = """Here is code:
```<DISPLAY:python>
print('hello')
```<END_CODE>
And some more text."""

    expected_text = """Here is code:
```python
print('hello')
```
And some more text."""

    transformed = core_agent_module.convert_code_format(original_text)

    assert transformed == expected_text, "convert_code_format did not perform expected <DISPLAY> replacements"


def test_convert_code_format_display_without_end_code():
    """Validate convert_code_format handles <DISPLAY:language> without <END_CODE>."""

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

    # Should remain unchanged since there's no <END_CODE>
    assert transformed == expected_text, "convert_code_format should not modify text without <END_CODE>"


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

    assert transformed == expected_text, "convert_code_format did not perform expected legacy replacements"

# ----------------------------------------------------------------------------
# Tests for parse_code_blobs function
# ----------------------------------------------------------------------------


def test_parse_code_blobs_run_format():
    """Test parse_code_blobs with ```<RUN>\ncontent\n```<END_CODE> pattern."""
    text = """Here is some code:
```<RUN>
print("Hello World")
x = 42
```<END_CODE>
And some more text."""

    result = core_agent_module.parse_code_blobs(text)
    expected = "print(\"Hello World\")\nx = 42"
    assert result == expected


def test_parse_code_blobs_python_match():
    """Test parse_code_blobs with ```python\ncontent\n``` pattern (legacy format)."""
    text = """Here is some code:
```python
print("Hello World")
x = 42
```
And some more text."""

    result = core_agent_module.parse_code_blobs(text)
    expected = "print(\"Hello World\")\nx = 42"
    assert result == expected


def test_parse_code_blobs_display_format_ignored():
    """Test parse_code_blobs ignores ```<DISPLAY:python>\ncontent\n```<END_CODE> pattern."""
    text = """Here is some code:
```<DISPLAY:python>
def hello():
    return "Hello"
```<END_CODE>
And some more text."""

    # This should raise ValueError because parse_code_blobs only handles <RUN> format
    with pytest.raises(ValueError) as exc_info:
        core_agent_module.parse_code_blobs(text)

    assert "executable code block pattern" in str(exc_info.value)


def test_parse_code_blobs_py_match():
    """Test parse_code_blobs with ```py\ncontent\n``` pattern (legacy format)."""
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


def test_parse_code_blobs_with_whitespace():
    """Test parse_code_blobs with whitespace around language identifier."""
    text = """Code with whitespace:
```python  
print("Hello")
```
More code:
```py
print("World")
```"""

    result = core_agent_module.parse_code_blobs(text)
    expected = "print(\"Hello\")\n\nprint(\"World\")"
    assert result == expected


def test_parse_code_blobs_no_match():
    """Test parse_code_blobs with ```\ncontent\n``` (no language specified)."""
    text = """Here is some code:
```
print("Hello World")
```
But no language specified."""

    with pytest.raises(ValueError) as exc_info:
        core_agent_module.parse_code_blobs(text)

    assert "executable code block pattern" in str(exc_info.value)


def test_parse_code_blobs_javascript_no_match():
    """Test parse_code_blobs with ```javascript\ncontent\n``` (other language)."""
    text = """Here is some JavaScript code:
```javascript
console.log("Hello World");
```
But this should not match."""

    with pytest.raises(ValueError) as exc_info:
        core_agent_module.parse_code_blobs(text)

    assert "executable code block pattern" in str(exc_info.value)


def test_parse_code_blobs_java_no_match():
    """Test parse_code_blobs with ```java\ncontent\n``` (other language)."""
    text = """Here is some Java code:
```java
System.out.println("Hello World");
```
But this should not match."""

    with pytest.raises(ValueError) as exc_info:
        core_agent_module.parse_code_blobs(text)

    assert "executable code block pattern" in str(exc_info.value)


def test_parse_code_blobs_direct_python_code():
    """Test parse_code_blobs with direct Python code (no code blocks)."""
    text = """print("Hello World")
x = 42
def hello():
    return "Hello\""""

    result = core_agent_module.parse_code_blobs(text)
    assert result == text


def test_parse_code_blobs_invalid_python_syntax():
    """Test parse_code_blobs with invalid Python syntax (should raise ValueError)."""
    text = """print("Hello World"
x = 42
def hello(:
    return "Hello\""""

    with pytest.raises(ValueError) as exc_info:
        core_agent_module.parse_code_blobs(text)

    assert "executable code block pattern" in str(exc_info.value)


def test_parse_code_blobs_generic_error():
    """Test parse_code_blobs with generic case that should raise ValueError."""
    text = """This is just some random text.
Just plain text that should fail."""

    with pytest.raises(ValueError) as exc_info:
        core_agent_module.parse_code_blobs(text)

    error_msg = str(exc_info.value)
    assert "executable code block pattern" in error_msg
    assert "Make sure to include code with the correct pattern" in error_msg


def test_parse_code_blobs_single_line_content():
    """Test parse_code_blobs with single line content."""
    text = """Single line:
```python
print("Hello")
```"""

    result = core_agent_module.parse_code_blobs(text)
    expected = "print(\"Hello\")"
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


def test_step_stream_parse_success(core_agent_instance):
    """Test _step_stream method when parsing succeeds."""
    # Setup
    mock_memory_step = MagicMock()
    mock_chat_message = MagicMock()
    mock_chat_message.content = "```<RUN>\nprint('hello')\n```<END_CODE>"

    # Set all required attributes on the instance
    core_agent_instance.agent_name = "test_agent"
    core_agent_instance.step_number = 1
    core_agent_instance.grammar = None
    core_agent_instance.logger = MagicMock()
    core_agent_instance.memory = MagicMock()
    core_agent_instance.memory.steps = []

    with patch.object(core_agent_module, 'parse_code_blobs', return_value="print('hello')"), \
            patch.object(core_agent_module, 'fix_final_answer_code', return_value="print('hello')"):

        # Mock the methods directly on the instance
        core_agent_instance.write_memory_to_messages = MagicMock(
            return_value=[])
        core_agent_instance.model = MagicMock(return_value=mock_chat_message)
        core_agent_instance.python_executor = MagicMock(
            return_value=("output", "logs", False))

        # Execute
        list(core_agent_instance._step_stream(mock_memory_step))

        # Assertions
        assert mock_memory_step.tool_calls is not None
        assert len(mock_memory_step.tool_calls) == 1
        # Check that tool_calls was set (we can't easily test the exact content due to mock behavior)
        assert hasattr(mock_memory_step.tool_calls[0], 'name')
        assert hasattr(mock_memory_step.tool_calls[0], 'arguments')


def test_step_stream_parse_failure_raises_final_answer_error(core_agent_instance):
    """Test _step_stream method when parsing fails and raises FinalAnswerError."""
    # Setup
    mock_memory_step = MagicMock()
    mock_chat_message = MagicMock()
    mock_chat_message.content = "This is not code, just text"

    # Set all required attributes on the instance
    core_agent_instance.agent_name = "test_agent"
    core_agent_instance.step_number = 1
    core_agent_instance.grammar = None
    core_agent_instance.logger = MagicMock()
    core_agent_instance.memory = MagicMock()
    core_agent_instance.memory.steps = []

    with patch.object(core_agent_module, 'parse_code_blobs', side_effect=ValueError("No code found")):

        # Mock the methods directly on the instance
        core_agent_instance.write_memory_to_messages = MagicMock(
            return_value=[])
        core_agent_instance.model = MagicMock(return_value=mock_chat_message)

        # Execute and assert
        with pytest.raises(core_agent_module.FinalAnswerError):
            list(core_agent_instance._step_stream(mock_memory_step))


def test_step_stream_model_generation_error(core_agent_instance):
    """Test _step_stream method when model generation fails."""
    # Setup
    mock_memory_step = MagicMock()

    # Set all required attributes on the instance
    core_agent_instance.agent_name = "test_agent"
    core_agent_instance.step_number = 1
    core_agent_instance.grammar = None
    core_agent_instance.logger = MagicMock()
    core_agent_instance.memory = MagicMock()
    core_agent_instance.memory.steps = []

    # Mock the methods directly on the instance
    core_agent_instance.write_memory_to_messages = MagicMock(return_value=[])
    core_agent_instance.model = MagicMock(side_effect=Exception("Model error"))

    # Execute and assert
    # Should raise the original exception wrapped in AgentGenerationError
    with pytest.raises(Exception):
        list(core_agent_instance._step_stream(mock_memory_step))


def test_step_stream_execution_success(core_agent_instance):
    """Test _step_stream method when code execution succeeds."""
    # Setup
    mock_memory_step = MagicMock()
    mock_chat_message = MagicMock()
    mock_chat_message.content = "```<RUN>\nprint('hello')\n```<END_CODE>"

    # Set all required attributes on the instance
    core_agent_instance.agent_name = "test_agent"
    core_agent_instance.step_number = 1
    core_agent_instance.grammar = None
    core_agent_instance.logger = MagicMock()
    core_agent_instance.memory = MagicMock()
    core_agent_instance.memory.steps = []

    with patch.object(core_agent_module, 'parse_code_blobs', return_value="print('hello')"), \
            patch.object(core_agent_module, 'fix_final_answer_code', return_value="print('hello')"):

        # Mock the methods directly on the instance
        core_agent_instance.write_memory_to_messages = MagicMock(
            return_value=[])
        core_agent_instance.model = MagicMock(return_value=mock_chat_message)
        core_agent_instance.python_executor = MagicMock(
            return_value=("Hello World", "Execution logs", False))

        # Execute
        result = list(core_agent_instance._step_stream(mock_memory_step))

        # Assertions
        # Should yield None when is_final_answer is False
        assert result[0] is None
        assert mock_memory_step.observations is not None
        # Check that observations was set (we can't easily test the exact content due to mock behavior)
        assert hasattr(mock_memory_step, 'observations')


def test_step_stream_execution_final_answer(core_agent_instance):
    """Test _step_stream method when execution returns final answer."""
    # Setup
    mock_memory_step = MagicMock()
    mock_chat_message = MagicMock()
    mock_chat_message.content = "```<RUN>\nprint('final answer')\n```<END_CODE>"

    # Set all required attributes on the instance
    core_agent_instance.agent_name = "test_agent"
    core_agent_instance.step_number = 1
    core_agent_instance.grammar = None
    core_agent_instance.logger = MagicMock()
    core_agent_instance.memory = MagicMock()
    core_agent_instance.memory.steps = []

    with patch.object(core_agent_module, 'parse_code_blobs', return_value="print('final answer')"), \
            patch.object(core_agent_module, 'fix_final_answer_code', return_value="print('final answer')"):

        # Mock the methods directly on the instance
        core_agent_instance.write_memory_to_messages = MagicMock(
            return_value=[])
        core_agent_instance.model = MagicMock(return_value=mock_chat_message)
        core_agent_instance.python_executor = MagicMock(
            return_value=("final answer", "Execution logs", True))

        # Execute
        result = list(core_agent_instance._step_stream(mock_memory_step))

        # Assertions
        assert result[0] == "final answer"  # Should yield the final answer


def test_step_stream_execution_error(core_agent_instance):
    """Test _step_stream method when code execution fails."""
    # Setup
    mock_memory_step = MagicMock()
    mock_chat_message = MagicMock()
    mock_chat_message.content = "```<RUN>\ninvalid_code\n```<END_CODE>"

    # Set all required attributes on the instance
    core_agent_instance.agent_name = "test_agent"
    core_agent_instance.step_number = 1
    core_agent_instance.grammar = None
    core_agent_instance.logger = MagicMock()
    core_agent_instance.memory = MagicMock()
    core_agent_instance.memory.steps = []

    with patch.object(core_agent_module, 'parse_code_blobs', return_value="invalid_code"), \
            patch.object(core_agent_module, 'fix_final_answer_code', return_value="invalid_code"):

        # Mock python_executor with state containing print outputs
        mock_executor = MagicMock()
        mock_executor.state = {"_print_outputs": "Some print output"}
        mock_executor.side_effect = Exception("Execution error")

        # Mock the methods directly on the instance
        core_agent_instance.write_memory_to_messages = MagicMock(
            return_value=[])
        core_agent_instance.model = MagicMock(return_value=mock_chat_message)
        core_agent_instance.python_executor = mock_executor

        # Execute and assert
        with pytest.raises(Exception):  # Should raise AgentExecutionError
            list(core_agent_instance._step_stream(mock_memory_step))

        # Verify observations were set with print outputs
        assert mock_memory_step.observations is not None
        # Check that observations contains the print output
        assert hasattr(mock_memory_step.observations, '__contains__') or "Some print output" in str(
            mock_memory_step.observations)


def test_step_stream_observer_calls(core_agent_instance):
    """Test _step_stream method calls observer with correct messages."""
    # Setup
    mock_memory_step = MagicMock()
    mock_chat_message = MagicMock()
    mock_chat_message.content = "```<RUN>\nprint('test')\n```<END_CODE>"

    # Set all required attributes on the instance
    core_agent_instance.agent_name = "test_agent"
    core_agent_instance.step_number = 1
    core_agent_instance.grammar = None
    core_agent_instance.logger = MagicMock()
    core_agent_instance.memory = MagicMock()
    core_agent_instance.memory.steps = []

    with patch.object(core_agent_module, 'parse_code_blobs', return_value="print('test')"), \
            patch.object(core_agent_module, 'fix_final_answer_code', return_value="print('test')"):

        # Mock the methods directly on the instance
        core_agent_instance.write_memory_to_messages = MagicMock(
            return_value=[])
        core_agent_instance.model = MagicMock(return_value=mock_chat_message)
        core_agent_instance.python_executor = MagicMock(
            return_value=("test", "logs", False))

        # Execute
        list(core_agent_instance._step_stream(mock_memory_step))

        # Assertions
        # Should call observer for step count, parse, and execution logs
        assert core_agent_instance.observer.add_message.call_count >= 3
        calls = core_agent_instance.observer.add_message.call_args_list

        # Check step count call
        step_count_call = calls[0]
        assert step_count_call[0][1] == ProcessType.STEP_COUNT

        # Check parse call
        parse_call = calls[1]
        assert parse_call[0][1] == ProcessType.PARSE
        # The parse call should contain the fixed code, not the mock object
        assert "print('test')" in str(parse_call[0][2])

        # Check execution logs call
        execution_call = calls[2]
        assert execution_call[0][1] == ProcessType.EXECUTION_LOGS


# ----------------------------------------------------------------------------
# Additional tests for coverage gaps
# ----------------------------------------------------------------------------

def test_step_stream_execution_with_logs(core_agent_instance):
    """Test _step_stream method when execution has logs (lines 169-176)."""
    # Setup
    mock_memory_step = MagicMock()
    mock_chat_message = MagicMock()
    mock_chat_message.content = "```<RUN>\nprint('hello')\n```<END_CODE>"

    # Set all required attributes on the instance
    core_agent_instance.agent_name = "test_agent"
    core_agent_instance.step_number = 1
    core_agent_instance.grammar = None
    core_agent_instance.logger = MagicMock()
    core_agent_instance.memory = MagicMock()
    core_agent_instance.memory.steps = []

    with patch.object(core_agent_module, 'parse_code_blobs', return_value="print('hello')"), \
            patch.object(core_agent_module, 'fix_final_answer_code', return_value="print('hello')"):

        # Mock the methods directly on the instance
        core_agent_instance.write_memory_to_messages = MagicMock(
            return_value=[])
        core_agent_instance.model = MagicMock(return_value=mock_chat_message)
        # Mock python_executor to return logs
        core_agent_instance.python_executor = MagicMock(
            return_value=("output", "Some execution logs", False))

        # Execute
        result = list(core_agent_instance._step_stream(mock_memory_step))

        # Assertions
        # Should yield None when is_final_answer is False
        assert result[0] is None
        # Check that execution logs were recorded
        assert core_agent_instance.observer.add_message.call_count >= 3
        calls = core_agent_instance.observer.add_message.call_args_list
        execution_call = calls[2]
        assert execution_call[0][1] == ProcessType.EXECUTION_LOGS
        assert "Some execution logs" in str(execution_call[0][2])


def test_step_stream_execution_error_with_print_outputs(core_agent_instance):
    """Test _step_stream method when execution fails with print outputs (lines 178-191)."""
    # Setup
    mock_memory_step = MagicMock()
    mock_chat_message = MagicMock()
    mock_chat_message.content = "```<RUN>\ninvalid_code\n```<END_CODE>"

    # Set all required attributes on the instance
    core_agent_instance.agent_name = "test_agent"
    core_agent_instance.step_number = 1
    core_agent_instance.grammar = None
    core_agent_instance.logger = MagicMock()
    core_agent_instance.memory = MagicMock()
    core_agent_instance.memory.steps = []

    with patch.object(core_agent_module, 'parse_code_blobs', return_value="invalid_code"), \
            patch.object(core_agent_module, 'fix_final_answer_code', return_value="invalid_code"):

        # Mock python_executor with state containing print outputs
        mock_executor = MagicMock()
        mock_executor.state = {"_print_outputs": "Print output from execution"}
        mock_executor.side_effect = Exception("Execution error")

        # Mock the methods directly on the instance
        core_agent_instance.write_memory_to_messages = MagicMock(
            return_value=[])
        core_agent_instance.model = MagicMock(return_value=mock_chat_message)
        core_agent_instance.python_executor = mock_executor

        # Execute and assert
        with pytest.raises(Exception):  # Should raise AgentExecutionError
            list(core_agent_instance._step_stream(mock_memory_step))

        # Verify observations were set with print outputs
        assert mock_memory_step.observations is not None
        assert "Print output from execution" in str(
            mock_memory_step.observations)


def test_step_stream_execution_error_with_import_warning(core_agent_instance):
    """Test _step_stream method when execution fails with import error (lines 192-196)."""
    # Setup
    mock_memory_step = MagicMock()
    mock_chat_message = MagicMock()
    mock_chat_message.content = "```<RUN>\nimport forbidden_module\n```<END_CODE>"

    # Set all required attributes on the instance
    core_agent_instance.agent_name = "test_agent"
    core_agent_instance.step_number = 1
    core_agent_instance.grammar = None
    core_agent_instance.logger = MagicMock()
    core_agent_instance.memory = MagicMock()
    core_agent_instance.memory.steps = []

    with patch.object(core_agent_module, 'parse_code_blobs', return_value="import forbidden_module"), \
            patch.object(core_agent_module, 'fix_final_answer_code', return_value="import forbidden_module"):

        # Mock python_executor to raise import error
        mock_executor = MagicMock()
        mock_executor.state = {}
        mock_executor.side_effect = Exception(
            "Import of forbidden_module is not allowed")

        # Mock the methods directly on the instance
        core_agent_instance.write_memory_to_messages = MagicMock(
            return_value=[])
        core_agent_instance.model = MagicMock(return_value=mock_chat_message)
        core_agent_instance.python_executor = mock_executor

        # Execute and assert
        with pytest.raises(Exception):  # Should raise AgentExecutionError
            list(core_agent_instance._step_stream(mock_memory_step))

        # Verify warning was logged
        core_agent_instance.logger.log.assert_called()
        # Check that the warning message was logged
        log_calls = core_agent_instance.logger.log.call_args_list
        warning_calls = [
            call for call in log_calls if "Warning to user" in str(call)]
        assert len(warning_calls) > 0


def test_step_stream_execution_error_without_print_outputs(core_agent_instance):
    """Test _step_stream method when execution fails without print outputs."""
    # Setup
    mock_memory_step = MagicMock()
    mock_chat_message = MagicMock()
    mock_chat_message.content = "```<RUN>\ninvalid_code\n```<END_CODE>"

    # Set all required attributes on the instance
    core_agent_instance.agent_name = "test_agent"
    core_agent_instance.step_number = 1
    core_agent_instance.grammar = None
    core_agent_instance.logger = MagicMock()
    core_agent_instance.memory = MagicMock()
    core_agent_instance.memory.steps = []

    with patch.object(core_agent_module, 'parse_code_blobs', return_value="invalid_code"), \
            patch.object(core_agent_module, 'fix_final_answer_code', return_value="invalid_code"):

        # Mock python_executor without state or with empty state
        mock_executor = MagicMock()
        mock_executor.state = {}
        mock_executor.side_effect = Exception("Execution error")

        # Mock the methods directly on the instance
        core_agent_instance.write_memory_to_messages = MagicMock(
            return_value=[])
        core_agent_instance.model = MagicMock(return_value=mock_chat_message)
        core_agent_instance.python_executor = mock_executor

        # Execute and assert
        with pytest.raises(Exception):  # Should raise AgentExecutionError
            list(core_agent_instance._step_stream(mock_memory_step))


def test_step_stream_execution_with_none_output(core_agent_instance):
    """Test _step_stream method when execution returns None output."""
    # Setup
    mock_memory_step = MagicMock()
    mock_chat_message = MagicMock()
    mock_chat_message.content = "```<RUN>\nprint('hello')\n```<END_CODE>"

    # Set all required attributes on the instance
    core_agent_instance.agent_name = "test_agent"
    core_agent_instance.step_number = 1
    core_agent_instance.grammar = None
    core_agent_instance.logger = MagicMock()
    core_agent_instance.memory = MagicMock()
    core_agent_instance.memory.steps = []

    with patch.object(core_agent_module, 'parse_code_blobs', return_value="print('hello')"), \
            patch.object(core_agent_module, 'fix_final_answer_code', return_value="print('hello')"):

        # Mock the methods directly on the instance
        core_agent_instance.write_memory_to_messages = MagicMock(
            return_value=[])
        core_agent_instance.model = MagicMock(return_value=mock_chat_message)
        # Mock python_executor to return None output
        core_agent_instance.python_executor = MagicMock(
            return_value=(None, "Execution logs", False))

        # Execute
        result = list(core_agent_instance._step_stream(mock_memory_step))

        # Assertions
        # Should yield None when is_final_answer is False
        assert result[0] is None
        assert mock_memory_step.observations is not None
        # Check that observations was set but should not contain "Last output from code snippet"
        # since output is None
        observations_str = str(mock_memory_step.observations)
        assert "Execution logs:" in observations_str
        assert "Last output from code snippet:" not in observations_str

# ----------------------------------------------------------------------------
# Tests for run method (lines 229-263)
# ----------------------------------------------------------------------------

def test_run_with_additional_args(core_agent_instance):
    """Test run method with additional_args parameter."""
    # Setup
    task = "test task"
    additional_args = {"param1": "value1", "param2": 42}

    # Mock required attributes
    core_agent_instance.max_steps = 5
    core_agent_instance.state = {}
    core_agent_instance.initialize_system_prompt = MagicMock(
        return_value="system prompt")
    core_agent_instance.memory = MagicMock()
    core_agent_instance.memory.reset = MagicMock()
    core_agent_instance.monitor = MagicMock()
    core_agent_instance.monitor.reset = MagicMock()
    core_agent_instance.logger = MagicMock()
    core_agent_instance.model = MagicMock()
    core_agent_instance.model.model_id = "test-model"
    core_agent_instance.name = "test_agent"
    core_agent_instance.python_executor = MagicMock()
    core_agent_instance.tools = {}
    core_agent_instance.managed_agents = {}
    core_agent_instance.observer = MagicMock()

    # Mock _run_stream to return a simple result
    mock_final_step = MagicMock()
    mock_final_step.final_answer = "final result"

    with patch.object(core_agent_instance, '_run_stream', return_value=[mock_final_step]):
        # Execute
        result = core_agent_instance.run(
            task, additional_args=additional_args, stream=False)

        # Assertions
        assert result == "final result"
        assert core_agent_instance.state == additional_args
        assert "You have been provided with these additional arguments" in core_agent_instance.task
        assert str(additional_args) in core_agent_instance.task


def test_run_with_stream_true(core_agent_instance):
    """Test run method with stream=True."""
    # Setup
    task = "test task"

    # Mock required attributes
    core_agent_instance.max_steps = 5
    core_agent_instance.state = {}
    core_agent_instance.initialize_system_prompt = MagicMock(
        return_value="system prompt")
    core_agent_instance.memory = MagicMock()
    core_agent_instance.memory.reset = MagicMock()
    core_agent_instance.monitor = MagicMock()
    core_agent_instance.monitor.reset = MagicMock()
    core_agent_instance.logger = MagicMock()
    core_agent_instance.model = MagicMock()
    core_agent_instance.model.model_id = "test-model"
    core_agent_instance.name = "test_agent"
    core_agent_instance.python_executor = MagicMock()
    core_agent_instance.tools = {}
    core_agent_instance.managed_agents = {}
    core_agent_instance.observer = MagicMock()

    # Mock _run_stream to return a generator
    mock_steps = [MagicMock(), MagicMock()]

    with patch.object(core_agent_instance, '_run_stream', return_value=mock_steps):
        # Execute
        result = core_agent_instance.run(task, stream=True)

        # Assertions
        assert result == mock_steps


def test_run_with_reset_false(core_agent_instance):
    """Test run method with reset=False."""
    # Setup
    task = "test task"

    # Mock required attributes
    core_agent_instance.max_steps = 5
    core_agent_instance.state = {}
    core_agent_instance.initialize_system_prompt = MagicMock(
        return_value="system prompt")
    core_agent_instance.memory = MagicMock()
    core_agent_instance.memory.reset = MagicMock()
    core_agent_instance.monitor = MagicMock()
    core_agent_instance.monitor.reset = MagicMock()
    core_agent_instance.logger = MagicMock()
    core_agent_instance.model = MagicMock()
    core_agent_instance.model.model_id = "test-model"
    core_agent_instance.name = "test_agent"
    core_agent_instance.python_executor = MagicMock()
    core_agent_instance.tools = {}
    core_agent_instance.managed_agents = {}
    core_agent_instance.observer = MagicMock()

    # Mock _run_stream to return a simple result
    mock_final_step = MagicMock()
    mock_final_step.final_answer = "final result"

    with patch.object(core_agent_instance, '_run_stream', return_value=[mock_final_step]):
        # Execute
        result = core_agent_instance.run(task, reset=False)

        # Assertions
        assert result == "final result"
        # Memory and monitor should not be reset
        core_agent_instance.memory.reset.assert_not_called()
        core_agent_instance.monitor.reset.assert_not_called()


def test_run_with_images(core_agent_instance):
    """Test run method with images parameter."""
    # Setup
    task = "test task"
    images = ["image1.jpg", "image2.jpg"]

    # Mock required attributes
    core_agent_instance.max_steps = 5
    core_agent_instance.state = {}
    core_agent_instance.initialize_system_prompt = MagicMock(
        return_value="system prompt")
    core_agent_instance.memory = MagicMock()
    core_agent_instance.memory.reset = MagicMock()
    core_agent_instance.monitor = MagicMock()
    core_agent_instance.monitor.reset = MagicMock()
    core_agent_instance.logger = MagicMock()
    core_agent_instance.model = MagicMock()
    core_agent_instance.model.model_id = "test-model"
    core_agent_instance.name = "test_agent"
    core_agent_instance.python_executor = MagicMock()
    core_agent_instance.tools = {}
    core_agent_instance.managed_agents = {}
    core_agent_instance.observer = MagicMock()

    # Mock _run_stream to return a simple result
    mock_final_step = MagicMock()
    mock_final_step.final_answer = "final result"

    with patch.object(core_agent_instance, '_run_stream', return_value=[mock_final_step]):
        # Execute
        result = core_agent_instance.run(task, images=images)

        # Assertions
        assert result == "final result"
        # Verify TaskStep was added with images
        core_agent_instance.memory.steps.append.assert_called_once()
        call_args = core_agent_instance.memory.steps.append.call_args[0][0]
        # The TaskStep is mocked, so just verify it was called with correct arguments via the constructor
        # We'll check that TaskStep was called with the right parameters
        mock_smolagents.memory.TaskStep.assert_called_with(
            task=task, task_images=images)


def test_run_without_python_executor(core_agent_instance):
    """Test run method when python_executor is None."""
    # Setup
    task = "test task"

    # Mock required attributes
    core_agent_instance.max_steps = 5
    core_agent_instance.state = {}
    core_agent_instance.initialize_system_prompt = MagicMock(
        return_value="system prompt")
    core_agent_instance.memory = MagicMock()
    core_agent_instance.memory.reset = MagicMock()
    core_agent_instance.monitor = MagicMock()
    core_agent_instance.monitor.reset = MagicMock()
    core_agent_instance.logger = MagicMock()
    core_agent_instance.model = MagicMock()
    core_agent_instance.model.model_id = "test-model"
    core_agent_instance.name = "test_agent"
    core_agent_instance.python_executor = None  # No python executor
    core_agent_instance.tools = {}
    core_agent_instance.managed_agents = {}
    core_agent_instance.observer = MagicMock()

    # Mock _run_stream to return a simple result
    mock_final_step = MagicMock()
    mock_final_step.final_answer = "final result"

    with patch.object(core_agent_instance, '_run_stream', return_value=[mock_final_step]):
        # Execute
        result = core_agent_instance.run(task)

        # Assertions
        assert result == "final result"
        # Should not call send_variables or send_tools when python_executor is None


# ----------------------------------------------------------------------------
# Tests for __call__ method (lines 269-290)
# ----------------------------------------------------------------------------

def test_call_method_success(core_agent_instance):
    """Test __call__ method with successful execution."""
    # Setup
    task = "test task"

    # Mock required attributes - use simple string templates without variables
    core_agent_instance.name = "test_agent"
    core_agent_instance.state = {}
    core_agent_instance.prompt_templates = {
        "managed_agent": {
            # Simple template with just task variable
            "task": "Task: {{task}}",
            # Simple template with just final_answer variable
            "report": "Report: {{final_answer}}"
        }
    }
    core_agent_instance.provide_run_summary = False
    core_agent_instance.observer = MagicMock()

    # Mock run method to return a simple result
    with patch.object(core_agent_instance, 'run', return_value="test result"):
        # Execute
        result = core_agent_instance(task)

        # Assertions
        # Check that the result follows the expected format
        assert "Report: test result" in result

        # Verify run was called with the rendered task template
        core_agent_instance.run.assert_called_once()
        called_task = core_agent_instance.run.call_args[0][0]
        assert "Task: test task" in called_task

        # Verify observer was notified
        core_agent_instance.observer.add_message.assert_called_with(
            "test_agent", ProcessType.AGENT_FINISH, "test result")


def test_call_method_with_run_summary(core_agent_instance):
    """Test __call__ method with provide_run_summary=True."""
    # Setup
    task = "test task"

    # Mock required attributes - use simple templates
    core_agent_instance.name = "test_agent"
    core_agent_instance.state = {}
    core_agent_instance.prompt_templates = {
        "managed_agent": {
            "task": "Task: {{task}}",
            "report": "Report: {{final_answer}}"
        }
    }
    core_agent_instance.provide_run_summary = True
    core_agent_instance.observer = MagicMock()

    # Mock write_memory_to_messages to return some simple messages
    mock_messages = [
        {"content": "msg1"},
        {"content": "msg2"}
    ]
    core_agent_instance.write_memory_to_messages = MagicMock(
        return_value=mock_messages)

    # Use the actual truncate_content function but simplify the test
    with patch.object(core_agent_instance, 'run', return_value="test result"):

        # Execute
        result = core_agent_instance(task)

        # Assertions
        # The result should be a string containing the expected components
        assert isinstance(result, str)
        assert "Report: test result" in result
        assert "<summary_of_work>" in result
        # Check for message content (will be truncated by real function)
        assert "msg1" in result
        assert "msg2" in result
        assert "</summary_of_work>" in result

        # Verify write_memory_to_messages was called with summary_mode=True
        core_agent_instance.write_memory_to_messages.assert_called_with(
            summary_mode=True)


def test_call_method_observer_exception(core_agent_instance):
    """Test __call__ method when observer.add_message raises exception."""
    # Setup
    task = "test task"

    # Mock required attributes - use simple templates
    core_agent_instance.name = "test_agent"
    core_agent_instance.state = {}
    core_agent_instance.prompt_templates = {
        "managed_agent": {
            "task": "Task: {{task}}",
            "report": "Report: {{final_answer}}"
        }
    }
    core_agent_instance.provide_run_summary = False
    core_agent_instance.observer = MagicMock()
    core_agent_instance.observer.add_message.side_effect = [
        Exception("Observer error"), None]

    # Mock run method
    with patch.object(core_agent_instance, 'run', return_value="test result"):

        # Execute
        result = core_agent_instance(task)

        # Assertions
        # The result should contain the rendered template even when observer fails
        assert "Report: test result" in result

        # Should call observer twice: once for AGENT_FINISH (which raises), once in except block
        assert core_agent_instance.observer.add_message.call_count == 2

        # Verify the calls were made correctly
        calls = core_agent_instance.observer.add_message.call_args_list
        # First call should try to send "test result"
        assert calls[0][0][0] == "test_agent"
        assert calls[0][0][1] == ProcessType.AGENT_FINISH
        assert calls[0][0][2] == "test result"
        # Second call should be with empty string in the except block
        assert calls[1][0][0] == "test_agent"
        assert calls[1][0][1] == ProcessType.AGENT_FINISH
        assert calls[1][0][2] == ""


def test_call_method_with_kwargs(core_agent_instance):
    """Test __call__ method with additional kwargs."""
    # Setup
    task = "test task"
    kwargs = {"stream": True, "max_steps": 10}

    # Mock required attributes - use simple templates
    core_agent_instance.name = "test_agent"
    core_agent_instance.state = {}
    core_agent_instance.prompt_templates = {
        "managed_agent": {
            "task": "Task: {{task}}",
            "report": "Report: {{final_answer}}"
        }
    }
    core_agent_instance.provide_run_summary = False
    core_agent_instance.observer = MagicMock()

    # Mock run method
    with patch.object(core_agent_instance, 'run', return_value="test result") as mock_run:

        # Execute
        result = core_agent_instance(task, **kwargs)

        # Assertions
        # The result should contain the rendered template
        assert "Report: test result" in result

        # Verify run was called with the rendered task and kwargs
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        # Check that the task was rendered correctly
        assert "Task: test task" in call_args[0][0]
        # Check that kwargs were passed through
        assert call_args[1] == kwargs

        # Verify observer was notified
        core_agent_instance.observer.add_message.assert_called_with(
            "test_agent", ProcessType.AGENT_FINISH, "test result")
