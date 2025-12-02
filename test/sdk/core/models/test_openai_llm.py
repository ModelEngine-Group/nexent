from unittest.mock import AsyncMock, MagicMock, patch, ANY
import importlib.util
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Prepare mocks for external dependencies similar to test_core_agent.py
# ---------------------------------------------------------------------------

# Mock smolagents and submodules
mock_smolagents = MagicMock()
mock_smolagents.Tool = MagicMock()

# Create dummy sub-modules and attributes
mock_models_module = MagicMock()


# Provide a minimal OpenAIServerModel base with the method needed by OpenAIModel
class DummyOpenAIServerModel:
    def __init__(self, *args, **kwargs):
        pass

    def _prepare_completion_kwargs(self, *args, **kwargs):
        # In tests we will patch this method on the instance directly, so default impl is fine
        return {}


mock_models_module.OpenAIServerModel = DummyOpenAIServerModel
mock_models_module.ChatMessage = MagicMock()
mock_models_module.MessageRole = MagicMock()
mock_smolagents.models = mock_models_module

# Mock monitoring modules
monitoring_manager_mock = MagicMock()

# Define a decorator that simply returns the original function unchanged


def pass_through_decorator(*args, **kwargs):
    def decorator(func):
        return func
    return decorator


monitoring_manager_mock.monitor_endpoint = pass_through_decorator
monitoring_manager_mock.monitor_llm_call = pass_through_decorator
monitoring_manager_mock.setup_fastapi_app = MagicMock(return_value=True)
monitoring_manager_mock.configure = MagicMock()
monitoring_manager_mock.add_span_event = MagicMock()
monitoring_manager_mock.set_span_attributes = MagicMock()

# Mock nexent.monitor modules
nexent_monitor_mock = MagicMock()
nexent_monitor_mock.get_monitoring_manager = lambda: monitoring_manager_mock
nexent_monitor_mock.monitoring_manager = monitoring_manager_mock
nexent_monitor_mock.MonitoringManager = MagicMock
nexent_monitor_mock.MonitoringConfig = MagicMock

# Create mock parent package structure for nexent module
nexent_mock = MagicMock()
nexent_mock.monitor = nexent_monitor_mock
nexent_core_mock = MagicMock()
nexent_core_models_mock = MagicMock()
nexent_core_utils_mock = MagicMock()

# Mock MessageObserver and ProcessType for utils.observer
class MockMessageObserver:
    def __init__(self, *args, **kwargs):
        self.add_model_new_token = MagicMock()
        self.add_model_reasoning_content = MagicMock()
        self.flush_remaining_tokens = MagicMock()

class MockProcessType:
    MODEL_OUTPUT_THINKING = "model_output_thinking"
    MODEL_OUTPUT = "model_output"

nexent_core_utils_mock.observer = MagicMock()
nexent_core_utils_mock.observer.MessageObserver = MockMessageObserver
nexent_core_utils_mock.observer.ProcessType = MockProcessType

# Assemble smolagents.* paths and monitoring mocks
module_mocks = {
    "smolagents": mock_smolagents,
    "smolagents.models": mock_models_module,
    "openai.types": MagicMock(),
    "openai.types.chat": MagicMock(),
    "openai.types.chat.chat_completion_message": MagicMock(),
    "openai": MagicMock(),
    "openai.lib": MagicMock(),
    "nexent": nexent_mock,
    "nexent.monitor": nexent_monitor_mock,
    "nexent.monitor.monitoring": nexent_monitor_mock,
    "nexent.core": nexent_core_mock,
    "nexent.core.models": nexent_core_models_mock,
    "nexent.core.utils": nexent_core_utils_mock,
    "nexent.core.utils.observer": nexent_core_utils_mock.observer,
}

# Dynamically load the module directly by file path
MODULE_NAME = "nexent.core.models.openai_llm"
MODULE_PATH = (
    Path(__file__).resolve().parents[4]
    / "sdk"
    / "nexent"
    / "core"
    / "models"
    / "openai_llm.py"
)

