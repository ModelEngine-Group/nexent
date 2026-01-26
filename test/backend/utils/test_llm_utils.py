import sys
import types
import pytest
from unittest.mock import MagicMock
from pytest_mock import MockFixture

# Mock boto3 and other external dependencies before importing modules under test
boto3_mock = MagicMock()
sys.modules['boto3'] = boto3_mock

elasticsearch_mock = MagicMock()
sys.modules['elasticsearch'] = elasticsearch_mock

# Create placeholder nexent package hierarchy for patching
nexent_module = types.ModuleType("nexent")
nexent_module.__path__ = []
sys.modules['nexent'] = nexent_module

storage_pkg = types.ModuleType("nexent.storage")
storage_pkg.__path__ = []
sys.modules['nexent.storage'] = storage_pkg
nexent_module.storage = storage_pkg

storage_client_factory_module = types.ModuleType("nexent.storage.storage_client_factory")
sys.modules['nexent.storage.storage_client_factory'] = storage_client_factory_module
storage_pkg.storage_client_factory = storage_client_factory_module
storage_client_factory_module.create_storage_client_from_config = MagicMock()


class _FakeMinIOStorageConfig:  # pylint: disable=too-few-public-methods
    def __init__(self, *args, **kwargs):
        pass

    def validate(self):
        return None


storage_client_factory_module.MinIOStorageConfig = _FakeMinIOStorageConfig

minio_config_module = types.ModuleType("nexent.storage.minio_config")
sys.modules['nexent.storage.minio_config'] = minio_config_module
storage_pkg.minio_config = minio_config_module
minio_config_module.MinIOStorageConfig = _FakeMinIOStorageConfig

vector_db_pkg = types.ModuleType("nexent.vector_database")
vector_db_pkg.__path__ = []
sys.modules['nexent.vector_database'] = vector_db_pkg
nexent_module.vector_database = vector_db_pkg

vector_db_es_module = types.ModuleType("nexent.vector_database.elasticsearch_core")
sys.modules['nexent.vector_database.elasticsearch_core'] = vector_db_es_module
vector_db_pkg.elasticsearch_core = vector_db_es_module
vector_db_es_module.ElasticSearchCore = MagicMock()
vector_db_es_module.Elasticsearch = MagicMock()

# Stub nexent.core.utils.observer MessageObserver used by llm_utils
observer_mod = types.ModuleType("nexent.core.utils.observer")


def _make_message_observer(*a, **k):
    return types.SimpleNamespace(
        add_model_new_token=lambda t: None,
        add_model_reasoning_content=lambda r: None,
        flush_remaining_tokens=lambda: None,
    )


observer_mod.MessageObserver = _make_message_observer
observer_mod.ProcessType = types.SimpleNamespace(MODEL_OUTPUT_CODE=types.SimpleNamespace(value="model_output_code"),
                                                 MODEL_OUTPUT_THINKING=types.SimpleNamespace(
                                                     value="model_output_thinking"))
sys.modules["nexent.core.utils.observer"] = observer_mod

# Minimal nexent.core.models.OpenAIModel stub to satisfy imports (tests will patch behavior)
models_mod = types.ModuleType("nexent.core.models")


class _SimpleOpenAIModel:
    def __init__(self, *a, **k):
        self.client = MagicMock()
        self.model_id = k.get("model_id", "")

    def _prepare_completion_kwargs(self, *a, **k):
        return {}


models_mod.OpenAIModel = _SimpleOpenAIModel
sys.modules["nexent.core.models"] = models_mod

# Ensure backend.database.client modules exist before patching
import backend.database.client  # noqa: E402,F401
import database.client  # noqa: E402,F401

from backend.utils.llm_utils import call_llm_for_system_prompt, _process_thinking_tokens


