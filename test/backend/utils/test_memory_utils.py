import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# Setup common mocks
from test.common.test_mocks import patch_minio_client_initialization, setup_common_mocks

# Initialize common mocks
mocks = setup_common_mocks()

# Patch storage factory before importing
with patch_minio_client_initialization():
    from backend.utils.memory_utils import _sanitize_index_component, build_memory_config


@pytest.fixture
def mock_model_configs():
    """Fixture to provide mock model configurations."""
    llm_config = {
        "model_name": "gpt-4",
        "model_repo": "openai",
        "base_url": "https://api.openai.com/v1",
        "api_key": "test-llm-key",
    }
    embedding_config = {
        "model_name": "text-embedding-ada-002",
        "model_repo": "openai",
        "base_url": "https://api.openai.com/v1",
        "api_key": "test-embed-key",
        "max_tokens": 1536,
    }
    return {
        "llm_config": llm_config,
        "embedding_config": embedding_config,
    }


@pytest.fixture
def mock_tenant_config_manager():
    """Fixture to provide mock tenant config manager."""
    return MagicMock()


@pytest.fixture
def model_mapping():
    """Fixture to provide deterministic model config mapping."""
    return {"llm": "llm", "embedding": "embedding"}


@pytest.fixture
def mock_constants():
    """Fixture to provide Elasticsearch-related constants."""
    return SimpleNamespace(
        ES_HOST="http://localhost:9200",
        ES_API_KEY="test-es-key",
        ES_USERNAME="elastic",
        ES_PASSWORD="test-password",
    )


@pytest.fixture
def patch_memory_dependencies(mocker, mock_tenant_config_manager, mock_constants, model_mapping):
    """Patch shared dependencies used by build_memory_config."""
    mocker.patch("backend.utils.memory_utils.tenant_config_manager", mock_tenant_config_manager)
    mocker.patch("backend.utils.memory_utils._c", mock_constants)
    mocker.patch("backend.utils.memory_utils.MODEL_CONFIG_MAPPING", model_mapping)
    return mock_tenant_config_manager, mock_constants