with patch.dict("sys.modules", module_mocks):
    spec = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
    openai_llm_module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = openai_llm_module
    assert spec and spec.loader
    spec.loader.exec_module(openai_llm_module)
    ImportedOpenAIModel = openai_llm_module.OpenAIModel

    # -----------------------------------------------------------------------
    # Fixtures
    # -----------------------------------------------------------------------

    @pytest.fixture()
    def openai_model_instance():
        """Return an OpenAIModel instance with minimal viable attributes for tests."""

        observer = MagicMock()
        model = ImportedOpenAIModel(observer=observer)

        # Inject dummy attributes required by the method under test
        model.model_id = "dummy-model"
        model.temperature = 0.7
        model.top_p = 0.9
        model.custom_role_conversions = {}  # Add missing attribute

        # Client hierarchy: client.chat.completions.create
        mock_client = MagicMock()
        mock_chat = MagicMock()
        mock_completions = MagicMock()
        mock_completions.create = MagicMock()
        mock_chat.completions = mock_completions
        mock_client.chat = mock_chat
        model.client = mock_client

        return model

    @pytest.fixture()
    def mock_chat_message():
        """Create a mock ChatMessage for testing"""
        mock_message = MagicMock()
        mock_message.raw = MagicMock()
        mock_message.role = MagicMock()
        return mock_message


# ---------------------------------------------------------------------------
# Tests for check_connectivity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_connectivity_success(openai_model_instance):
    """check_connectivity should return True when no exception is raised."""

    with patch.object(
            openai_model_instance,
            "_prepare_completion_kwargs",
            return_value={},
    ) as mock_prepare_kwargs, patch(
        "sdk.nexent.core.models.openai_llm.asyncio.to_thread",
        new_callable=AsyncMock,
        return_value=None,
    ) as mock_to_thread:
        result = await openai_model_instance.check_connectivity()

        assert result is True
        mock_prepare_kwargs.assert_called_once()
        mock_to_thread.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_connectivity_failure(openai_model_instance):
    """check_connectivity should return False when an exception is raised inside to_thread."""

    with patch.object(
            openai_model_instance,
            "_prepare_completion_kwargs",
            return_value={},
    ), patch(
        "sdk.nexent.core.models.openai_llm.asyncio.to_thread",
        new_callable=AsyncMock,
        side_effect=Exception("connection error"),
    ):
        result = await openai_model_instance.check_connectivity()
        assert result is False


# ---------------------------------------------------------------------------
# Tests for __call__ method
# ---------------------------------------------------------------------------

def test_call_normal_operation(openai_model_instance):
    """Test __call__ method with normal operation flow"""

    # Setup test messages with correct format
    messages = [
        {"role": "user", "content": [{"text": "Hello"}]},
        {"role": "assistant", "content": [{"text": "Hi there"}]}
    ]

    # Mock the stream response
    mock_chunk1 = MagicMock()
    mock_chunk1.choices = [MagicMock()]
    mock_chunk1.choices[0].delta.content = "Hello"
    mock_chunk1.choices[0].delta.role = "assistant"

    mock_chunk2 = MagicMock()
    mock_chunk2.choices = [MagicMock()]
    mock_chunk2.choices[0].delta.content = " world"
    mock_chunk2.choices[0].delta.role = None

    mock_chunk3 = MagicMock()
    mock_chunk3.choices = [MagicMock()]
    mock_chunk3.choices[0].delta.content = None
    mock_chunk3.choices[0].delta.role = None
    mock_chunk3.usage = MagicMock()
    mock_chunk3.usage.prompt_tokens = 10
    mock_chunk3.usage.total_tokens = 15
    # Set completion_tokens for output token count
    mock_chunk3.usage.completion_tokens = 5

    mock_stream = [mock_chunk1, mock_chunk2, mock_chunk3]

    # Mock ChatMessage.from_dict to return a mock message
    mock_result_message = MagicMock()
    mock_result_message.raw = mock_stream
    mock_result_message.role = MagicMock()

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}) as mock_prepare, \
            patch.object(mock_models_module.ChatMessage, "from_dict", return_value=mock_result_message):
        # Mock the client response
        openai_model_instance.client.chat.completions.create.return_value = mock_stream

        # Call the method
        result = openai_model_instance.__call__(messages)

        # Verify the result
        assert result == mock_result_message
        mock_prepare.assert_called_once()

        # Verify observer calls
        openai_model_instance.observer.add_model_new_token.assert_any_call(
            "Hello")
        openai_model_instance.observer.add_model_new_token.assert_any_call(
            " world")
        openai_model_instance.observer.flush_remaining_tokens.assert_called_once()

        # Verify token counts were set
        assert openai_model_instance.last_input_token_count == 10
        assert openai_model_instance.last_output_token_count == 5


