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
        self.assertEqual(token_join, [""])
        self.assertEqual(callback_calls, [""])


if __name__ == '__main__':
    unittest.main()