class TestCallLLMForSystemPrompt:
    def test_call_llm_for_system_prompt_success(self, mocker: MockFixture):
        mock_get_model_by_id = mocker.patch('backend.utils.llm_utils.get_model_by_model_id')
        mock_get_model_name = mocker.patch('backend.utils.llm_utils.get_model_name_from_config')
        mock_openai = mocker.patch('backend.utils.llm_utils.OpenAIModel')

        mock_model_config = {
            "base_url": "http://example.com",
            "api_key": "fake-key",
            "model_factory": "qwen",
        }
        mock_get_model_by_id.return_value = mock_model_config
        mock_get_model_name.return_value = "gpt-4"

        mock_llm_instance = mock_openai.return_value
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = "Generated prompt"

        mock_llm_instance.client = MagicMock()
        mock_llm_instance.client.chat.completions.create.return_value = [mock_chunk]
        mock_llm_instance._prepare_completion_kwargs.return_value = {}

        result = call_llm_for_system_prompt(
            1,
            "user prompt",
            "system prompt",
        )

        assert result == "Generated prompt"
        mock_get_model_by_id.assert_called_once_with(
            model_id=1,
            tenant_id=None,
        )
        mock_openai.assert_called_once_with(
            model_id="gpt-4",
            api_base="http://example.com",
            model_factory="qwen",
            api_key="fake-key",
            temperature=0.3,
            top_p=0.95,
            ssl_verify=True,
        )

    def test_call_llm_for_system_prompt_exception(self, mocker: MockFixture):
        mock_get_model_by_id = mocker.patch('backend.utils.llm_utils.get_model_by_model_id')
        mock_get_model_name = mocker.patch('backend.utils.llm_utils.get_model_name_from_config')
        mock_openai = mocker.patch('backend.utils.llm_utils.OpenAIModel')

        mock_model_config = {
            "base_url": "http://example.com",
            "api_key": "fake-key",
        }
        mock_get_model_by_id.return_value = mock_model_config
        mock_get_model_name.return_value = "gpt-4"

        mock_llm_instance = mock_openai.return_value
        mock_llm_instance.client = MagicMock()
        mock_llm_instance.client.chat.completions.create.side_effect = Exception("LLM error")
        mock_llm_instance._prepare_completion_kwargs.return_value = {}

        with pytest.raises(Exception) as exc_info:
            call_llm_for_system_prompt(
                1,
                "user prompt",
                "system prompt",
            )

        assert "LLM error" in str(exc_info.value)