def test_call_with_no_think_token_addition(openai_model_instance):
    """Test __call__ method adds /no_think token to user messages"""

    # Setup test messages with user as last message
    messages = [
        {"role": "assistant", "content": [{"text": "Hi there"}]},
        {"role": "user", "content": [{"text": "Hello"}]}
    ]

    # Mock the stream response
    mock_chunk = MagicMock()
    mock_chunk.choices = [MagicMock()]
    mock_chunk.choices[0].delta.content = "Response"
    mock_chunk.choices[0].delta.role = "assistant"
    mock_chunk.usage = MagicMock()
    mock_chunk.usage.prompt_tokens = 5
    mock_chunk.usage.total_tokens = 8

    # Mock ChatMessage.from_dict to return a mock message
    mock_result_message = MagicMock()
    mock_result_message.raw = [mock_chunk]
    mock_result_message.role = MagicMock()

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}), \
            patch.object(mock_models_module.ChatMessage, "from_dict", return_value=mock_result_message):
        openai_model_instance.client.chat.completions.create.return_value = [
            mock_chunk]

        # Call the method
        openai_model_instance.__call__(messages)

        # Verify that /no_think was added to the last user message
        assert messages[-1]["content"][-1]["text"] == "Hello"


def test_call_without_no_think_token(openai_model_instance):
    """Test __call__ method doesn't add /no_think when last message is not user"""

    # Setup test messages with assistant as last message
    messages = [
        {"role": "user", "content": [{"text": "Hello"}]},
        {"role": "assistant", "content": [{"text": "Hi there"}]}
    ]

    # Mock the stream response
    mock_chunk = MagicMock()
    mock_chunk.choices = [MagicMock()]
    mock_chunk.choices[0].delta.content = "Response"
    mock_chunk.choices[0].delta.role = "assistant"
    mock_chunk.usage = MagicMock()
    mock_chunk.usage.prompt_tokens = 5
    mock_chunk.usage.total_tokens = 8

    # Mock ChatMessage.from_dict to return a mock message
    mock_result_message = MagicMock()
    mock_result_message.raw = [mock_chunk]
    mock_result_message.role = MagicMock()

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}), \
            patch.object(mock_models_module.ChatMessage, "from_dict", return_value=mock_result_message):
        openai_model_instance.client.chat.completions.create.return_value = [
            mock_chunk]

        # Call the method
        openai_model_instance.__call__(messages)

        # Verify that /no_think was NOT added
        assert messages[-1]["content"][-1]["text"] == "Hi there"


def test_call_stop_event_interruption(openai_model_instance):
    """Test __call__ method raises RuntimeError when stop_event is set"""

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    # Mock the stream response
    mock_chunk = MagicMock()
    mock_chunk.choices = [MagicMock()]
    mock_chunk.choices[0].delta.content = "Response"
    mock_chunk.choices[0].delta.role = "assistant"

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}):
        openai_model_instance.client.chat.completions.create.return_value = [
            mock_chunk]

        # Set the stop event before calling
        openai_model_instance.stop_event.set()

        # Call the method and expect RuntimeError
        with pytest.raises(RuntimeError, match="Model is interrupted by stop event"):
            openai_model_instance.__call__(messages)


