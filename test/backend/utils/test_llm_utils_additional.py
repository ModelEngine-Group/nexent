import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# Mirror the environment setup used by existing tests to avoid heavy import-time deps
boto3_mock = MagicMock()
sys.modules['boto3'] = boto3_mock

elasticsearch_mock = MagicMock()
sys.modules['elasticsearch'] = elasticsearch_mock

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
# Ensure storage_client_factory also exposes MinIOStorageConfig for imports that expect it there
storage_client_factory_module.MinIOStorageConfig = None  # will be set after minio_config_module is created

minio_config_module = types.ModuleType("nexent.storage.minio_config")
sys.modules['nexent.storage.minio_config'] = minio_config_module
storage_pkg.minio_config = minio_config_module
minio_config_module.MinIOStorageConfig = MagicMock()
storage_client_factory_module.MinIOStorageConfig = minio_config_module.MinIOStorageConfig

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
observer_mod.ProcessType = types.SimpleNamespace(MODEL_OUTPUT_CODE=types.SimpleNamespace(value="model_output_code"), MODEL_OUTPUT_THINKING=types.SimpleNamespace(value="model_output_thinking"))
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

# Import the functions under test
from backend.utils.llm_utils import _process_thinking_tokens, call_llm_for_system_prompt


class AdditionalLLMUtilsTests(unittest.TestCase):
    def test_process_thinking_tokens_append_and_callback(self):
        token_join = []
        calls = []

        def cb(text):
            calls.append(text)

        is_thinking = _process_thinking_tokens("Hello", False, token_join, cb)
        self.assertFalse(is_thinking)
        self.assertEqual(token_join, ["Hello"])
        self.assertEqual(calls, ["Hello"])

    def test_process_thinking_tokens_start_tag(self):
        token_join = []
        calls = []

        def cb(text):
            calls.append(text)

        is_thinking = _process_thinking_tokens("<think>inner", False, token_join, cb)
        self.assertTrue(is_thinking)
        # start tag should not append to token_join
        self.assertEqual(token_join, [])
        self.assertEqual(calls, [])

    def test_process_thinking_tokens_is_thinking_without_end(self):
        token_join = ["x"]
        # when already thinking and token does NOT contain end tag, should remain thinking
        is_thinking = _process_thinking_tokens("still thinking", True, token_join, None)
        self.assertTrue(is_thinking)
        self.assertEqual(token_join, ["x"])

    def test_process_thinking_tokens_is_thinking_with_end(self):
        token_join = ["x"]
        # when already thinking and token contains end tag, should return False (stop thinking)
        is_thinking = _process_thinking_tokens("</think>done", True, token_join, None)
        self.assertFalse(is_thinking)
        # token_join is not modified by the function in this code path
        self.assertEqual(token_join, ["x", "done"])

    def test_process_thinking_tokens_empty_token_with_callback(self):
        token_join = []
        calls = []

        def cb(text):
            calls.append(text)

        is_thinking = _process_thinking_tokens("", False, token_join, cb)
        # empty string is appended and callback is invoked with the joined token list
        self.assertFalse(is_thinking)
        self.assertEqual(token_join, [])
        self.assertEqual(calls, [])

    @patch('backend.utils.llm_utils.OpenAIModel')
    @patch('backend.utils.llm_utils.get_model_name_from_config')
    @patch('backend.utils.llm_utils.get_model_by_model_id')
    def test_call_llm_for_system_prompt_skips_none_tokens_and_joins(self, mock_get_model_by_id, mock_get_model_name, mock_openai):
        # Setup model config and OpenAIModel behavior
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
        self.assertEqual(res, "OK")
        # Ensure OpenAIModel constructed with expected args
        mock_openai.assert_called_once()

    @patch('backend.utils.llm_utils.OpenAIModel')
    @patch('backend.utils.llm_utils.get_model_name_from_config')
    @patch('backend.utils.llm_utils.get_model_by_model_id')
    def test_call_llm_for_system_prompt_generator_like_response(self, mock_get_model_by_id, mock_get_model_name, mock_openai):
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
        self.assertEqual(res, "ABC")


if __name__ == "__main__":
    unittest.main()