class TestProcessThinkingTokens:
    def test_process_thinking_tokens_normal_token(self):
        token_join = []
        callback_calls = []

        def mock_callback(text):
            callback_calls.append(text)

        is_thinking = _process_thinking_tokens("Hello", False, token_join, mock_callback)

        assert is_thinking is False
        assert token_join == ["Hello"]
        assert callback_calls == ["Hello"]

    def test_process_thinking_tokens_start_thinking(self):
        token_join = []
        callback_calls = []

        def mock_callback(text):
            callback_calls.append(text)

        is_thinking = _process_thinking_tokens("<think>", False, token_join, mock_callback)

        assert is_thinking is True
        assert token_join == []
        assert callback_calls == []

    def test_process_thinking_tokens_content_while_thinking(self):
        token_join = ["Hello"]
        callback_calls = []

        def mock_callback(text):
            callback_calls.append(text)

        is_thinking = _process_thinking_tokens(
            "thinking content",
            True,
            token_join,
            mock_callback,
        )

        assert is_thinking is True
        assert token_join == ["Hello"]
        assert callback_calls == []

    def test_process_thinking_tokens_end_thinking(self):
        token_join = ["Hello"]
        callback_calls = []

        def mock_callback(text):
            callback_calls.append(text)

        is_thinking = _process_thinking_tokens("</think>", True, token_join, mock_callback)

        assert is_thinking is False
        assert token_join == ["Hello"]
        assert callback_calls == []

    def test_process_thinking_tokens_content_after_thinking(self):
        token_join = ["Hello"]
        callback_calls = []

        def mock_callback(text):
            callback_calls.append(text)

        is_thinking = _process_thinking_tokens("World", False, token_join, mock_callback)

        assert is_thinking is False
        assert token_join == ["Hello", "World"]
        assert callback_calls == ["HelloWorld"]

    def test_process_thinking_tokens_complete_flow(self):
        token_join = []
        callback_calls = []

        def mock_callback(text):
            callback_calls.append(text)

        is_thinking = _process_thinking_tokens("Start ", False, token_join, mock_callback)
        assert is_thinking is False

        is_thinking = _process_thinking_tokens("<think>", False, token_join, mock_callback)
        assert is_thinking is True

        is_thinking = _process_thinking_tokens("thinking", True, token_join, mock_callback)
        assert is_thinking is True

        is_thinking = _process_thinking_tokens(" more", True, token_join, mock_callback)
        assert is_thinking is True

        is_thinking = _process_thinking_tokens("</think>", True, token_join, mock_callback)
        assert is_thinking is False

        is_thinking = _process_thinking_tokens(" End", False, token_join, mock_callback)
        assert is_thinking is False

        assert token_join == ["Start ", " End"]
        assert callback_calls == ["Start ", "Start  End"]

    def test_process_thinking_tokens_no_callback(self):
        token_join = []

        is_thinking = _process_thinking_tokens("Hello", False, token_join, None)

        assert is_thinking is False
        assert token_join == ["Hello"]

    def test_process_thinking_tokens_empty_token(self):
        token_join = []
        callback_calls = []

        def mock_callback(text):
            callback_calls.append(text)

        is_thinking = _process_thinking_tokens("", False, token_join, mock_callback)

        assert is_thinking is False
        assert token_join == []
        assert callback_calls == []

    def test_process_thinking_tokens_end_tag_without_starting(self):
        """Test end tag when never in thinking mode - should clear token_join"""
        token_join = ["Some", "content"]
        callback_calls = []

        def mock_callback(text):
            callback_calls.append(text)

        is_thinking = _process_thinking_tokens("</think>", False, token_join, mock_callback)

        assert is_thinking is False
        assert token_join == []
        assert callback_calls == [""]

    def test_process_thinking_tokens_end_tag_without_starting_no_callback(self):
        """Test end tag when never in thinking mode without callback"""
        token_join = ["Some", "content"]

        is_thinking = _process_thinking_tokens("</think>", False, token_join, None)

        assert is_thinking is False
        assert token_join == []

    def test_process_thinking_tokens_end_tag_with_content_after(self):
        """Test end tag followed by content in the same token"""
        token_join = ["Hello"]
        callback_calls = []

        def mock_callback(text):
            callback_calls.append(text)

        is_thinking = _process_thinking_tokens("</think>World", True, token_join, mock_callback)

        assert is_thinking is False
        assert token_join == ["Hello", "World"]
        assert callback_calls == ["HelloWorld"]

    def test_process_thinking_tokens_start_tag_with_content_after(self):
        """Test start tag followed by content in the same token"""
        token_join = ["Hello"]
        callback_calls = []

        def mock_callback(text):
            callback_calls.append(text)

        is_thinking = _process_thinking_tokens("<think>thinking", False, token_join, mock_callback)

        assert is_thinking is True
        assert token_join == ["Hello"]
        assert callback_calls == []

    def test_process_thinking_tokens_both_tags_in_same_token(self):
        """Test both start and end tags in the same token"""
        token_join = ["Hello"]
        callback_calls = []

        def mock_callback(text):
            callback_calls.append(text)

        # When both tags are in the same token, end tag is processed first
        # End tag clears token_join (since is_thinking=False), sets is_thinking=False,
        # new_token becomes "World" (content after </think>)
        # Then start tag check happens on "World", no match, so is_thinking stays False
        # Then is_thinking check returns False, so "World" is added to token_join
        is_thinking = _process_thinking_tokens(
            "<think>thinking</think>World",
            False,
            token_join,
            mock_callback,
        )

        # After processing end tag: token_join cleared, is_thinking=False, new_token="World"
        # Start tag check on "World": no match, is_thinking stays False
        # Then "World" is added to token_join
        # Note: When end tag clears token_join, callback("") is called, but empty string is not added to token_join
        assert is_thinking is False
        assert token_join == ["World"]
        assert callback_calls == ["", "World"]

    def test_process_thinking_tokens_new_token_empty_after_processing(self):
        """Test when new_token becomes empty after processing tags"""
        token_join = ["Hello"]
        callback_calls = []

        def mock_callback(text):
            callback_calls.append(text)

        # End tag with no content after
        is_thinking = _process_thinking_tokens("</think>", True, token_join, mock_callback)

        assert is_thinking is False
        assert token_join == ["Hello"]
        assert callback_calls == []