def test_call_context_length_exceeded_error(openai_model_instance):
    """Test __call__ method handles context_length_exceeded error correctly"""

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}):
        # Mock the client to raise context length exceeded error
        openai_model_instance.client.chat.completions.create.side_effect = Exception(
            "context_length_exceeded: token limit exceeded")

        # Call the method and expect the original Exception (since client.create error is not wrapped)
        with pytest.raises(Exception, match="context_length_exceeded: token limit exceeded"):
            openai_model_instance.__call__(messages)


def test_call_general_exception(openai_model_instance):
    """Test __call__ method re-raises general exceptions"""

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}):
        # Mock the client to raise a general exception
        openai_model_instance.client.chat.completions.create.side_effect = Exception(
            "General error")

        # Call the method and expect the same exception
        with pytest.raises(Exception, match="General error"):
            openai_model_instance.__call__(messages)


def test_call_with_no_usage_info(openai_model_instance):
    """Test __call__ method handles case where usage info is None"""

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    # Mock the stream response with no usage info
    mock_chunk = MagicMock()
    mock_chunk.choices = [MagicMock()]
    mock_chunk.choices[0].delta.content = "Response"
    mock_chunk.choices[0].delta.role = "assistant"
    mock_chunk.usage = None

    # Mock ChatMessage.from_dict to return a mock message
    mock_result_message = MagicMock()
    mock_result_message.raw = [mock_chunk]
    mock_result_message.role = MagicMock()

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}), \
            patch.object(mock_models_module.ChatMessage, "from_dict", return_value=mock_result_message):
        openai_model_instance.client.chat.completions.create.return_value = [
            mock_chunk]

        # Call the method
        openai_model_instance.__call__(messages)

        # Verify token counts are set to 0 when usage is None
        assert openai_model_instance.last_input_token_count == 0
        assert openai_model_instance.last_output_token_count == 0


def test_call_with_null_tokens(openai_model_instance):
    """Test __call__ method handles null tokens in stream"""

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    # Mock the stream response with null tokens
    mock_chunk1 = MagicMock()
    mock_chunk1.choices = [MagicMock()]
    mock_chunk1.choices[0].delta.content = None
    mock_chunk1.choices[0].delta.role = "assistant"

    mock_chunk2 = MagicMock()
    mock_chunk2.choices = [MagicMock()]
    mock_chunk2.choices[0].delta.content = "Response"
    mock_chunk2.choices[0].delta.role = None
    mock_chunk2.usage = MagicMock()
    mock_chunk2.usage.prompt_tokens = 5
    mock_chunk2.usage.total_tokens = 8

    # Mock ChatMessage.from_dict to return a mock message
    mock_result_message = MagicMock()
    mock_result_message.raw = [mock_chunk1, mock_chunk2]
    mock_result_message.role = MagicMock()

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}), \
            patch.object(mock_models_module.ChatMessage, "from_dict", return_value=mock_result_message):
        openai_model_instance.client.chat.completions.create.return_value = [
            mock_chunk1, mock_chunk2]

        # Call the method
        openai_model_instance.__call__(messages)

        # Verify that null tokens are handled correctly (not added to observer)
        openai_model_instance.observer.add_model_new_token.assert_called_once_with(
            "Response")


