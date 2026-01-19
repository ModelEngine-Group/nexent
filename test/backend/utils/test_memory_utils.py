import pytest

from backend.utils.memory_utils import build_memory_config


class TestMemoryUtils:
    """Tests for backend.utils.memory_utils functions"""

    def test_build_memory_config_success(self, mocker, mock_constants, mock_model_configs, mock_tenant_config_manager):
        """Builds a complete configuration successfully"""
        # Use global fixtures for common mocks
        mock_llm_config = mock_model_configs['llm_config']
        mock_embed_config = mock_model_configs['embedding_config']

        # Mock get_model_config return sequence
        mock_tenant_config_manager.get_model_config.side_effect = [
            mock_llm_config,  # LLM
            mock_embed_config  # embedding
        ]

        # Mock get_model_name_from_config
        mock_get_model_name = mocker.MagicMock()
        mock_get_model_name.side_effect = [
            "openai/gpt-4", "openai/text-embedding-ada-002"]

        # Provide deterministic mapping for model config keys
        model_mapping = {"llm": "llm", "embedding": "embedding"}

        mocker.patch('backend.utils.memory_utils.tenant_config_manager',
                     mock_tenant_config_manager)
        mocker.patch('backend.utils.memory_utils._c', mock_constants)
        mocker.patch(
            'backend.utils.memory_utils.get_model_name_from_config', mock_get_model_name)
        mocker.patch(
            'backend.utils.memory_utils.MODEL_CONFIG_MAPPING', model_mapping)

        # Execute
        result = build_memory_config("test-tenant-id")

        # Structure
        assert isinstance(result, dict)
        assert "llm" in result
        assert "embedder" in result
        assert "vector_store" in result
        assert "telemetry" in result

        # LLM
        assert result["llm"]["provider"] == "openai"
        assert result["llm"]["config"]["model"] == "openai/gpt-4"
        assert result["llm"]["config"]["openai_base_url"] == "https://api.openai.com/v1"
        assert result["llm"]["config"]["api_key"] == "test-llm-key"

        # Embedder
        assert result["embedder"]["provider"] == "openai"
        assert result["embedder"]["config"]["model"] == "openai/text-embedding-ada-002"
        assert result["embedder"]["config"]["openai_base_url"] == "https://api.openai.com/v1"
        assert result["embedder"]["config"]["embedding_dims"] == 1536
        assert result["embedder"]["config"]["api_key"] == "test-embed-key"

        # Vector store
        assert result["vector_store"]["provider"] == "elasticsearch"
        assert result["vector_store"]["config"]["collection_name"] == "mem0_openai_text-embedding-ada-002_1536"
        assert result["vector_store"]["config"]["host"] == "http://localhost"
        assert result["vector_store"]["config"]["port"] == 9200
        assert result["vector_store"]["config"]["embedding_model_dims"] == 1536
        assert result["vector_store"]["config"]["verify_certs"] is False
        assert result["vector_store"]["config"]["api_key"] == "test-es-key"
        assert result["vector_store"]["config"]["user"] == "elastic"
        assert result["vector_store"]["config"]["password"] == "test-password"

        # Telemetry
        assert result["telemetry"]["enabled"] is False

        # Called for both models
        assert mock_get_model_name.call_count == 2
        mock_get_model_name.assert_any_call(mock_llm_config)
        mock_get_model_name.assert_any_call(mock_embed_config)

    def test_build_memory_config_missing_llm_config(self, mocker, mock_tenant_config_manager):
        """Raises when LLM config is missing"""
        mock_tenant_config_manager.get_model_config.side_effect = [
            None,  # LLM is None
            {"model_name": "test-embed", "max_tokens": 1536}  # embedding present
        ]

        mocker.patch('backend.utils.memory_utils.tenant_config_manager',
                     mock_tenant_config_manager)

        # Should raise
        with pytest.raises(ValueError) as exc_info:
            build_memory_config("test-tenant-id")

        assert "Missing LLM configuration for tenant" in str(exc_info.value)

    def test_build_memory_config_llm_config_missing_model_name(self, mocker):
        """Raises when LLM config lacks model_name"""
        mock_tenant_config_manager = mocker.MagicMock()
        mock_tenant_config_manager.get_model_config.side_effect = [
            {"api_key": "test-key"},  # LLM missing model_name
            {"model_name": "test-embed", "max_tokens": 1536}  # embedding present
        ]

        mocker.patch('backend.utils.memory_utils.tenant_config_manager',
                     mock_tenant_config_manager)

        # Should raise
        with pytest.raises(ValueError) as exc_info:
            build_memory_config("test-tenant-id")

        assert "Missing LLM configuration for tenant" in str(exc_info.value)

    def test_build_memory_config_missing_embedding_config(self, mocker, mock_tenant_config_manager):
        """Raises when embedding config is missing"""
        mock_tenant_config_manager.get_model_config.side_effect = [
            {"model_name": "test-llm"},  # LLM present
            None  # embedding is None
        ]

        mocker.patch('backend.utils.memory_utils.tenant_config_manager',
                     mock_tenant_config_manager)

        # Should raise
        with pytest.raises(ValueError) as exc_info:
            build_memory_config("test-tenant-id")

        assert "Missing embedding-model configuration for tenant" in str(
            exc_info.value)

    def test_build_memory_config_embedding_config_missing_max_tokens(self, mocker):
        """Raises when embedding config lacks max_tokens"""
        mock_tenant_config_manager = mocker.MagicMock()
        mock_tenant_config_manager.get_model_config.side_effect = [
            {"model_name": "test-llm"},  # LLM present
            {"model_name": "test-embed"}  # embedding missing max_tokens
        ]

        mocker.patch('backend.utils.memory_utils.tenant_config_manager',
                     mock_tenant_config_manager)

        # Should raise
        with pytest.raises(ValueError) as exc_info:
            build_memory_config("test-tenant-id")

        assert "Missing embedding-model configuration for tenant" in str(
            exc_info.value)

    def test_build_memory_config_missing_es_host(self, mocker):
        """Raises when ES_HOST is missing"""
        mock_tenant_config_manager = mocker.MagicMock()
        mock_tenant_config_manager.get_model_config.side_effect = [
            {"model_name": "test-llm"},
            {"model_name": "test-embed", "max_tokens": 1536}
        ]

        mock_const = mocker.MagicMock()
        mock_const.ES_HOST = None  # ES_HOST is None

        mocker.patch('backend.utils.memory_utils.tenant_config_manager',
                     mock_tenant_config_manager)
        mocker.patch('backend.utils.memory_utils._c', mock_const)

        # Should raise
        with pytest.raises(ValueError) as exc_info:
            build_memory_config("test-tenant-id")

        assert "ES_HOST is not configured" in str(exc_info.value)

    def test_build_memory_config_invalid_es_host_format(self, mocker):
        """Raises when ES_HOST format is invalid"""
        mock_tenant_config_manager = mocker.MagicMock()
        mock_tenant_config_manager.get_model_config.side_effect = [
            {"model_name": "test-llm"},
            {"model_name": "test-embed", "max_tokens": 1536}
        ]

        mock_const = mocker.MagicMock()
        mock_const.ES_HOST = "invalid-host"  # invalid format

        mocker.patch('backend.utils.memory_utils.tenant_config_manager',
                     mock_tenant_config_manager)
        mocker.patch('backend.utils.memory_utils._c', mock_const)

        # Should raise
        with pytest.raises(ValueError) as exc_info:
            build_memory_config("test-tenant-id")

        assert "ES_HOST must include scheme, host and port" in str(
            exc_info.value)

    def test_build_memory_config_es_host_missing_scheme(self, mocker):
        """Raises when ES_HOST is missing scheme"""
        mock_tenant_config_manager = mocker.MagicMock()
        mock_tenant_config_manager.get_model_config.side_effect = [
            {"model_name": "test-llm"},
            {"model_name": "test-embed", "max_tokens": 1536}
        ]

        mock_const = mocker.MagicMock()
        mock_const.ES_HOST = "localhost:9200"  # missing scheme

        mocker.patch('backend.utils.memory_utils.tenant_config_manager',
                     mock_tenant_config_manager)
        mocker.patch('backend.utils.memory_utils._c', mock_const)

        # Should raise
        with pytest.raises(ValueError) as exc_info:
            build_memory_config("test-tenant-id")

        assert "ES_HOST must include scheme, host and port" in str(
            exc_info.value)

    def test_build_memory_config_es_host_missing_port(self, mocker):
        """Raises when ES_HOST is missing port"""
        mock_tenant_config_manager = mocker.MagicMock()
        mock_tenant_config_manager.get_model_config.side_effect = [
            {"model_name": "test-llm"},
            {"model_name": "test-embed", "max_tokens": 1536}
        ]

        mock_const = mocker.MagicMock()
        mock_const.ES_HOST = "http://localhost"  # missing port

        mocker.patch('backend.utils.memory_utils.tenant_config_manager',
                     mock_tenant_config_manager)
        mocker.patch('backend.utils.memory_utils._c', mock_const)

        # Should raise
        with pytest.raises(ValueError) as exc_info:
            build_memory_config("test-tenant-id")

        assert "ES_HOST must include scheme, host and port" in str(
            exc_info.value)

    def test_build_memory_config_with_https_es_host(self, mocker):
        """HTTPS ES_HOST is parsed correctly and collection name composes"""
        mock_tenant_config_manager = mocker.MagicMock()
        mock_tenant_config_manager.get_model_config.side_effect = [
            {"model_name": "test-llm", "model_repo": "openai",
                "base_url": "https://api.openai.com/v1", "api_key": "test-llm-key"},
            {"model_name": "test-embed", "model_repo": "openai",
                "base_url": "https://api.openai.com/v1", "api_key": "test-embed-key", "max_tokens": 1536}
        ]

        mock_const = mocker.MagicMock()
        mock_const.ES_HOST = "https://elastic.example.com:9200"
        mock_const.ES_API_KEY = "test-es-key"
        mock_const.ES_USERNAME = "elastic"
        mock_const.ES_PASSWORD = "test-password"

        mock_get_model_name = mocker.MagicMock()
        mock_get_model_name.side_effect = [
            "openai/test-llm", "openai/test-embed"]

        model_mapping = {"llm": "llm", "embedding": "embedding"}
        mocker.patch('backend.utils.memory_utils.tenant_config_manager',
                     mock_tenant_config_manager)
        mocker.patch('backend.utils.memory_utils._c', mock_const)
        mocker.patch(
            'backend.utils.memory_utils.get_model_name_from_config', mock_get_model_name)
        mocker.patch(
            'backend.utils.memory_utils.MODEL_CONFIG_MAPPING', model_mapping)

        # Execute
        result = build_memory_config("test-tenant-id")

        # ES fields
        assert result["vector_store"]["config"]["host"] == "https://elastic.example.com"
        assert result["vector_store"]["config"]["port"] == 9200
        assert result["vector_store"]["config"]["collection_name"] == "mem0_openai_test-embed_1536"

    def test_build_memory_config_with_custom_port(self, mocker):
        """Custom ES port is parsed and applied; collection name composed"""
        mock_tenant_config_manager = mocker.MagicMock()
        mock_tenant_config_manager.get_model_config.side_effect = [
            {"model_name": "test-llm", "model_repo": "openai",
                "base_url": "https://api.openai.com/v1", "api_key": "test-llm-key"},
            {"model_name": "test-embed", "model_repo": "openai",
                "base_url": "https://api.openai.com/v1", "api_key": "test-embed-key", "max_tokens": 1536}
        ]

        mock_const = mocker.MagicMock()
        mock_const.ES_HOST = "http://localhost:9300"  # custom port
        mock_const.ES_API_KEY = "test-es-key"
        mock_const.ES_USERNAME = "elastic"
        mock_const.ES_PASSWORD = "test-password"

        mock_get_model_name = mocker.MagicMock()
        mock_get_model_name.side_effect = [
            "openai/test-llm", "openai/test-embed"]

        model_mapping = {"llm": "llm", "embedding": "embedding"}
        mocker.patch('backend.utils.memory_utils.tenant_config_manager',
                     mock_tenant_config_manager)
        mocker.patch('backend.utils.memory_utils._c', mock_const)
        mocker.patch(
            'backend.utils.memory_utils.get_model_name_from_config', mock_get_model_name)
        mocker.patch(
            'backend.utils.memory_utils.MODEL_CONFIG_MAPPING', model_mapping)

        # Execute
        result = build_memory_config("test-tenant-id")

        # ES fields
        assert result["vector_store"]["config"]["host"] == "http://localhost"
        assert result["vector_store"]["config"]["port"] == 9300
        assert result["vector_store"]["config"]["collection_name"] == "mem0_openai_test-embed_1536"

    def test_build_memory_config_sanitizes_slashes_in_repo_and_name(self, mocker):
        """Slash characters in repo/name are replaced with underscores in collection name"""
        mock_tenant_config_manager = mocker.MagicMock()
        mock_tenant_config_manager.get_model_config.side_effect = [
            {"model_name": "gpt-4", "model_repo": "azure/openai",
                "base_url": "https://api.example.com/v1", "api_key": "llm-key"},
            {"model_name": "text-embed/ada-002", "model_repo": "azure/openai",
                "base_url": "https://api.example.com/v1", "api_key": "embed-key", "max_tokens": 1536}
        ]

        mock_const = mocker.MagicMock()
        mock_const.ES_HOST = "http://localhost:9200"
        mock_const.ES_API_KEY = "test-es-key"
        mock_const.ES_USERNAME = "elastic"
        mock_const.ES_PASSWORD = "test-password"

        model_mapping = {"llm": "llm", "embedding": "embedding"}
        mock_get_model_name = mocker.MagicMock()
        mock_get_model_name.side_effect = [
            "azure/openai/gpt-4", "azure/openai/text-embed/ada-002"]

        mocker.patch('backend.utils.memory_utils.tenant_config_manager',
                     mock_tenant_config_manager)
        mocker.patch('backend.utils.memory_utils._c', mock_const)
        mocker.patch(
            'backend.utils.memory_utils.get_model_name_from_config', mock_get_model_name)
        mocker.patch(
            'backend.utils.memory_utils.MODEL_CONFIG_MAPPING', model_mapping)

        result = build_memory_config("tenant-with-slash")

        assert result["vector_store"]["config"]["collection_name"] == "mem0_azure_openai_text-embed_ada-002_1536"

    def test_build_memory_config_with_empty_model_repo(self, mocker):
        """Empty model_repo yields collection name without repo segment"""
        mock_tenant_config_manager = mocker.MagicMock()
        mock_tenant_config_manager.get_model_config.side_effect = [
            {"model_name": "gpt-4", "model_repo": "",
                "base_url": "https://api.openai.com/v1", "api_key": "test-llm-key"},
            {"model_name": "text-embedding-ada-002", "model_repo": "",
                "base_url": "https://api.openai.com/v1", "api_key": "test-embed-key", "max_tokens": 1536}
        ]

        mock_const = mocker.MagicMock()
        mock_const.ES_HOST = "http://localhost:9200"
        mock_const.ES_API_KEY = "test-es-key"
        mock_const.ES_USERNAME = "elastic"
        mock_const.ES_PASSWORD = "test-password"

        mock_get_model_name = mocker.MagicMock()
        mock_get_model_name.side_effect = [
            "gpt-4", "text-embedding-ada-002"]  # no repo prefix

        model_mapping = {"llm": "llm", "embedding": "embedding"}
        mocker.patch('backend.utils.memory_utils.tenant_config_manager',
                     mock_tenant_config_manager)
        mocker.patch('backend.utils.memory_utils._c', mock_const)
        mocker.patch(
            'backend.utils.memory_utils.get_model_name_from_config', mock_get_model_name)
        mocker.patch(
            'backend.utils.memory_utils.MODEL_CONFIG_MAPPING', model_mapping)

        # Execute
        result = build_memory_config("test-tenant-id")

        # Model names
        assert result["llm"]["config"]["model"] == "gpt-4"
        assert result["embedder"]["config"]["model"] == "text-embedding-ada-002"
        # Collection name omits empty repo segment
        assert result["vector_store"]["config"]["collection_name"] == "mem0_text-embedding-ada-002_1536"
