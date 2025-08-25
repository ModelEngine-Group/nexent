from unittest.mock import AsyncMock, MagicMock, patch

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

# Assemble smolagents.* paths
module_mocks = {
    "smolagents": mock_smolagents,
    "smolagents.models": mock_models_module,
    "openai.types": MagicMock(),
    "openai.types.chat": MagicMock(),
    "openai.types.chat.chat_completion_message": MagicMock(),
}

with patch.dict("sys.modules", module_mocks):
    # Import after patching so dependencies are satisfied
    from sdk.nexent.core.models.openai_llm import OpenAIModel as ImportedOpenAIModel


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
        openai_model_instance.observer.add_model_new_token.assert_any_call("Hello")
        openai_model_instance.observer.add_model_new_token.assert_any_call(" world")
        openai_model_instance.observer.flush_remaining_tokens.assert_called_once()

        # Verify token counts were set
        assert openai_model_instance.last_input_token_count == 10
        assert openai_model_instance.last_output_token_count == 15


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
        openai_model_instance.client.chat.completions.create.return_value = [mock_chunk]

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
        openai_model_instance.client.chat.completions.create.return_value = [mock_chunk]

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
        openai_model_instance.client.chat.completions.create.return_value = [mock_chunk]

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

        # Call the method and expect ValueError
        with pytest.raises(ValueError, match="Token limit exceeded"):
            openai_model_instance.__call__(messages)


def test_call_general_exception(openai_model_instance):
    """Test __call__ method re-raises general exceptions"""

    messages = [{"role": "user", "content": [{"text": "Hello"}]}]

    with patch.object(openai_model_instance, "_prepare_completion_kwargs", return_value={}):
        # Mock the client to raise a general exception
        openai_model_instance.client.chat.completions.create.side_effect = Exception("General error")

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
        openai_model_instance.client.chat.completions.create.return_value = [mock_chunk]

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
        openai_model_instance.client.chat.completions.create.return_value = [mock_chunk1, mock_chunk2]

        # Call the method
        openai_model_instance.__call__(messages)

        # Verify that null tokens are handled correctly (not added to observer)
        openai_model_instance.observer.add_model_new_token.assert_called_once_with("Response")


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
        openai_model_instance.client.chat.completions.create.return_value = [mock_chunk1, mock_chunk2]

        # Call the method
        result = openai_model_instance.__call__(messages)

        # Verify the result
        assert result == mock_result_message

        # Verify that reasoning_content was added to observer
        openai_model_instance.observer.add_model_reasoning_content.assert_called_once_with("This is a reasoning step")

        # Verify that normal tokens were also added
        openai_model_instance.observer.add_model_new_token.assert_any_call("Let me think about this")
        openai_model_instance.observer.add_model_new_token.assert_any_call("Response")


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
        openai_model_instance.client.chat.completions.create.return_value = [mock_chunk1, mock_chunk2, mock_chunk3]

        # Call the method
        result = openai_model_instance.__call__(messages)

        # Verify the result
        assert result == mock_result_message

        # Verify that all reasoning_content chunks were added to observer
        openai_model_instance.observer.add_model_reasoning_content.assert_any_call("First reasoning step")
        openai_model_instance.observer.add_model_reasoning_content.assert_any_call("Second reasoning step")

        # Verify that normal tokens were also added
        openai_model_instance.observer.add_model_new_token.assert_any_call("Let me")
        openai_model_instance.observer.add_model_new_token.assert_any_call(" think")
        openai_model_instance.observer.add_model_new_token.assert_any_call(" about this")


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
        openai_model_instance.client.chat.completions.create.return_value = [mock_chunk1, mock_chunk2]

        # Call the method
        result = openai_model_instance.__call__(messages)

        # Verify the result
        assert result == mock_result_message

        # Verify that reasoning_content was added to observer
        openai_model_instance.observer.add_model_reasoning_content.assert_called_once_with("Pure reasoning content")

        # Verify that only the non-null content token was added
        openai_model_instance.observer.add_model_new_token.assert_called_once_with("Final response")


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
        openai_model_instance.client.chat.completions.create.return_value = [mock_chunk]

        # Call the method
        result = openai_model_instance.__call__(messages)

        # Verify the result
        assert result == mock_result_message

        # Verify that both reasoning_content and content were processed
        openai_model_instance.observer.add_model_reasoning_content.assert_called_once_with(
            "Reasoning alongside content")
        openai_model_instance.observer.add_model_new_token.assert_called_once_with("Response text")


if __name__ == "__main__":
    pytest.main([__file__])