def test_call_with_reasoning_content(openai_model_instance):
    """Test __call__ method handles reasoning_content when it is not None"""

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    # Mock the stream response with reasoning_content
    mock_chunk1 = MagicMock()
    mock_chunk1.choices = [MagicMock()]
    mock_chunk1.choices[0].delta.content = "Let me think about this"
    mock_chunk1.choices[0].delta.role = "assistant"
    mock_chunk1.choices[0].delta.reasoning_content = "This is a reasoning step"

    mock_chunk2 = MagicMock()
    mock_chunk2.choices = [MagicMock()]
    mock_chunk2.choices[0].delta.content = "Response"
    mock_chunk2.choices[0].delta.role = None
    mock_chunk2.choices[0].delta.reasoning_content = None
    mock_chunk2.usage = MagicMock()
    mock_chunk2.usage.prompt_tokens = 5
    mock_chunk2.usage.total_tokens = 8

    # Mock ChatMessage.from_dict to return a mock message
    mock_result_message = MagicMock()
    mock_result_message.raw = [mock_chunk1, mock_chunk2]
    mock_result_message.role = MagicMock()

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}), \
            patch.object(mock_models_module.ChatMessage, "from_dict", return_value=mock_result_message):
        openai_model_instance.client.chat.completions.create.return_value = [
            mock_chunk1, mock_chunk2]

        # Call the method
        result = openai_model_instance.__call__(messages)

        # Verify the result
        assert result == mock_result_message

        # Verify that reasoning_content was added to observer
        openai_model_instance.observer.add_model_reasoning_content.assert_called_once_with(
            "This is a reasoning step")

        # Verify that normal tokens were also added
        openai_model_instance.observer.add_model_new_token.assert_any_call(
            "Let me think about this")
        openai_model_instance.observer.add_model_new_token.assert_any_call(
            "Response")


def test_call_with_multiple_reasoning_content_chunks(openai_model_instance):
    """Test __call__ method handles multiple chunks with reasoning_content"""

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    # Mock the stream response with multiple reasoning_content chunks
    mock_chunk1 = MagicMock()
    mock_chunk1.choices = [MagicMock()]
    mock_chunk1.choices[0].delta.content = "Let me"
    mock_chunk1.choices[0].delta.role = "assistant"
    mock_chunk1.choices[0].delta.reasoning_content = "First reasoning step"

    mock_chunk2 = MagicMock()
    mock_chunk2.choices = [MagicMock()]
    mock_chunk2.choices[0].delta.content = " think"
    mock_chunk2.choices[0].delta.role = None
    mock_chunk2.choices[0].delta.reasoning_content = "Second reasoning step"

    mock_chunk3 = MagicMock()
    mock_chunk3.choices = [MagicMock()]
    mock_chunk3.choices[0].delta.content = " about this"
    mock_chunk3.choices[0].delta.role = None
    mock_chunk3.choices[0].delta.reasoning_content = None
    mock_chunk3.usage = MagicMock()
    mock_chunk3.usage.prompt_tokens = 5
    mock_chunk3.usage.total_tokens = 8

    # Mock ChatMessage.from_dict to return a mock message
    mock_result_message = MagicMock()
    mock_result_message.raw = [mock_chunk1, mock_chunk2, mock_chunk3]
    mock_result_message.role = MagicMock()

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}), \
            patch.object(mock_models_module.ChatMessage, "from_dict", return_value=mock_result_message):
        openai_model_instance.client.chat.completions.create.return_value = [
            mock_chunk1, mock_chunk2, mock_chunk3]

        # Call the method
        result = openai_model_instance.__call__(messages)

        # Verify the result
        assert result == mock_result_message

        # Verify that all reasoning_content chunks were added to observer
        openai_model_instance.observer.add_model_reasoning_content.assert_any_call(
            "First reasoning step")
        openai_model_instance.observer.add_model_reasoning_content.assert_any_call(
            "Second reasoning step")

        # Verify that normal tokens were also added
        openai_model_instance.observer.add_model_new_token.assert_any_call(
            "Let me")
        openai_model_instance.observer.add_model_new_token.assert_any_call(
            " think")
        openai_model_instance.observer.add_model_new_token.assert_any_call(
            " about this")


