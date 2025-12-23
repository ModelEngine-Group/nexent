import sys
import types
import unittest
from unittest.mock import MagicMock, patch

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

# Ensure backend.database.client modules exist before patching
import backend.database.client  # noqa: E402,F401
import database.client  # noqa: E402,F401

patch('botocore.client.BaseClient._make_api_call', return_value={}).start()

storage_client_mock = MagicMock()
minio_client_mock = MagicMock()
minio_client_mock._ensure_bucket_exists = MagicMock()
minio_client_mock.client = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config', return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
patch('backend.database.client.MinioClient', return_value=minio_client_mock).start()
patch('database.client.MinioClient', return_value=minio_client_mock).start()
patch('backend.database.client.minio_client', minio_client_mock).start()
patch('nexent.vector_database.elasticsearch_core.ElasticSearchCore', return_value=MagicMock()).start()
patch('nexent.vector_database.elasticsearch_core.Elasticsearch', return_value=MagicMock()).start()
patch('elasticsearch.Elasticsearch', return_value=MagicMock()).start()

from backend.utils.llm_utils import call_llm_for_system_prompt, _process_thinking_tokens


class TestCallLLMForSystemPrompt(unittest.TestCase):
    def setUp(self):
        self.test_model_id = 1

    @patch('backend.utils.llm_utils.OpenAIModel')
    @patch('backend.utils.llm_utils.get_model_name_from_config')
    @patch('backend.utils.llm_utils.get_model_by_model_id')
    def test_call_llm_for_system_prompt_success(
        self,
        mock_get_model_by_id,
        mock_get_model_name,
        mock_openai,
    ):
        mock_model_config = {
            "base_url": "http://example.com",
            "api_key": "fake-key",
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
            self.test_model_id,
            "user prompt",
            "system prompt",
        )

        self.assertEqual(result, "Generated prompt")
        mock_get_model_by_id.assert_called_once_with(
            model_id=self.test_model_id,
            tenant_id=None,
        )
        mock_openai.assert_called_once_with(
            model_id="gpt-4",
            api_base="http://example.com",
            api_key="fake-key",
            temperature=0.3,
            top_p=0.95,
        )

    @patch('backend.utils.llm_utils.OpenAIModel')
    @patch('backend.utils.llm_utils.get_model_name_from_config')
    @patch('backend.utils.llm_utils.get_model_by_model_id')
    def test_call_llm_for_system_prompt_exception(
        self,
        mock_get_model_by_id,
        mock_get_model_name,
        mock_openai,
    ):
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

        with self.assertRaises(Exception) as context:
            call_llm_for_system_prompt(
                self.test_model_id,
                "user prompt",
                "system prompt",
            )

        self.assertIn("LLM error", str(context.exception))


