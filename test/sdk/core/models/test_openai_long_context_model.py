import pytest
import sys
from unittest.mock import MagicMock, patch

mock_smolagents = MagicMock()
mock_models_module = MagicMock()


class MockOpenAIServerModel:
    def __init__(self, *args, **kwargs):
        pass


class MockChatMessage:
    def __init__(self, content="", role="user"):
        self.content = content
        self.role = role
        self.raw = MagicMock()


mock_models_module.OpenAIServerModel = MockOpenAIServerModel
mock_models_module.ChatMessage = MockChatMessage
mock_smolagents.models = mock_models_module

with patch.dict("sys.modules", {
    "smolagents": mock_smolagents,
    "smolagents.models": mock_models_module,
}):
    import sdk.nexent.core.models.openai_long_context_model as openai_long_context_model
    from sdk.nexent.core.utils.observer import MessageObserver


@pytest.fixture
def mock_observer():
    return MagicMock(spec=MessageObserver)


@pytest.fixture
def long_context_model(mock_observer):
    model = openai_long_context_model.OpenAILongContextModel(
        observer=mock_observer,
        temperature=0.5,
        top_p=0.95,
        max_context_tokens=128000,
        truncation_strategy="start"
    )
    model.model_id = "test-model"
    return model


@pytest.fixture
def mock_tokenizer():
    mock_enc = MagicMock()
    mock_enc.encode.return_value = list(range(1, 11))
    mock_enc.decode.return_value = "decoded text"
    return mock_enc


def test_init_default_values(mock_observer):
    model = openai_long_context_model.OpenAILongContextModel(observer=mock_observer)
    assert model.max_context_tokens == 128000
    assert model.truncation_strategy == "start"
    assert model._tokenizer is None


def test_init_custom_values(mock_observer):
    model = openai_long_context_model.OpenAILongContextModel(observer=mock_observer, max_context_tokens=64000, truncation_strategy="middle")
    assert model.max_context_tokens == 64000
    assert model.truncation_strategy == "middle"


def test_init_invalid_truncation_strategy(mock_observer):
    with pytest.raises(ValueError, match="truncation_strategy must be 'start', 'middle' or 'end'"):
        openai_long_context_model.OpenAILongContextModel(observer=mock_observer, truncation_strategy="invalid")


def test_get_tokenizer_success(long_context_model, mock_tokenizer):
    with patch.object(long_context_model, '_get_tokenizer', return_value=mock_tokenizer):
        result = long_context_model._get_tokenizer()
        assert result == mock_tokenizer


def test_get_tokenizer_import_error(long_context_model):
    with patch.object(long_context_model, '_get_tokenizer', return_value=None):
        result = long_context_model._get_tokenizer()
        assert result is None


def test_get_tokenizer_cached(long_context_model, mock_tokenizer):
    long_context_model._tokenizer = mock_tokenizer
    assert long_context_model._get_tokenizer() == mock_tokenizer


def test_count_tokens_with_tiktoken(long_context_model, mock_tokenizer):
    with patch.object(long_context_model, '_get_tokenizer', return_value=mock_tokenizer):
        mock_tokenizer.encode.return_value = [1, 2, 3, 4, 5]
        assert long_context_model.count_tokens("test text") == 5


def test_count_tokens_without_tiktoken(long_context_model):
    long_context_model._tokenizer = None
    with patch.object(long_context_model, '_get_tokenizer', return_value=None):
        result = long_context_model.count_tokens("a" * 20)
        assert result == 5


def test_truncate_text_no_truncation_needed(long_context_model):
    long_context_model.count_tokens = MagicMock(return_value=10)
    assert long_context_model.truncate_text("short text", 20) == "short text"


@patch.object(openai_long_context_model.logging, "getLogger")
def test_truncate_text_start_strategy_with_tiktoken(mock_logger, long_context_model, mock_tokenizer):
    with patch.object(long_context_model, '_get_tokenizer', return_value=mock_tokenizer):
        long_context_model.count_tokens = MagicMock(return_value=100)
        mock_tokenizer.encode.return_value = list(range(1, 11))
        assert long_context_model.truncate_text("long text", 5) == "decoded text"


@patch.object(openai_long_context_model.logging, "getLogger")
def test_truncate_text_middle_strategy_with_tiktoken(mock_logger, long_context_model, mock_tokenizer):
    with patch.object(long_context_model, '_get_tokenizer', return_value=mock_tokenizer):
        long_context_model.truncation_strategy = "middle"
        long_context_model.count_tokens = MagicMock(return_value=100)
        mock_tokenizer.encode.return_value = list(range(1, 11))
        long_context_model.truncate_text("long text", 6)
        mock_tokenizer.decode.assert_called_once_with([1, 2, 3, 8, 9, 10])