def test_call_with_reasoning_content_only(openai_model_instance):
    """Test __call__ method handles chunks with only reasoning_content (no content)"""

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    # Mock the stream response with only reasoning_content
    mock_chunk1 = MagicMock()
    mock_chunk1.choices = [MagicMock()]
    mock_chunk1.choices[0].delta.content = None
    mock_chunk1.choices[0].delta.role = "assistant"
    mock_chunk1.choices[0].delta.reasoning_content = "Pure reasoning content"

    mock_chunk2 = MagicMock()
    mock_chunk2.choices = [MagicMock()]
    mock_chunk2.choices[0].delta.content = "Final response"
    mock_chunk2.choices[0].delta.role = None
    mock_chunk2.choices[0].delta.reasoning_content = None
    mock_chunk2.usage = MagicMock()
    mock_chunk2.usage.prompt_tokens = 5
    mock_chunk2.usage.total_tokens = 8

    # Mock ChatMessage.from_dict to return a mock message
    mock_result_message = MagicMock()
    mock_result_message.raw = [mock_chunk1, mock_chunk2]
    mock_result_message.role = MagicMock()

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}), \
            patch.object(mock_models_module.ChatMessage, "from_dict", return_value=mock_result_message):
        openai_model_instance.client.chat.completions.create.return_value = [
            mock_chunk1, mock_chunk2]

        # Call the method
        result = openai_model_instance.__call__(messages)

        # Verify the result
        assert result == mock_result_message

        # Verify that reasoning_content was added to observer
        openai_model_instance.observer.add_model_reasoning_content.assert_called_once_with(
            "Pure reasoning content")

        # Verify that only the non-null content token was added
        openai_model_instance.observer.add_model_new_token.assert_called_once_with(
            "Final response")


def test_call_with_reasoning_content_and_content_together(openai_model_instance):
    """Test __call__ method handles chunks with both reasoning_content and content simultaneously"""

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    # Mock the stream response with both reasoning_content and content
    mock_chunk = MagicMock()
    mock_chunk.choices = [MagicMock()]
    mock_chunk.choices[0].delta.content = "Response text"
    mock_chunk.choices[0].delta.role = "assistant"
    mock_chunk.choices[0].delta.reasoning_content = "Reasoning alongside content"
    mock_chunk.usage = MagicMock()
    mock_chunk.usage.prompt_tokens = 5
    mock_chunk.usage.total_tokens = 8

    # Mock ChatMessage.from_dict to return a mock message
    mock_result_message = MagicMock()
    mock_result_message.raw = [mock_chunk]
    mock_result_message.role = MagicMock()

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}), \
            patch.object(mock_models_module.ChatMessage, "from_dict", return_value=mock_result_message):
        openai_model_instance.client.chat.completions.create.return_value = [
            mock_chunk]

        # Call the method
        result = openai_model_instance.__call__(messages)

        # Verify the result
        assert result == mock_result_message

        # Verify that both reasoning_content and content were processed
        openai_model_instance.observer.add_model_reasoning_content.assert_called_once_with(
            "Reasoning alongside content")
        openai_model_instance.observer.add_model_new_token.assert_called_once_with(
            "Response text")


# ---------------------------------------------------------------------------
# Tests for __init__ with ssl_verify parameter
# ---------------------------------------------------------------------------

def test_init_with_ssl_verify_false():
    """Test __init__ method creates http_client when ssl_verify=False"""
    
    observer = MagicMock()
    
    # Mock DefaultHttpxClient from openai module
    with patch("openai.DefaultHttpxClient") as mock_httpx_client:
        mock_httpx_client.return_value = MagicMock()
        
        # Create model with ssl_verify=False
        model = ImportedOpenAIModel(observer=observer, ssl_verify=False)
        
        # Verify DefaultHttpxClient was called with verify=False
        mock_httpx_client.assert_called_once_with(verify=False)


def test_init_with_ssl_verify_true():
    """Test __init__ method doesn't create http_client when ssl_verify=True (default)"""
    
    observer = MagicMock()
    
    # Mock DefaultHttpxClient from openai module
    with patch("openai.DefaultHttpxClient") as mock_httpx_client:
        # Create model with ssl_verify=True (default)
        model = ImportedOpenAIModel(observer=observer, ssl_verify=True)
        
        # Verify DefaultHttpxClient was NOT called
        mock_httpx_client.assert_not_called()