class TestProcessThinkingTokens(unittest.TestCase):
    def test_process_thinking_tokens_normal_token(self):
        token_join = []
        callback_calls = []

        def mock_callback(text):
            callback_calls.append(text)

        is_thinking = _process_thinking_tokens("Hello", False, token_join, mock_callback)

        self.assertFalse(is_thinking)
        self.assertEqual(token_join, ["Hello"])
        self.assertEqual(callback_calls, ["Hello"])

    def test_process_thinking_tokens_start_thinking(self):
        token_join = []
        callback_calls = []

        def mock_callback(text):
            callback_calls.append(text)

        is_thinking = _process_thinking_tokens("<think>", False, token_join, mock_callback)

        self.assertTrue(is_thinking)
        self.assertEqual(token_join, [])
        self.assertEqual(callback_calls, [])

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

        self.assertTrue(is_thinking)
        self.assertEqual(token_join, ["Hello"])
        self.assertEqual(callback_calls, [])

    def test_process_thinking_tokens_end_thinking(self):
        token_join = ["Hello"]
        callback_calls = []

        def mock_callback(text):
            callback_calls.append(text)

        is_thinking = _process_thinking_tokens("</think>", True, token_join, mock_callback)

        self.assertFalse(is_thinking)
        self.assertEqual(token_join, ["Hello"])
        self.assertEqual(callback_calls, [])

    def test_process_thinking_tokens_content_after_thinking(self):
        token_join = ["Hello"]
        callback_calls = []

        def mock_callback(text):
            callback_calls.append(text)

        is_thinking = _process_thinking_tokens("World", False, token_join, mock_callback)

        self.assertFalse(is_thinking)
        self.assertEqual(token_join, ["Hello", "World"])
        self.assertEqual(callback_calls, ["HelloWorld"])

    def test_process_thinking_tokens_complete_flow(self):
        token_join = []
        callback_calls = []

        def mock_callback(text):
            callback_calls.append(text)

        is_thinking = _process_thinking_tokens("Start ", False, token_join, mock_callback)
        self.assertFalse(is_thinking)

        is_thinking = _process_thinking_tokens("<think>", False, token_join, mock_callback)
        self.assertTrue(is_thinking)

        is_thinking = _process_thinking_tokens("thinking", True, token_join, mock_callback)
        self.assertTrue(is_thinking)

        is_thinking = _process_thinking_tokens(" more", True, token_join, mock_callback)
        self.assertTrue(is_thinking)

        is_thinking = _process_thinking_tokens("</think>", True, token_join, mock_callback)
        self.assertFalse(is_thinking)

        is_thinking = _process_thinking_tokens(" End", False, token_join, mock_callback)
        self.assertFalse(is_thinking)

        self.assertEqual(token_join, ["Start ", " End"])
        self.assertEqual(callback_calls, ["Start ", "Start  End"])

    def test_process_thinking_tokens_no_callback(self):
        token_join = []

        is_thinking = _process_thinking_tokens("Hello", False, token_join, None)

        self.assertFalse(is_thinking)
        self.assertEqual(token_join, ["Hello"])

    def test_process_thinking_tokens_empty_token(self):
        token_join = []
        callback_calls = []

        def mock_callback(text):
            callback_calls.append(text)

        is_thinking = _process_thinking_tokens("", False, token_join, mock_callback)

        self.assertFalse(is_thinking)
        self.assertEqual(token_join, [])
        self.assertEqual(callback_calls, [])

    def test_process_thinking_tokens_end_tag_without_starting(self):
        """Test end tag when never in thinking mode - should clear token_join"""
        token_join = ["Some", "content"]
        callback_calls = []

        def mock_callback(text):
            callback_calls.append(text)

        is_thinking = _process_thinking_tokens("</think>", False, token_join, mock_callback)

        self.assertFalse(is_thinking)
        self.assertEqual(token_join, [])
        self.assertEqual(callback_calls, [""])

    def test_process_thinking_tokens_end_tag_without_starting_no_callback(self):
        """Test end tag when never in thinking mode without callback"""
        token_join = ["Some", "content"]

        is_thinking = _process_thinking_tokens("</think>", False, token_join, None)

        self.assertFalse(is_thinking)
        self.assertEqual(token_join, [])

    def test_process_thinking_tokens_end_tag_with_content_after(self):
        """Test end tag followed by content in the same token"""
        token_join = ["Hello"]
        callback_calls = []

        def mock_callback(text):
            callback_calls.append(text)

        is_thinking = _process_thinking_tokens("</think>World", True, token_join, mock_callback)

        self.assertFalse(is_thinking)
        self.assertEqual(token_join, ["Hello", "World"])
        self.assertEqual(callback_calls, ["HelloWorld"])

    def test_process_thinking_tokens_start_tag_with_content_after(self):
        """Test start tag followed by content in the same token"""
        token_join = ["Hello"]
        callback_calls = []

        def mock_callback(text):
            callback_calls.append(text)

        is_thinking = _process_thinking_tokens("<think>thinking", False, token_join, mock_callback)

        self.assertTrue(is_thinking)
        self.assertEqual(token_join, ["Hello"])
        self.assertEqual(callback_calls, [])

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
        self.assertFalse(is_thinking)
        self.assertEqual(token_join, ["World"])
        self.assertEqual(callback_calls, ["", "World"])

    def test_process_thinking_tokens_new_token_empty_after_processing(self):
        """Test when new_token becomes empty after processing tags"""
        token_join = ["Hello"]
        callback_calls = []

        def mock_callback(text):
            callback_calls.append(text)

        # End tag with no content after
        is_thinking = _process_thinking_tokens("</think>", True, token_join, mock_callback)

        self.assertFalse(is_thinking)
        self.assertEqual(token_join, ["Hello"])
        self.assertEqual(callback_calls, [])