class TestSanitizeIndexComponent:
    """Tests for the index component sanitizer."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("OpenAI", "openai"),
            ("azure/openai", "azure_openai"),
            ("Model Name", "model_name"),
            ("repo.name-1", "repo.name-1"),
            ("MIXED/Chars@Here", "mixed_chars_here"),
            ("", ""),
        ],
    )
    def test_sanitize_index_component(self, value, expected):
        """Sanitizer lowercases input and replaces unsupported characters."""
        assert _sanitize_index_component(value) == expected


class TestMemoryUtils:
    """Tests for backend.utils.memory_utils functions."""

    def test_build_memory_config_success(
        self,
        mocker,
        mock_model_configs,
        patch_memory_dependencies,
        mock_tenant_config_manager,
        mock_constants,
    ):
        """Builds a complete configuration successfully."""
        mock_llm_config = mock_model_configs["llm_config"]
        mock_embed_config = mock_model_configs["embedding_config"]
        mock_tenant_config_manager.get_model_config.side_effect = [mock_llm_config, mock_embed_config]

        mock_get_model_name = mocker.patch(
            "backend.utils.memory_utils.get_model_name_from_config",
            side_effect=["openai/gpt-4", "openai/text-embedding-ada-002"],
        )

        result = build_memory_config("test-tenant-id")

        assert isinstance(result, dict)
        assert result["llm"] == {
            "provider": "openai",
            "config": {
                "model": "openai/gpt-4",
                "openai_base_url": "https://api.openai.com/v1",
                "api_key": "test-llm-key",
            },
        }
        assert result["embedder"] == {
            "provider": "openai",
            "config": {
                "model": "openai/text-embedding-ada-002",
                "openai_base_url": "https://api.openai.com/v1",
                "embedding_dims": 1536,
                "api_key": "test-embed-key",
            },
        }
        assert result["vector_store"] == {
            "provider": "elasticsearch",
            "config": {
                "collection_name": "mem0_openai_text-embedding-ada-002_1536",
                "host": "http://localhost",
                "port": 9200,
                "embedding_model_dims": 1536,
                "verify_certs": False,
                "api_key": mock_constants.ES_API_KEY,
                "user": mock_constants.ES_USERNAME,
                "password": mock_constants.ES_PASSWORD,
            },
        }
        assert result["telemetry"] == {"enabled": False}

        assert mock_get_model_name.call_count == 2
        mock_get_model_name.assert_any_call(mock_llm_config)
        mock_get_model_name.assert_any_call(mock_embed_config)
        assert mock_tenant_config_manager.get_model_config.call_count == 2

    @pytest.mark.parametrize(
        "llm_raw",
        [None, {}, {"api_key": "test-key"}, {"model_name": ""}],
    )
    def test_build_memory_config_missing_llm_config(self, llm_raw, patch_memory_dependencies, mock_tenant_config_manager):
        """Raises when LLM config is missing or incomplete."""
        mock_tenant_config_manager.get_model_config.side_effect = [
            llm_raw,
            {"model_name": "test-embed", "max_tokens": 1536},
        ]

        with pytest.raises(ValueError, match="Missing LLM configuration for tenant"):
            build_memory_config("test-tenant-id")

    @pytest.mark.parametrize(
        "embed_raw",
        [None, {}, {"model_name": "test-embed"}, {"model_name": "test-embed", "max_tokens": 0}],
    )
    def test_build_memory_config_missing_embedding_config(
        self,
        embed_raw,
        patch_memory_dependencies,
        mock_tenant_config_manager,
    ):
        """Raises when embedding config is missing or incomplete."""
        mock_tenant_config_manager.get_model_config.side_effect = [
            {"model_name": "test-llm"},
            embed_raw,
        ]

        with pytest.raises(ValueError, match="Missing embedding-model configuration for tenant"):
            build_memory_config("test-tenant-id")

    @pytest.mark.parametrize("es_host", [None, ""])
    def test_build_memory_config_missing_es_host(self, es_host, patch_memory_dependencies, mock_constants):
        """Raises when ES_HOST is not configured."""
        mock_constants.ES_HOST = es_host

        with pytest.raises(ValueError, match="ES_HOST is not configured"):
            build_memory_config("test-tenant-id")

    @pytest.mark.parametrize(
        "es_host",
        [
            "invalid-host",
            "localhost:9200",
            "http://localhost",
            "http://:9200",
        ],
    )
    def test_build_memory_config_invalid_es_host_format(self, es_host, patch_memory_dependencies, mock_tenant_config_manager, mock_constants):
        """Raises when ES_HOST is missing required URL parts."""
        mock_tenant_config_manager.get_model_config.side_effect = [
            {"model_name": "test-llm"},
            {"model_name": "test-embed", "max_tokens": 1536},
        ]
        mock_constants.ES_HOST = es_host

        with pytest.raises(
            ValueError,
            match="ES_HOST must include scheme, host and port, e.g. http://host:9200",
        ):
            build_memory_config("test-tenant-id")

    def test_build_memory_config_with_https_es_host(
        self,
        mocker,
        patch_memory_dependencies,
        mock_tenant_config_manager,
        mock_constants,
    ):
        """HTTPS ES host is parsed correctly."""
        mock_tenant_config_manager.get_model_config.side_effect = [
            {
                "model_name": "test-llm",
                "model_repo": "openai",
                "base_url": "https://api.openai.com/v1",
                "api_key": "test-llm-key",
            },
            {
                "model_name": "test-embed",
                "model_repo": "openai",
                "base_url": "https://api.openai.com/v1",
                "api_key": "test-embed-key",
                "max_tokens": 1536,
            },
        ]
        mock_constants.ES_HOST = "https://elastic.example.com:9200"
        mocker.patch(
            "backend.utils.memory_utils.get_model_name_from_config",
            side_effect=["openai/test-llm", "openai/test-embed"],
        )

        result = build_memory_config("test-tenant-id")

        assert result["vector_store"]["config"]["host"] == "https://elastic.example.com"
        assert result["vector_store"]["config"]["port"] == 9200
        assert result["vector_store"]["config"]["collection_name"] == "mem0_openai_test-embed_1536"

    def test_build_memory_config_with_custom_port(
        self,
        mocker,
        patch_memory_dependencies,
        mock_tenant_config_manager,
        mock_constants,
    ):
        """Custom ES port is parsed and applied."""
        mock_tenant_config_manager.get_model_config.side_effect = [
            {
                "model_name": "test-llm",
                "model_repo": "openai",
                "base_url": "https://api.openai.com/v1",
                "api_key": "test-llm-key",
            },
            {
                "model_name": "test-embed",
                "model_repo": "openai",
                "base_url": "https://api.openai.com/v1",
                "api_key": "test-embed-key",
                "max_tokens": 1536,
            },
        ]
        mock_constants.ES_HOST = "http://localhost:9300"
        mocker.patch(
            "backend.utils.memory_utils.get_model_name_from_config",
            side_effect=["openai/test-llm", "openai/test-embed"],
        )

        result = build_memory_config("test-tenant-id")

        assert result["vector_store"]["config"]["host"] == "http://localhost"
        assert result["vector_store"]["config"]["port"] == 9300
        assert result["vector_store"]["config"]["collection_name"] == "mem0_openai_test-embed_1536"

    def test_build_memory_config_sanitizes_repo_and_name(
        self,
        mocker,
        patch_memory_dependencies,
        mock_tenant_config_manager,
    ):
        """Collection name sanitizes repo and model name through the helper."""
        mock_tenant_config_manager.get_model_config.side_effect = [
            {
                "model_name": "gpt-4",
                "model_repo": "Azure/OpenAI Repo",
                "base_url": "https://api.example.com/v1",
                "api_key": "llm-key",
            },
            {
                "model_name": "Text Embed@Ada/002",
                "model_repo": "Azure/OpenAI Repo",
                "base_url": "https://api.example.com/v1",
                "api_key": "embed-key",
                "max_tokens": 1536,
            },
        ]
        mocker.patch(
            "backend.utils.memory_utils.get_model_name_from_config",
            side_effect=["azure/openai/gpt-4", "azure/openai/Text Embed@Ada/002"],
        )

        result = build_memory_config("tenant-with-special-chars")

        assert result["vector_store"]["config"]["collection_name"] == (
            "mem0_azure_openai_repo_text_embed_ada_002_1536"
        )

    @pytest.mark.parametrize("repo_value", ["", None])
    def test_build_memory_config_without_repo_segment(
        self,
        repo_value,
        mocker,
        patch_memory_dependencies,
        mock_tenant_config_manager,
    ):
        """Falsy model_repo omits the repo segment from the collection name."""
        mock_tenant_config_manager.get_model_config.side_effect = [
            {
                "model_name": "gpt-4",
                "model_repo": repo_value,
                "base_url": "https://api.openai.com/v1",
                "api_key": "test-llm-key",
            },
            {
                "model_name": "Text Embedding/ADA 002",
                "model_repo": repo_value,
                "base_url": "https://api.openai.com/v1",
                "api_key": "test-embed-key",
                "max_tokens": 1536,
            },
        ]
        mocker.patch(
            "backend.utils.memory_utils.get_model_name_from_config",
            side_effect=["gpt-4", "Text Embedding/ADA 002"],
        )

        result = build_memory_config("test-tenant-id")

        assert result["llm"]["config"]["model"] == "gpt-4"
        assert result["embedder"]["config"]["model"] == "Text Embedding/ADA 002"
        assert result["vector_store"]["config"]["collection_name"] == "mem0_text_embedding_ada_002_1536"