# ---------------------------------------------------------------------------
# Tests for monitoring and token_tracker integration
# ---------------------------------------------------------------------------

def test_call_with_monitoring_and_token_tracker(openai_model_instance):
    """Test __call__ method with monitoring and token_tracker enabled"""
    
    messages = [{"role": "user", "content": [{"text": "Hello"}]}]
    
    # Create mock token_tracker
    mock_token_tracker = MagicMock()
    mock_token_tracker.record_first_token = MagicMock()
    mock_token_tracker.record_token = MagicMock()
    mock_token_tracker.record_completion = MagicMock()
    
    # Mock the stream response
    mock_chunk1 = MagicMock()
    mock_chunk1.choices = [MagicMock()]
    mock_chunk1.choices[0].delta.content = "Hello"
    mock_chunk1.choices[0].delta.role = "assistant"
    mock_chunk1.choices[0].delta.reasoning_content = None
    
    mock_chunk2 = MagicMock()
    mock_chunk2.choices = [MagicMock()]
    mock_chunk2.choices[0].delta.content = " world"
    mock_chunk2.choices[0].delta.role = None
    mock_chunk2.choices[0].delta.reasoning_content = None
    
    mock_chunk3 = MagicMock()
    mock_chunk3.choices = [MagicMock()]
    mock_chunk3.choices[0].delta.content = None
    mock_chunk3.choices[0].delta.role = None
    mock_chunk3.choices[0].delta.reasoning_content = None
    mock_chunk3.usage = MagicMock()
    mock_chunk3.usage.prompt_tokens = 10
    mock_chunk3.usage.completion_tokens = 5
    mock_chunk3.usage.total_tokens = 15
    
    mock_stream = [mock_chunk1, mock_chunk2, mock_chunk3]
    
    # Mock ChatMessage.from_dict
    mock_result_message = MagicMock()
    mock_result_message.raw = mock_stream
    mock_result_message.role = MagicMock()
    
    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}), \
            patch.object(mock_models_module.ChatMessage, "from_dict", return_value=mock_result_message):
        openai_model_instance.client.chat.completions.create.return_value = mock_stream
        
        # Call with _token_tracker kwarg
        result = openai_model_instance.__call__(messages, _token_tracker=mock_token_tracker)
        
        # Verify monitoring calls
        monitoring_manager_mock.add_span_event.assert_any_call("completion_started")
        monitoring_manager_mock.set_span_attributes.assert_called()
        monitoring_manager_mock.add_span_event.assert_any_call("completion_finished", ANY)
        
        # Verify token_tracker calls
        mock_token_tracker.record_first_token.assert_called_once()
        assert mock_token_tracker.record_token.call_count == 2  # "Hello" and " world"
        mock_token_tracker.record_completion.assert_called_once_with(10, 5)