class AdditionalLLMUtilsTests:
    def test_process_thinking_tokens_append_and_callback(self):
        token_join = []
        calls = []

        def cb(text):
            calls.append(text)

        is_thinking = _process_thinking_tokens("Hello", False, token_join, cb)
        assert is_thinking is False
        assert token_join == ["Hello"]
        assert calls == ["Hello"]

    def test_process_thinking_tokens_start_tag(self):
        token_join = []
        calls = []

        def cb(text):
            calls.append(text)

        is_thinking = _process_thinking_tokens("<think>inner", False, token_join, cb)
        assert is_thinking is True
        # start tag should not append to token_join
        assert token_join == []
        assert calls == []

    def test_process_thinking_tokens_is_thinking_without_end(self):
        token_join = ["x"]
        # when already thinking and token does NOT contain end tag, should remain thinking
        is_thinking = _process_thinking_tokens("still thinking", True, token_join, None)
        assert is_thinking is True
        assert token_join == ["x"]

    def test_process_thinking_tokens_is_thinking_with_end(self):
        token_join = ["x"]
        # when already thinking and token contains end tag, should return False (stop thinking)
        is_thinking = _process_thinking_tokens("</think>done", True, token_join, None)
        assert is_thinking is False
        # token_join is not modified by the function in this code path
        assert token_join == ["x", "done"]

    def test_process_thinking_tokens_empty_token_with_callback(self):
        token_join = []
        calls = []

        def cb(text):
            calls.append(text)

        is_thinking = _process_thinking_tokens("", False, token_join, cb)
        # empty string is appended and callback is invoked with the joined token list
        assert is_thinking is False
        assert token_join == []
        assert calls == []

    def test_call_llm_for_system_prompt_skips_none_tokens_and_joins(self, mocker: MockFixture):
        # Setup model config and OpenAIModel behavior
        mock_get_model_by_id = mocker.patch('backend.utils.llm_utils.get_model_by_model_id')
        mock_get_model_name = mocker.patch('backend.utils.llm_utils.get_model_name_from_config')
        mock_openai = mocker.patch('backend.utils.llm_utils.OpenAIModel')

        mock_get_model_by_id.return_value = {"base_url": "http://x", "api_key": "k"}
        mock_get_model_name.return_value = "gpt-5"

        mock_instance = mock_openai.return_value
        # chunk1: None content (should be skipped), chunk2: actual content
        chunk1 = MagicMock()
        chunk1.choices = [MagicMock()]
        chunk1.choices[0].delta.content = None

        chunk2 = MagicMock()
        chunk2.choices = [MagicMock()]
        chunk2.choices[0].delta.content = "OK"

        mock_instance.client = MagicMock()
        mock_instance.client.chat.completions.create.return_value = [chunk1, chunk2]
        mock_instance._prepare_completion_kwargs.return_value = {}

        res = call_llm_for_system_prompt(1, "u", "s")
        assert res == "OK"
        # Ensure OpenAIModel constructed with expected args
        mock_openai.assert_called_once()

    def test_call_llm_for_system_prompt_generator_like_response(self, mocker: MockFixture):
        mock_get_model_by_id = mocker.patch('backend.utils.llm_utils.get_model_by_model_id')
        mock_get_model_name = mocker.patch('backend.utils.llm_utils.get_model_name_from_config')
        mock_openai = mocker.patch('backend.utils.llm_utils.OpenAIModel')

        mock_get_model_by_id.return_value = {"base_url": "http://y", "api_key": "k2"}
        mock_get_model_name.return_value = "gpt-6"

        mock_instance = mock_openai.return_value

        # Provide an object that is iterable (generator-like)
        def gen():
            for txt in ("A", "B", None, "C"):
                ch = MagicMock()
                ch.choices = [MagicMock()]
                ch.choices[0].delta.content = txt
                yield ch

        mock_instance.client = MagicMock()
        mock_instance.client.chat.completions.create.return_value = gen()
        mock_instance._prepare_completion_kwargs.return_value = {}

        res = call_llm_for_system_prompt(2, "u2", "s2")
        assert res == "ABC"

    def test_call_llm_for_system_prompt_with_callback(self, mocker: MockFixture):
        """Test call_llm_for_system_prompt with callback"""
        mock_get_model_by_id = mocker.patch('backend.utils.llm_utils.get_model_by_model_id')
        mock_get_model_name = mocker.patch('backend.utils.llm_utils.get_model_name_from_config')
        mock_openai = mocker.patch('backend.utils.llm_utils.OpenAIModel')

        mock_get_model_by_id.return_value = {"base_url": "http://example.com", "api_key": "fake-key"}
        mock_get_model_name.return_value = "gpt-4"

        mock_llm_instance = mock_openai.return_value
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = "Generated prompt"

        mock_llm_instance.client = MagicMock()
        mock_llm_instance.client.chat.completions.create.return_value = [mock_chunk]
        mock_llm_instance._prepare_completion_kwargs.return_value = {}

        callback_calls = []

        def mock_callback(text):
            callback_calls.append(text)

        result = call_llm_for_system_prompt(
            1,
            "user prompt",
            "system prompt",
            callback=mock_callback,
        )

        assert result == "Generated prompt"
        assert len(callback_calls) == 1
        assert callback_calls[0] == "Generated prompt"

    def test_call_llm_for_system_prompt_with_reasoning_content(self, mocker: MockFixture):
        """Test call_llm_for_system_prompt with reasoning_content"""
        mock_get_model_by_id = mocker.patch('backend.utils.llm_utils.get_model_by_model_id')
        mock_get_model_name = mocker.patch('backend.utils.llm_utils.get_model_name_from_config')
        mock_openai = mocker.patch('backend.utils.llm_utils.OpenAIModel')

        mock_get_model_by_id.return_value = {"base_url": "http://example.com", "api_key": "fake-key"}
        mock_get_model_name.return_value = "gpt-4"

        mock_llm_instance = mock_openai.return_value
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = "Generated prompt"
        mock_chunk.choices[0].delta.reasoning_content = "Some reasoning"

        mock_llm_instance.client = MagicMock()
        mock_llm_instance.client.chat.completions.create.return_value = [mock_chunk]
        mock_llm_instance._prepare_completion_kwargs.return_value = {}

        result = call_llm_for_system_prompt(
            1,
            "user prompt",
            "system prompt",
        )

        assert result == "Generated prompt"

    def test_call_llm_for_system_prompt_multiple_chunks(self, mocker: MockFixture):
        """Test call_llm_for_system_prompt with multiple chunks"""
        mock_get_model_by_id = mocker.patch('backend.utils.llm_utils.get_model_by_model_id')
        mock_get_model_name = mocker.patch('backend.utils.llm_utils.get_model_name_from_config')
        mock_openai = mocker.patch('backend.utils.llm_utils.OpenAIModel')

        mock_get_model_by_id.return_value = {"base_url": "http://example.com", "api_key": "fake-key"}
        mock_get_model_name.return_value = "gpt-4"

        mock_llm_instance = mock_openai.return_value
        mock_chunk1 = MagicMock()
        mock_chunk1.choices = [MagicMock()]
        mock_chunk1.choices[0].delta.content = "Generated "
        mock_chunk1.choices[0].delta.reasoning_content = None

        mock_chunk2 = MagicMock()
        mock_chunk2.choices = [MagicMock()]
        mock_chunk2.choices[0].delta.content = "prompt"
        mock_chunk2.choices[0].delta.reasoning_content = None

        mock_llm_instance.client = MagicMock()
        mock_llm_instance.client.chat.completions.create.return_value = [mock_chunk1, mock_chunk2]
        mock_llm_instance._prepare_completion_kwargs.return_value = {}

        result = call_llm_for_system_prompt(
            1,
            "user prompt",
            "system prompt",
        )

        assert result == "Generated prompt"

    def test_call_llm_for_system_prompt_with_none_content(self, mocker: MockFixture):
        """Test call_llm_for_system_prompt with delta.content as None"""
        mock_get_model_by_id = mocker.patch('backend.utils.llm_utils.get_model_by_model_id')
        mock_get_model_name = mocker.patch('backend.utils.llm_utils.get_model_name_from_config')
        mock_openai = mocker.patch('backend.utils.llm_utils.OpenAIModel')

        mock_get_model_by_id.return_value = {"base_url": "http://example.com", "api_key": "fake-key"}
        mock_get_model_name.return_value = "gpt-4"

        mock_llm_instance = mock_openai.return_value
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = None
        mock_chunk.choices[0].delta.reasoning_content = "Some reasoning"

        mock_llm_instance.client = MagicMock()
        mock_llm_instance.client.chat.completions.create.return_value = [mock_chunk]
        mock_llm_instance._prepare_completion_kwargs.return_value = {}

        result = call_llm_for_system_prompt(
            1,
            "user prompt",
            "system prompt",
        )

        assert result == ""

    def test_call_llm_for_system_prompt_with_thinking_tags(self, mocker: MockFixture):
        """Test call_llm_for_system_prompt with thinking tags"""
        mock_get_model_by_id = mocker.patch('backend.utils.llm_utils.get_model_by_model_id')
        mock_get_model_name = mocker.patch('backend.utils.llm_utils.get_model_name_from_config')
        mock_openai = mocker.patch('backend.utils.llm_utils.OpenAIModel')

        mock_get_model_by_id.return_value = {"base_url": "http://example.com", "api_key": "fake-key"}
        mock_get_model_name.return_value = "gpt-4"

        mock_llm_instance = mock_openai.return_value
        mock_chunk1 = MagicMock()
        mock_chunk1.choices = [MagicMock()]
        mock_chunk1.choices[0].delta.content = "Start "
        mock_chunk1.choices[0].delta.reasoning_content = None

        mock_chunk2 = MagicMock()
        mock_chunk2.choices = [MagicMock()]
        mock_chunk2.choices[0].delta.content = "<think>thinking</think>"
        mock_chunk2.choices[0].delta.reasoning_content = None

        mock_chunk3 = MagicMock()
        mock_chunk3.choices = [MagicMock()]
        mock_chunk3.choices[0].delta.content = " End"
        mock_chunk3.choices[0].delta.reasoning_content = None

        mock_llm_instance.client = MagicMock()
        mock_llm_instance.client.chat.completions.create.return_value = [
            mock_chunk1,
            mock_chunk2,
            mock_chunk3,
        ]
        mock_llm_instance._prepare_completion_kwargs.return_value = {}

        result = call_llm_for_system_prompt(
            1,
            "user prompt",
            "system prompt",
        )

        # chunk1: "Start " -> added to token_join
        # chunk2: "<think>thinking</think>" ->
        #   end tag clears token_join (since is_thinking=False), new_token becomes ""
        # chunk3: " End" -> added to token_join
        # Final result should be " End" (chunk1 content was cleared by chunk2's end tag)
        assert result == " End"

    def test_call_llm_for_system_prompt_empty_result_with_tokens(self, mocker: MockFixture):
        """Test call_llm_for_system_prompt with empty result but processed tokens"""
        mock_logger = mocker.patch('backend.utils.llm_utils.logger')
        mock_get_model_by_id = mocker.patch('backend.utils.llm_utils.get_model_by_model_id')
        mock_get_model_name = mocker.patch('backend.utils.llm_utils.get_model_name_from_config')
        mock_openai = mocker.patch('backend.utils.llm_utils.OpenAIModel')

        mock_get_model_by_id.return_value = {"base_url": "http://example.com", "api_key": "fake-key"}
        mock_get_model_name.return_value = "gpt-4"

        mock_llm_instance = mock_openai.return_value
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        # Content that will be filtered out by thinking tags
        mock_chunk.choices[0].delta.content = "<think>all content</think>"
        mock_chunk.choices[0].delta.reasoning_content = None

        mock_llm_instance.client = MagicMock()
        mock_llm_instance.client.chat.completions.create.return_value = [mock_chunk]
        mock_llm_instance._prepare_completion_kwargs.return_value = {}

        result = call_llm_for_system_prompt(
            1,
            "user prompt",
            "system prompt",
        )

        assert result == ""
        # Verify warning was logged
        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args[0][0]
        assert "empty but" in call_args
        assert "content tokens were processed" in call_args

    def test_call_llm_for_system_prompt_with_tenant_id(self, mocker: MockFixture):
        """Test call_llm_for_system_prompt with tenant_id"""
        mock_get_model_by_id = mocker.patch('backend.utils.llm_utils.get_model_by_model_id')
        mock_get_model_name = mocker.patch('backend.utils.llm_utils.get_model_name_from_config')
        mock_openai = mocker.patch('backend.utils.llm_utils.OpenAIModel')

        mock_get_model_by_id.return_value = {"base_url": "http://example.com", "api_key": "fake-key"}
        mock_get_model_name.return_value = "gpt-4"

        mock_llm_instance = mock_openai.return_value
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = "Generated prompt"

        mock_llm_instance.client = MagicMock()
        mock_llm_instance.client.chat.completions.create.return_value = [mock_chunk]
        mock_llm_instance._prepare_completion_kwargs.return_value = {}

        result = call_llm_for_system_prompt(
            1,
            "user prompt",
            "system prompt",
            tenant_id="test-tenant",
        )

        assert result == "Generated prompt"
        mock_get_model_by_id.assert_called_once_with(
            model_id=1,
            tenant_id="test-tenant",
        )

    def test_call_llm_for_system_prompt_with_none_model_config(self, mocker: MockFixture):
        """Test call_llm_for_system_prompt with None model config"""
        mock_get_model_by_id = mocker.patch('backend.utils.llm_utils.get_model_by_model_id')
        mock_get_model_name = mocker.patch('backend.utils.llm_utils.get_model_name_from_config')
        mock_openai = mocker.patch('backend.utils.llm_utils.OpenAIModel')

        mock_get_model_by_id.return_value = None
        mock_get_model_name.return_value = "gpt-4"

        mock_llm_instance = mock_openai.return_value
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = "Generated prompt"

        mock_llm_instance.client = MagicMock()
        mock_llm_instance.client.chat.completions.create.return_value = [mock_chunk]
        mock_llm_instance._prepare_completion_kwargs.return_value = {}

        result = call_llm_for_system_prompt(
            1,
            "user prompt",
            "system prompt",
        )

        assert result == "Generated prompt"
        # Verify OpenAIModel was called with empty strings when model_config is None
        mock_openai.assert_called_once_with(
            model_id="",
            api_base="",
            api_key="",
            model_factory=None,
            temperature=0.3,
            top_p=0.95,
            ssl_verify=True,
        )

    def test_call_llm_for_system_prompt_reasoning_content_logging(self, mocker: MockFixture):
        """Test call_llm_for_system_prompt logs when reasoning_content is received"""
        mock_logger = mocker.patch('backend.utils.llm_utils.logger')
        mock_get_model_by_id = mocker.patch('backend.utils.llm_utils.get_model_by_model_id')
        mock_get_model_name = mocker.patch('backend.utils.llm_utils.get_model_name_from_config')
        mock_openai = mocker.patch('backend.utils.llm_utils.OpenAIModel')

        mock_get_model_by_id.return_value = {"base_url": "http://example.com", "api_key": "fake-key"}
        mock_get_model_name.return_value = "gpt-4"

        mock_llm_instance = mock_openai.return_value
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = "Generated prompt"
        mock_chunk.choices[0].delta.reasoning_content = "Some reasoning"

        mock_llm_instance.client = MagicMock()
        mock_llm_instance.client.chat.completions.create.return_value = [mock_chunk]
        mock_llm_instance._prepare_completion_kwargs.return_value = {}

        result = call_llm_for_system_prompt(
            1,
            "user prompt",
            "system prompt",
        )

        assert result == "Generated prompt"
        # Verify debug log was called for reasoning_content
        mock_logger.debug.assert_called_once()
        call_args = mock_logger.debug.call_args[0][0]
        assert "reasoning_content" in call_args

    def test_call_llm_for_system_prompt_exception_logging(self, mocker: MockFixture):
        """Test call_llm_for_system_prompt exception handling and logging"""
        mock_logger = mocker.patch('backend.utils.llm_utils.logger')
        mock_get_model_by_id = mocker.patch('backend.utils.llm_utils.get_model_by_model_id')
        mock_get_model_name = mocker.patch('backend.utils.llm_utils.get_model_name_from_config')
        mock_openai = mocker.patch('backend.utils.llm_utils.OpenAIModel')

        mock_get_model_by_id.return_value = {"base_url": "http://example.com", "api_key": "fake-key"}
        mock_get_model_name.return_value = "gpt-4"

        mock_llm_instance = mock_openai.return_value
        mock_llm_instance.client = MagicMock()
        mock_llm_instance.client.chat.completions.create.side_effect = Exception("LLM error")
        mock_llm_instance._prepare_completion_kwargs.return_value = {}

        with pytest.raises(Exception) as exc_info:
            call_llm_for_system_prompt(
                1,
                "user prompt",
                "system prompt",
            )

        assert "LLM error" in str(exc_info.value)
        # Verify error was logged
        mock_logger.error.assert_called_once()
        call_args = mock_logger.error.call_args[0][0]
        assert "Failed to generate prompt" in call_args
