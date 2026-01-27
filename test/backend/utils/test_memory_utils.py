import unittest
import sys
import os
from unittest.mock import MagicMock, patch

# Add project root to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

# Mock major dependencies
sys.modules['consts'] = MagicMock()
sys.modules['consts.const'] = MagicMock()
sys.modules['utils.config_utils'] = MagicMock()

# Mock logger
logger_mock = MagicMock()


class TestMemoryUtils(unittest.TestCase):
    """Tests for backend.utils.memory_utils functions"""

    def setUp(self):
        """Import function under test for each test"""
        # Import target function
        from backend.utils.memory_utils import build_memory_config
        self.build_memory_config = build_memory_config

    def test_build_memory_config_success(self):
        """Builds a complete configuration successfully"""
        # Mock tenant_config_manager
        mock_tenant_config_manager = MagicMock()
        
        # Mock LLM config
        mock_llm_config = {
            "model_name": "gpt-4",
            "model_repo": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "test-llm-key"
        }
        
        # Mock embedding config
        mock_embed_config = {
            "model_name": "text-embedding-ada-002",
            "model_repo": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "test-embed-key",
            "max_tokens": 1536
        }
        
        # Mock get_model_config return sequence
        mock_tenant_config_manager.get_model_config.side_effect = [
            mock_llm_config,  # LLM
            mock_embed_config  # embedding
        ]
        
        # Mock constants
        mock_const = MagicMock()
        mock_const.ES_HOST = "http://localhost:9200"
        mock_const.ES_API_KEY = "test-es-key"
        mock_const.ES_USERNAME = "elastic"
        mock_const.ES_PASSWORD = "test-password"
        
        # Mock get_model_name_from_config
        mock_get_model_name = MagicMock()
        mock_get_model_name.side_effect = ["openai/gpt-4", "openai/text-embedding-ada-002"]
        
        # Provide deterministic mapping for model config keys
        model_mapping = {"llm": "llm", "embedding": "embedding"}

        with patch('backend.utils.memory_utils.tenant_config_manager', mock_tenant_config_manager), \
            patch('backend.utils.memory_utils._c', mock_const), \
                patch('backend.utils.memory_utils.get_model_name_from_config', mock_get_model_name), \
                patch('backend.utils.memory_utils.MODEL_CONFIG_MAPPING', model_mapping):
            
            # Execute
            result = self.build_memory_config("test-tenant-id")
            
            # Structure
            self.assertIsInstance(result, dict)
            self.assertIn("llm", result)
            self.assertIn("embedder", result)
            self.assertIn("vector_store", result)
            self.assertIn("telemetry", result)
            
            # LLM
            self.assertEqual(result["llm"]["provider"], "openai")
            self.assertEqual(result["llm"]["config"]["model"], "openai/gpt-4")
            self.assertEqual(result["llm"]["config"]["openai_base_url"], "https://api.openai.com/v1")
            self.assertEqual(result["llm"]["config"]["api_key"], "test-llm-key")
            
            # Embedder
            self.assertEqual(result["embedder"]["provider"], "openai")
            self.assertEqual(result["embedder"]["config"]["model"], "openai/text-embedding-ada-002")
            self.assertEqual(result["embedder"]["config"]["openai_base_url"], "https://api.openai.com/v1")
            self.assertEqual(result["embedder"]["config"]["embedding_dims"], 1536)
            self.assertEqual(result["embedder"]["config"]["api_key"], "test-embed-key")
            
            # Vector store
            self.assertEqual(result["vector_store"]["provider"], "elasticsearch")
            self.assertEqual(result["vector_store"]["config"]
                             ["collection_name"], "mem0_openai_text-embedding-ada-002_1536")
            self.assertEqual(result["vector_store"]["config"]["host"], "http://localhost")
            self.assertEqual(result["vector_store"]["config"]["port"], 9200)
            self.assertEqual(result["vector_store"]["config"]["embedding_model_dims"], 1536)
            self.assertEqual(result["vector_store"]["config"]["verify_certs"], False)
            self.assertEqual(result["vector_store"]["config"]["api_key"], "test-es-key")
            self.assertEqual(result["vector_store"]["config"]["user"], "elastic")
            self.assertEqual(result["vector_store"]["config"]["password"], "test-password")
            
            # Telemetry
            self.assertEqual(result["telemetry"]["enabled"], False)
            
            # Called for both models
            self.assertEqual(mock_get_model_name.call_count, 2)
            mock_get_model_name.assert_any_call(mock_llm_config)
            mock_get_model_name.assert_any_call(mock_embed_config)

    def test_build_memory_config_missing_llm_config(self):
        """Raises when LLM config is missing"""
        mock_tenant_config_manager = MagicMock()
        mock_tenant_config_manager.get_model_config.side_effect = [
            None,  # LLM is None
            {"model_name": "test-embed", "max_tokens": 1536}  # embedding present
        ]
        
        with patch('backend.utils.memory_utils.tenant_config_manager', mock_tenant_config_manager):
            # Should raise
            with self.assertRaises(ValueError) as context:
                self.build_memory_config("test-tenant-id")
            
            self.assertIn("Missing LLM configuration for tenant", str(context.exception))

    def test_build_memory_config_llm_config_missing_model_name(self):
        """Raises when LLM config lacks model_name"""
        mock_tenant_config_manager = MagicMock()
        mock_tenant_config_manager.get_model_config.side_effect = [
            {"api_key": "test-key"},  # LLM missing model_name
            {"model_name": "test-embed", "max_tokens": 1536}  # embedding present
        ]
        
        with patch('backend.utils.memory_utils.tenant_config_manager', mock_tenant_config_manager):
            # Should raise
            with self.assertRaises(ValueError) as context:
                self.build_memory_config("test-tenant-id")
            
            self.assertIn("Missing LLM configuration for tenant", str(context.exception))

    def test_build_memory_config_missing_embedding_config(self):
        """Raises when embedding config is missing"""
        mock_tenant_config_manager = MagicMock()
        mock_tenant_config_manager.get_model_config.side_effect = [
            {"model_name": "test-llm"},  # LLM present
            None  # embedding is None
        ]
        
        with patch('backend.utils.memory_utils.tenant_config_manager', mock_tenant_config_manager):
            # Should raise
            with self.assertRaises(ValueError) as context:
                self.build_memory_config("test-tenant-id")
            
            self.assertIn("Missing embedding-model configuration for tenant", str(context.exception))

    def test_build_memory_config_embedding_config_missing_max_tokens(self):
        """Raises when embedding config lacks max_tokens"""
        mock_tenant_config_manager = MagicMock()
        mock_tenant_config_manager.get_model_config.side_effect = [
            {"model_name": "test-llm"},  # LLM present
            {"model_name": "test-embed"}  # embedding missing max_tokens
        ]
        
        with patch('backend.utils.memory_utils.tenant_config_manager', mock_tenant_config_manager):
            # Should raise
            with self.assertRaises(ValueError) as context:
                self.build_memory_config("test-tenant-id")
            
            self.assertIn("Missing embedding-model configuration for tenant", str(context.exception))

    def test_build_memory_config_missing_es_host(self):
        """Raises when ES_HOST is missing"""
        mock_tenant_config_manager = MagicMock()
        mock_tenant_config_manager.get_model_config.side_effect = [
            {"model_name": "test-llm"},
            {"model_name": "test-embed", "max_tokens": 1536}
        ]
        
        mock_const = MagicMock()
        mock_const.ES_HOST = None  # ES_HOST is None
        
        with patch('backend.utils.memory_utils.tenant_config_manager', mock_tenant_config_manager), \
             patch('backend.utils.memory_utils._c', mock_const):
            
            # Should raise
            with self.assertRaises(ValueError) as context:
                self.build_memory_config("test-tenant-id")
            
            self.assertIn("ES_HOST is not configured", str(context.exception))

    def test_build_memory_config_invalid_es_host_format(self):
        """Raises when ES_HOST format is invalid"""
        mock_tenant_config_manager = MagicMock()
        mock_tenant_config_manager.get_model_config.side_effect = [
            {"model_name": "test-llm"},
            {"model_name": "test-embed", "max_tokens": 1536}
        ]
        
        mock_const = MagicMock()
        mock_const.ES_HOST = "invalid-host"  # invalid format
        
        with patch('backend.utils.memory_utils.tenant_config_manager', mock_tenant_config_manager), \
             patch('backend.utils.memory_utils._c', mock_const):
            
            # Should raise
            with self.assertRaises(ValueError) as context:
                self.build_memory_config("test-tenant-id")
            
            self.assertIn("ES_HOST must include scheme, host and port", str(context.exception))

    def test_build_memory_config_es_host_missing_scheme(self):
        """Raises when ES_HOST is missing scheme"""
        mock_tenant_config_manager = MagicMock()
        mock_tenant_config_manager.get_model_config.side_effect = [
            {"model_name": "test-llm"},
            {"model_name": "test-embed", "max_tokens": 1536}
        ]
        
        mock_const = MagicMock()
        mock_const.ES_HOST = "localhost:9200"  # missing scheme
        
        with patch('backend.utils.memory_utils.tenant_config_manager', mock_tenant_config_manager), \
             patch('backend.utils.memory_utils._c', mock_const):
            
            # Should raise
            with self.assertRaises(ValueError) as context:
                self.build_memory_config("test-tenant-id")
            
            self.assertIn("ES_HOST must include scheme, host and port", str(context.exception))

    def test_build_memory_config_es_host_missing_port(self):
        """Raises when ES_HOST is missing port"""
        mock_tenant_config_manager = MagicMock()
        mock_tenant_config_manager.get_model_config.side_effect = [
            {"model_name": "test-llm"},
            {"model_name": "test-embed", "max_tokens": 1536}
        ]
        
        mock_const = MagicMock()
        mock_const.ES_HOST = "http://localhost"  # missing port
        
        with patch('backend.utils.memory_utils.tenant_config_manager', mock_tenant_config_manager), \
             patch('backend.utils.memory_utils._c', mock_const):
            
            # Should raise
            with self.assertRaises(ValueError) as context:
                self.build_memory_config("test-tenant-id")
            
            self.assertIn("ES_HOST must include scheme, host and port", str(context.exception))

    def test_build_memory_config_with_https_es_host(self):
        """HTTPS ES_HOST is parsed correctly and collection name composes"""
        mock_tenant_config_manager = MagicMock()
        mock_tenant_config_manager.get_model_config.side_effect = [
            {"model_name": "test-llm", "model_repo": "openai", "base_url": "https://api.openai.com/v1", "api_key": "test-llm-key"},
            {"model_name": "test-embed", "model_repo": "openai", "base_url": "https://api.openai.com/v1", "api_key": "test-embed-key", "max_tokens": 1536}
        ]
        
        mock_const = MagicMock()
        mock_const.ES_HOST = "https://elastic.example.com:9200"
        mock_const.ES_API_KEY = "test-es-key"
        mock_const.ES_USERNAME = "elastic"
        mock_const.ES_PASSWORD = "test-password"
        
        mock_get_model_name = MagicMock()
        mock_get_model_name.side_effect = ["openai/test-llm", "openai/test-embed"]
        
        model_mapping = {"llm": "llm", "embedding": "embedding"}
        with patch('backend.utils.memory_utils.tenant_config_manager', mock_tenant_config_manager), \
            patch('backend.utils.memory_utils._c', mock_const), \
                patch('backend.utils.memory_utils.get_model_name_from_config', mock_get_model_name), \
                patch('backend.utils.memory_utils.MODEL_CONFIG_MAPPING', model_mapping):
            
            # Execute
            result = self.build_memory_config("test-tenant-id")
            
            # ES fields
            self.assertEqual(result["vector_store"]["config"]["host"], "https://elastic.example.com")
            self.assertEqual(result["vector_store"]["config"]["port"], 9200)
            self.assertEqual(result["vector_store"]["config"]
                             ["collection_name"], "mem0_openai_test-embed_1536")

    def test_build_memory_config_with_custom_port(self):
        """Custom ES port is parsed and applied; collection name composed"""
        mock_tenant_config_manager = MagicMock()
        mock_tenant_config_manager.get_model_config.side_effect = [
            {"model_name": "test-llm", "model_repo": "openai", "base_url": "https://api.openai.com/v1", "api_key": "test-llm-key"},
            {"model_name": "test-embed", "model_repo": "openai", "base_url": "https://api.openai.com/v1", "api_key": "test-embed-key", "max_tokens": 1536}
        ]
        
        mock_const = MagicMock()
        mock_const.ES_HOST = "http://localhost:9300"  # custom port
        mock_const.ES_API_KEY = "test-es-key"
        mock_const.ES_USERNAME = "elastic"
        mock_const.ES_PASSWORD = "test-password"
        
        mock_get_model_name = MagicMock()
        mock_get_model_name.side_effect = ["openai/test-llm", "openai/test-embed"]
        
        model_mapping = {"llm": "llm", "embedding": "embedding"}
        with patch('backend.utils.memory_utils.tenant_config_manager', mock_tenant_config_manager), \
            patch('backend.utils.memory_utils._c', mock_const), \
                patch('backend.utils.memory_utils.get_model_name_from_config', mock_get_model_name), \
                patch('backend.utils.memory_utils.MODEL_CONFIG_MAPPING', model_mapping):
            
            # Execute
            result = self.build_memory_config("test-tenant-id")
            
            # ES fields
            self.assertEqual(result["vector_store"]["config"]["host"], "http://localhost")
            self.assertEqual(result["vector_store"]["config"]["port"], 9300)
            self.assertEqual(result["vector_store"]["config"]
                             ["collection_name"], "mem0_openai_test-embed_1536")

    def test_build_memory_config_sanitizes_slashes_in_repo_and_name(self):
        """Slash characters in repo/name are replaced with underscores in collection name"""
        mock_tenant_config_manager = MagicMock()
        mock_tenant_config_manager.get_model_config.side_effect = [
            {"model_name": "gpt-4", "model_repo": "azure/openai", "base_url": "https://api.example.com/v1", "api_key": "llm-key"},
            {"model_name": "text-embed/ada-002", "model_repo": "azure/openai", "base_url": "https://api.example.com/v1", "api_key": "embed-key", "max_tokens": 1536}
        ]

        mock_const = MagicMock()
        mock_const.ES_HOST = "http://localhost:9200"
        mock_const.ES_API_KEY = "test-es-key"
        mock_const.ES_USERNAME = "elastic"
        mock_const.ES_PASSWORD = "test-password"

        model_mapping = {"llm": "llm", "embedding": "embedding"}
        mock_get_model_name = MagicMock()
        mock_get_model_name.side_effect = ["azure/openai/gpt-4", "azure/openai/text-embed/ada-002"]

        with patch('backend.utils.memory_utils.tenant_config_manager', mock_tenant_config_manager), \
            patch('backend.utils.memory_utils._c', mock_const), \
                patch('backend.utils.memory_utils.get_model_name_from_config', mock_get_model_name), \
                patch('backend.utils.memory_utils.MODEL_CONFIG_MAPPING', model_mapping):

            result = self.build_memory_config("tenant-with-slash")

            self.assertEqual(
                result["vector_store"]["config"]["collection_name"],
                "mem0_azure_openai_text-embed_ada-002_1536",
            )

    def test_build_memory_config_with_empty_model_repo(self):
        """Empty model_repo yields collection name without repo segment"""
        mock_tenant_config_manager = MagicMock()
        mock_tenant_config_manager.get_model_config.side_effect = [
            {"model_name": "gpt-4", "model_repo": "", "base_url": "https://api.openai.com/v1", "api_key": "test-llm-key"},
            {"model_name": "text-embedding-ada-002", "model_repo": "", "base_url": "https://api.openai.com/v1", "api_key": "test-embed-key", "max_tokens": 1536}
        ]
        
        mock_const = MagicMock()
        mock_const.ES_HOST = "http://localhost:9200"
        mock_const.ES_API_KEY = "test-es-key"
        mock_const.ES_USERNAME = "elastic"
        mock_const.ES_PASSWORD = "test-password"
        
        mock_get_model_name = MagicMock()
        mock_get_model_name.side_effect = [
            "gpt-4", "text-embedding-ada-002"]  # no repo prefix
        
        model_mapping = {"llm": "llm", "embedding": "embedding"}
        with patch('backend.utils.memory_utils.tenant_config_manager', mock_tenant_config_manager), \
            patch('backend.utils.memory_utils._c', mock_const), \
                patch('backend.utils.memory_utils.get_model_name_from_config', mock_get_model_name), \
                patch('backend.utils.memory_utils.MODEL_CONFIG_MAPPING', model_mapping):
            
            # Execute
            result = self.build_memory_config("test-tenant-id")
            
            # Model names
            self.assertEqual(result["llm"]["config"]["model"], "gpt-4")
            self.assertEqual(result["embedder"]["config"]["model"], "text-embedding-ada-002")
            # Collection name omits empty repo segment
            self.assertEqual(result["vector_store"]["config"]
                             ["collection_name"], "mem0_text-embedding-ada-002_1536")


if __name__ == "__main__":
    unittest.main()