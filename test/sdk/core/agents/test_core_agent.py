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

mock_smolagents.handle_agent_output_types = MagicMock(return_value="handled_output")

# Create dummy smolagents sub-modules
for sub_mod in ["agents", "memory", "models", "monitoring", "utils", "local_python_executor"]:
    mock_module = MagicMock()
    setattr(mock_smolagents, sub_mod, mock_module)

mock_smolagents.agents.CodeAgent = MagicMock

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
        assert isinstance(result[4], MagicMock)  # Final action step (from _handle_max_steps_reached)
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
    assert isinstance(result[2], MagicMock)  # Final answer step with "<user_break>"


def test_run_with_agent_error(core_agent_instance):
    """Test _run method when AgentError occurs."""
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


def test_run_with_agent_parse_error_branch(core_agent_instance):
    """Ensure branch that converts model_output via convert_code_format is covered."""

    task = "parse task"
    max_steps = 1

    parse_hint = "Make sure to include code with the correct pattern, for instance"

    # Create a mock action step that will be used in the error handling
    mock_action_step = MagicMock()
    mock_action_step.model_output = "unformatted answer"

    # Mock ActionStep constructor to return our mock
    with patch.object(mock_smolagents.memory, 'ActionStep', return_value=mock_action_step), \
            patch.object(core_agent_instance, '_execute_step', side_effect=MockAgentError(f"{parse_hint} - error")), \
            patch.object(core_agent_module, 'convert_code_format', return_value="formatted answer") as mock_convert, \
            patch.object(core_agent_instance, '_finalize_step'):
        results = list(core_agent_instance._run_stream(task, max_steps))

    # _run 应该产出 action step + 处理后的结果
    assert len(results) >= 2
    assert isinstance(results[0], MagicMock)  # Action step
    assert isinstance(results[-1], MagicMock)  # Final answer step





def test_convert_code_format_replacements():
    """Validate convert_code_format correctly transforms code fences."""

    original_text = """Here is code:\n```code:python\nprint('hello')\n```\nAnd mixed fence ```< should be fixed."""

    expected_text = """Here is code:\n```python\nprint('hello')\n```\nAnd mixed fence ``` should be fixed."""

    transformed = core_agent_module.convert_code_format(original_text)

    assert transformed == expected_text, "convert_code_format did not perform expected replacements"

# ----------------------------------------------------------------------------
# Tests for parse_code_blobs function
# ----------------------------------------------------------------------------

def test_parse_code_blobs_python_match():
    """Test parse_code_blobs with ```python\ncontent\n``` pattern."""
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
    """Test parse_code_blobs with ```py\ncontent\n``` pattern."""
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
    
    assert "regex pattern" in str(exc_info.value)


def test_parse_code_blobs_javascript_no_match():
    """Test parse_code_blobs with ```javascript\ncontent\n``` (other language)."""
    text = """Here is some JavaScript code:
```javascript
console.log("Hello World");
```
But this should not match."""
    
    with pytest.raises(ValueError) as exc_info:
        core_agent_module.parse_code_blobs(text)
    
    assert "regex pattern" in str(exc_info.value)


def test_parse_code_blobs_java_no_match():
    """Test parse_code_blobs with ```java\ncontent\n``` (other language)."""
    text = """Here is some Java code:
```java
System.out.println("Hello World");
```
But this should not match."""
    
    with pytest.raises(ValueError) as exc_info:
        core_agent_module.parse_code_blobs(text)
    
    assert "regex pattern" in str(exc_info.value)


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
    
    assert "regex pattern" in str(exc_info.value)


def test_parse_code_blobs_generic_error():
    """Test parse_code_blobs with generic case that should raise ValueError."""
    text = """This is just some random text.
Just plain text that should fail."""
    
    with pytest.raises(ValueError) as exc_info:
        core_agent_module.parse_code_blobs(text)
    
    error_msg = str(exc_info.value)
    assert "regex pattern" in error_msg
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