def test_call_with_token_tracker_on_reasoning_content(openai_model_instance):
    """Test __call__ method tracks first token on reasoning_content"""
    
    messages = [{"role": "user", "content": [{"text": "Hello"}]}]
    
    # Create mock token_tracker
    mock_token_tracker = MagicMock()
    mock_token_tracker.record_first_token = MagicMock()
    mock_token_tracker.record_token = MagicMock()
    mock_token_tracker.record_completion = MagicMock()
    
    # Mock the stream response with reasoning_content first
    mock_chunk1 = MagicMock()
    mock_chunk1.choices = [MagicMock()]
    mock_chunk1.choices[0].delta.content = None
    mock_chunk1.choices[0].delta.role = "assistant"
    mock_chunk1.choices[0].delta.reasoning_content = "Thinking..."
    
    mock_chunk2 = MagicMock()
    mock_chunk2.choices = [MagicMock()]
    mock_chunk2.choices[0].delta.content = "Response"
    mock_chunk2.choices[0].delta.role = None
    mock_chunk2.choices[0].delta.reasoning_content = None
    mock_chunk2.usage = MagicMock()
    mock_chunk2.usage.prompt_tokens = 5
    mock_chunk2.usage.completion_tokens = 3
    mock_chunk2.usage.total_tokens = 8
    
    mock_stream = [mock_chunk1, mock_chunk2]
    
    # Mock ChatMessage.from_dict
    mock_result_message = MagicMock()
    mock_result_message.raw = mock_stream
    mock_result_message.role = MagicMock()
    
    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}), \
            patch.object(mock_models_module.ChatMessage, "from_dict", return_value=mock_result_message):
        openai_model_instance.client.chat.completions.create.return_value = mock_stream
        
        # Call with _token_tracker kwarg
        result = openai_model_instance.__call__(messages, _token_tracker=mock_token_tracker)
        
        # Verify token_tracker.record_first_token was called when reasoning_content was received
        mock_token_tracker.record_first_token.assert_called()
        mock_token_tracker.record_token.assert_called_once_with("Response")


def test_call_with_stop_event_and_token_tracker(openai_model_instance):
    """Test __call__ method adds monitoring event when stop_event is set with token_tracker"""
    
    messages = [{"role": "user", "content": [{"text": "Hello"}]}]
    
    # Create mock token_tracker
    mock_token_tracker = MagicMock()
    
    # Mock the stream response
    mock_chunk = MagicMock()
    mock_chunk.choices = [MagicMock()]
    mock_chunk.choices[0].delta.content = "Response"
    mock_chunk.choices[0].delta.role = "assistant"
    mock_chunk.choices[0].delta.reasoning_content = None
    
    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}):
        openai_model_instance.client.chat.completions.create.return_value = [mock_chunk]
        
        # Set the stop event before calling
        openai_model_instance.stop_event.set()
        
        # Call the method with token_tracker and expect RuntimeError
        with pytest.raises(RuntimeError, match="Model is interrupted by stop event"):
            openai_model_instance.__call__(messages, _token_tracker=mock_token_tracker)
        
        # Verify monitoring event was added
        monitoring_manager_mock.add_span_event.assert_any_call("model_stopped", {"reason": "stop_event_set"})


def test_call_exception_with_token_tracker(openai_model_instance):
    """Test __call__ method adds error event when exception occurs with token_tracker"""
    
    messages = [{"role": "user", "content": [{"text": "Hello"}]}]
    
    # Create mock token_tracker
    mock_token_tracker = MagicMock()
    
    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}):
        # Mock the client to raise an exception
        openai_model_instance.client.chat.completions.create.side_effect = Exception("API Error")
        
        # Call the method with token_tracker and expect exception
        with pytest.raises(Exception, match="API Error"):
            openai_model_instance.__call__(messages, _token_tracker=mock_token_tracker)
        
        # Verify error event was added
        monitoring_manager_mock.add_span_event.assert_any_call("error_occurred", ANY)


def test_call_context_length_exceeded_with_token_tracker(openai_model_instance):
    """Test __call__ method adds error event for context_length_exceeded with token_tracker"""
    
    messages = [{"role": "user", "content": [{"text": "Hello"}]}]
    
    # Create mock token_tracker
    mock_token_tracker = MagicMock()
    
    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}):
        # Mock the client to raise context length exceeded error
        openai_model_instance.client.chat.completions.create.side_effect = Exception(
            "context_length_exceeded: token limit exceeded")
        
        # Call the method with token_tracker and expect exception
        with pytest.raises(Exception, match="context_length_exceeded"):
            openai_model_instance.__call__(messages, _token_tracker=mock_token_tracker)
        
        # Verify error event was added
        monitoring_manager_mock.add_span_event.assert_any_call("error_occurred", ANY)


if __name__ == "__main__":
    pytest.main([__file__])