class TestCallLLMForSystemPromptExtended(unittest.TestCase):
    """Extended tests for call_llm_for_system_prompt to achieve 100% coverage"""

    def setUp(self):
        self.test_model_id = 1

    @patch('backend.utils.llm_utils.OpenAIModel')
    @patch('backend.utils.llm_utils.get_model_name_from_config')
    @patch('backend.utils.llm_utils.get_model_by_model_id')
    def test_call_llm_for_system_prompt_with_callback(
        self,
        mock_get_model_by_id,
        mock_get_model_name,
        mock_openai,
    ):
        """Test call_llm_for_system_prompt with callback"""
        mock_model_config = {
            "base_url": "http://example.com",
            "api_key": "fake-key",
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

        callback_calls = []

        def mock_callback(text):
            callback_calls.append(text)

        result = call_llm_for_system_prompt(
            self.test_model_id,
            "user prompt",
            "system prompt",
            callback=mock_callback,
        )

        self.assertEqual(result, "Generated prompt")
        self.assertEqual(len(callback_calls), 1)
        self.assertEqual(callback_calls[0], "Generated prompt")

    @patch('backend.utils.llm_utils.OpenAIModel')
    @patch('backend.utils.llm_utils.get_model_name_from_config')
    @patch('backend.utils.llm_utils.get_model_by_model_id')
    def test_call_llm_for_system_prompt_with_reasoning_content(
        self,
        mock_get_model_by_id,
        mock_get_model_name,
        mock_openai,
    ):
        """Test call_llm_for_system_prompt with reasoning_content"""
        mock_model_config = {
            "base_url": "http://example.com",
            "api_key": "fake-key",
        }
        mock_get_model_by_id.return_value = mock_model_config
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
            self.test_model_id,
            "user prompt",
            "system prompt",
        )

        self.assertEqual(result, "Generated prompt")

    @patch('backend.utils.llm_utils.OpenAIModel')
    @patch('backend.utils.llm_utils.get_model_name_from_config')
    @patch('backend.utils.llm_utils.get_model_by_model_id')
    def test_call_llm_for_system_prompt_multiple_chunks(
        self,
        mock_get_model_by_id,
        mock_get_model_name,
        mock_openai,
    ):
        """Test call_llm_for_system_prompt with multiple chunks"""
        mock_model_config = {
            "base_url": "http://example.com",
            "api_key": "fake-key",
        }
        mock_get_model_by_id.return_value = mock_model_config
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
            self.test_model_id,
            "user prompt",
            "system prompt",
        )

        self.assertEqual(result, "Generated prompt")

    @patch('backend.utils.llm_utils.OpenAIModel')
    @patch('backend.utils.llm_utils.get_model_name_from_config')
    @patch('backend.utils.llm_utils.get_model_by_model_id')
    def test_call_llm_for_system_prompt_with_none_content(
        self,
        mock_get_model_by_id,
        mock_get_model_name,
        mock_openai,
    ):
        """Test call_llm_for_system_prompt with delta.content as None"""
        mock_model_config = {
            "base_url": "http://example.com",
            "api_key": "fake-key",
        }
        mock_get_model_by_id.return_value = mock_model_config
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
            self.test_model_id,
            "user prompt",
            "system prompt",
        )

        self.assertEqual(result, "")

    @patch('backend.utils.llm_utils.OpenAIModel')
    @patch('backend.utils.llm_utils.get_model_name_from_config')
    @patch('backend.utils.llm_utils.get_model_by_model_id')
    def test_call_llm_for_system_prompt_with_thinking_tags(
        self,
        mock_get_model_by_id,
        mock_get_model_name,
        mock_openai,
    ):
        """Test call_llm_for_system_prompt with thinking tags"""
        mock_model_config = {
            "base_url": "http://example.com",
            "api_key": "fake-key",
        }
        mock_get_model_by_id.return_value = mock_model_config
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
            self.test_model_id,
            "user prompt",
            "system prompt",
        )

        # chunk1: "Start " -> added to token_join
        # chunk2: "<think>thinking</think>" ->
        #   end tag clears token_join (since is_thinking=False), new_token becomes ""
        # chunk3: " End" -> added to token_join
        # Final result should be " End" (chunk1 content was cleared by chunk2's end tag)
        self.assertEqual(result, " End")

    @patch('backend.utils.llm_utils.OpenAIModel')
    @patch('backend.utils.llm_utils.get_model_name_from_config')
    @patch('backend.utils.llm_utils.get_model_by_model_id')
    @patch('backend.utils.llm_utils.logger')
    def test_call_llm_for_system_prompt_empty_result_with_tokens(
        self,
        mock_logger,
        mock_get_model_by_id,
        mock_get_model_name,
        mock_openai,
    ):
        """Test call_llm_for_system_prompt with empty result but processed tokens"""
        mock_model_config = {
            "base_url": "http://example.com",
            "api_key": "fake-key",
        }
        mock_get_model_by_id.return_value = mock_model_config
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
            self.test_model_id,
            "user prompt",
            "system prompt",
        )

        self.assertEqual(result, "")
        # Verify warning was logged
        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args[0][0]
        self.assertIn("empty but", call_args)
        self.assertIn("content tokens were processed", call_args)

    @patch('backend.utils.llm_utils.OpenAIModel')
    @patch('backend.utils.llm_utils.get_model_name_from_config')
    @patch('backend.utils.llm_utils.get_model_by_model_id')
    def test_call_llm_for_system_prompt_with_tenant_id(
        self,
        mock_get_model_by_id,
        mock_get_model_name,
        mock_openai,
    ):
        """Test call_llm_for_system_prompt with tenant_id"""
        mock_model_config = {
            "base_url": "http://example.com",
            "api_key": "fake-key",
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
            self.test_model_id,
            "user prompt",
            "system prompt",
            tenant_id="test-tenant",
        )

        self.assertEqual(result, "Generated prompt")
        mock_get_model_by_id.assert_called_once_with(
            model_id=self.test_model_id,
            tenant_id="test-tenant",
        )

    @patch('backend.utils.llm_utils.OpenAIModel')
    @patch('backend.utils.llm_utils.get_model_name_from_config')
    @patch('backend.utils.llm_utils.get_model_by_model_id')
    def test_call_llm_for_system_prompt_with_none_model_config(
        self,
        mock_get_model_by_id,
        mock_get_model_name,
        mock_openai,
    ):
        """Test call_llm_for_system_prompt with None model config"""
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
            self.test_model_id,
            "user prompt",
            "system prompt",
        )

        self.assertEqual(result, "Generated prompt")
        # Verify OpenAIModel was called with empty strings when model_config is None
        mock_openai.assert_called_once_with(
            model_id="",
            api_base="",
            api_key="",
            temperature=0.3,
            top_p=0.95,
        )

    @patch('backend.utils.llm_utils.OpenAIModel')
    @patch('backend.utils.llm_utils.get_model_name_from_config')
    @patch('backend.utils.llm_utils.get_model_by_model_id')
    @patch('backend.utils.llm_utils.logger')
    def test_call_llm_for_system_prompt_reasoning_content_logging(
        self,
        mock_logger,
        mock_get_model_by_id,
        mock_get_model_name,
        mock_openai,
    ):
        """Test call_llm_for_system_prompt logs when reasoning_content is received"""
        mock_model_config = {
            "base_url": "http://example.com",
            "api_key": "fake-key",
        }
        mock_get_model_by_id.return_value = mock_model_config
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
            self.test_model_id,
            "user prompt",
            "system prompt",
        )

        self.assertEqual(result, "Generated prompt")
        # Verify debug log was called for reasoning_content
        mock_logger.debug.assert_called_once()
        call_args = mock_logger.debug.call_args[0][0]
        self.assertIn("reasoning_content", call_args)

    @patch('backend.utils.llm_utils.OpenAIModel')
    @patch('backend.utils.llm_utils.get_model_name_from_config')
    @patch('backend.utils.llm_utils.get_model_by_model_id')
    @patch('backend.utils.llm_utils.logger')
    def test_call_llm_for_system_prompt_exception_logging(
        self,
        mock_logger,
        mock_get_model_by_id,
        mock_get_model_name,
        mock_openai,
    ):
        """Test call_llm_for_system_prompt exception handling and logging"""
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

        with self.assertRaises(Exception) as context:
            call_llm_for_system_prompt(
                self.test_model_id,
                "user prompt",
                "system prompt",
            )

        self.assertIn("LLM error", str(context.exception))
        # Verify error was logged
        mock_logger.error.assert_called_once()
        call_args = mock_logger.error.call_args[0][0]
        self.assertIn("Failed to generate prompt", call_args)


if __name__ == '__main__':
    unittest.main()