@patch.object(openai_long_context_model.logging, "getLogger")
def test_truncate_text_end_strategy_with_tiktoken(mock_logger, long_context_model, mock_tokenizer):
    with patch.object(long_context_model, '_get_tokenizer', return_value=mock_tokenizer):
        long_context_model.truncation_strategy = "end"
        long_context_model.count_tokens = MagicMock(return_value=100)
        mock_tokenizer.encode.return_value = list(range(1, 11))
        long_context_model.truncate_text("long text", 5)
        mock_tokenizer.decode.assert_called_once_with([6, 7, 8, 9, 10])


@patch.object(openai_long_context_model.logging, "getLogger")
def test_truncate_text_without_tiktoken_start_strategy(mock_logger, long_context_model):
    with patch.object(long_context_model, '_get_tokenizer', return_value=None):
        long_context_model.count_tokens = MagicMock(return_value=100)
        result = long_context_model.truncate_text("x" * 100, 10)
        assert result == "x" * 40


@patch.object(openai_long_context_model.logging, "getLogger")
def test_truncate_text_without_tiktoken_middle_strategy(mock_logger, long_context_model):
    with patch.object(long_context_model, '_get_tokenizer', return_value=None):
        long_context_model.truncation_strategy = "middle"
        long_context_model.count_tokens = MagicMock(return_value=100)
        result = long_context_model.truncate_text("abcdefghij" * 5, 10)
        assert "[Content truncated...]" in result


@patch.object(openai_long_context_model.logging, "getLogger")
def test_truncate_text_without_tiktoken_end_strategy(mock_logger, long_context_model):
    with patch.object(long_context_model, '_get_tokenizer', return_value=None):
        long_context_model.count_tokens = MagicMock(return_value=100)
        text = "abcdefghij" * 5
        result = long_context_model.truncate_text(text, 10)
        assert result == text[-40:]


def test_prepare_long_text_message(long_context_model):
    long_context_model.count_tokens = MagicMock(side_effect=[50, 30, 1000, 800])
    long_context_model.truncate_text = MagicMock(return_value="truncated content")
    messages, truncation_percentage = long_context_model.prepare_long_text_message("very long content", "system prompt", "user prompt")
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert "truncated content" in messages[1]["content"]
    assert isinstance(truncation_percentage, str)


def test_prepare_long_text_message_no_truncation_needed(long_context_model):
    long_context_model.count_tokens = MagicMock(side_effect=[50, 30, 100, 100])
    long_context_model.truncate_text = MagicMock(return_value="original content")
    messages, truncation_percentage = long_context_model.prepare_long_text_message("short content", "system prompt", "user prompt")
    assert len(messages) == 2
    long_context_model.truncate_text.assert_called_once()
    assert isinstance(truncation_percentage, str)


def test_analyze_long_text_exception(long_context_model):
    long_context_model.prepare_long_text_message = MagicMock(side_effect=Exception("test error"))
    with pytest.raises(Exception, match="test error"):
        long_context_model.analyze_long_text("t", "sp", "up")


def test_edge_cases(long_context_model):
    long_context_model.count_tokens = MagicMock(return_value=0)
    assert long_context_model.truncate_text("", 100) == ""

    long_context_model.count_tokens = MagicMock(return_value=10)
    assert len(long_context_model.truncate_text("test", 1)) > 0

    long_context_model.count_tokens = MagicMock(return_value=100)
    assert long_context_model.truncate_text("test", 100) == "test"


def test_token_calculation_accuracy(long_context_model):
    with patch.object(long_context_model, '_get_tokenizer', return_value=None):
        short_text = "Hello world"
        assert long_context_model.count_tokens(short_text) == len(short_text) // 4

        long_text = "This is a much longer text for estimation"
        assert long_context_model.count_tokens(long_text) == len(long_text) // 4


def test_truncation_strategies_comparison(long_context_model):
    with patch.object(long_context_model, '_get_tokenizer', return_value=None):
        long_context_model.count_tokens = MagicMock(return_value=100)
        text = "This is a very long text for truncation strategy test"

        long_context_model.truncation_strategy = "start"
        start_result = long_context_model.truncate_text(text, 10)

        long_context_model.truncation_strategy = "end"
        end_result = long_context_model.truncate_text(text, 10)

        long_context_model.truncation_strategy = "middle"
        middle_result = long_context_model.truncate_text(text, 10)

        assert start_result != end_result
        assert start_result != middle_result
        assert end_result != middle_result


def test_prepare_long_text_message_insufficient_tokens(long_context_model):
    """Test that ValueError is raised when there are insufficient tokens available"""
    # Mock count_tokens to return high values that exceed max_context_tokens
    long_context_model.count_tokens = MagicMock(side_effect=[50000, 40000, 1000])  # system + user + content
    long_context_model.max_context_tokens = 80000  # Less than required (50000 + 40000 + 100)
    
    with pytest.raises(ValueError, match="Insufficient tokens available"):
        long_context_model.prepare_long_text_message("content", "system prompt", "user prompt")
