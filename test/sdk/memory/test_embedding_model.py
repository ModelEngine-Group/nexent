"""Tests for embedding model metadata and client cache."""

from unittest.mock import MagicMock

import pytest

from nexent.memory.embedding_model import (
    EmbeddingModelInfo,
    _sanitize_index_component,
    get_embedding_client,
    reset_embedding_client_cache,
)


# --------------------------------------------------------------------------- #
# _sanitize_index_component                                                    #
# --------------------------------------------------------------------------- #

class TestSanitizeIndexComponent:
    """Tests for the ES index name sanitisation helper."""

    def test_lowercase_conversion(self):
        assert _sanitize_index_component("Text-Embedding") == "text-embedding"

    def test_slash_replacement(self):
        assert _sanitize_index_component("text/embedding") == "text_embedding"

    def test_special_chars_replacement(self):
        assert _sanitize_index_component("model@v1.0") == "model_v1.0"

    def test_underscore_preserved(self):
        assert _sanitize_index_component("text_embedding_v1") == "text_embedding_v1"


# --------------------------------------------------------------------------- #
# EmbeddingModelInfo                                                           #
# --------------------------------------------------------------------------- #

class TestEmbeddingModelInfo:
    """Tests for ``EmbeddingModelInfo`` as a pure value object."""

    def test_create_model_info(self):
        info = EmbeddingModelInfo(
            model_name="text-embedding-3-small",
            model_repo="openai",
            dimension=1536,
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
        )
        assert info.model_name == "text-embedding-3-small"
        assert info.dimension == 1536
        assert info.model_repo == "openai"

    def test_get_index_name_with_repo(self):
        info = EmbeddingModelInfo(
            model_name="text-embedding-3-small",
            model_repo="openai",
            dimension=1536,
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
        )
        index_name = info.get_index_name()
        assert "mem_" in index_name
        assert "openai" in index_name
        assert "1536" in index_name

    def test_get_index_name_without_repo(self):
        info = EmbeddingModelInfo(
            model_name="bge-m3",
            model_repo=None,
            dimension=1024,
            base_url="https://example.com",
            api_key="sk-test",
        )
        # Hyphens are preserved per the regex pattern [^a-z0-9_.-]
        assert info.get_index_name() == "mem_bge-m3_1024"

    def test_index_name_deterministic_across_calls(self):
        info = EmbeddingModelInfo(
            model_name="bge-m3",
            model_repo="local",
            dimension=1024,
            base_url="https://example.com",
            api_key="sk-test",
        )
        assert info.get_index_name() == info.get_index_name()

    def test_ssl_verify_default_true(self):
        info = EmbeddingModelInfo(
            model_name="test",
            dimension=256,
            base_url="https://example.com",
            api_key="sk-test",
        )
        assert info.ssl_verify is True


# --------------------------------------------------------------------------- #
# get_embedding_client / reset_embedding_client_cache                            #
# --------------------------------------------------------------------------- #

class TestEmbeddingClientCache:
    """Tests for the process-wide HTTP client cache."""

    def setup_method(self):
        reset_embedding_client_cache()

    def teardown_method(self):
        reset_embedding_client_cache()

    def test_cache_miss_creates_instance(self, mocker):
        """First call with a given key must create and cache the client."""
        mock_init = mocker.patch(
            "nexent.memory.embedding_model.OpenAICompatibleEmbedding"
        )
        mock_instance = MagicMock()
        mock_init.return_value = mock_instance

        client = get_embedding_client(
            model_name="text-embedding-3-small",
            dimension=1536,
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
        )

        assert client is mock_instance
        mock_init.assert_called_once_with(
            model_name="text-embedding-3-small",
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            embedding_dim=1536,
            ssl_verify=True,
        )

    def test_cache_hit_returns_same_instance(self, mocker):
        """Subsequent calls with the same key must return the cached instance."""
        mock_init = mocker.patch(
            "nexent.memory.embedding_model.OpenAICompatibleEmbedding"
        )
        mock_instance = MagicMock()
        mock_init.return_value = mock_instance

        client1 = get_embedding_client(
            model_name="text-embedding-3-small",
            dimension=1536,
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
        )
        client2 = get_embedding_client(
            model_name="text-embedding-3-small",
            dimension=1536,
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
        )

        # Only one instance should have been created
        assert mock_init.call_count == 1
        # Both calls should return the same object
        assert client1 is client2

    def test_different_dimension_returns_different_instance(self, mocker):
        """Different dimensions are separate cache entries."""
        mock_init = mocker.patch(
            "nexent.memory.embedding_model.OpenAICompatibleEmbedding"
        )
        mock1 = MagicMock()
        mock2 = MagicMock()
        mock_init.side_effect = [mock1, mock2]

        c1 = get_embedding_client(
            model_name="text-embedding-3-small",
            dimension=1536,
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
        )
        c2 = get_embedding_client(
            model_name="text-embedding-3-small",
            dimension=256,
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
        )

        assert mock_init.call_count == 2
        assert c1 is not c2

    def test_model_repo_not_used_in_cache_key(self, mocker):
        """model_repo does not appear in the cache key — only model_name + dimension.

        This matches the design rationale: one tenant has one global embedding
        model; the model_name is the primary identifier.
        """
        mock_init = mocker.patch(
            "nexent.memory.embedding_model.OpenAICompatibleEmbedding"
        )
        mock_instance = MagicMock()
        mock_init.return_value = mock_instance

        # First call with a repo
        get_embedding_client(
            model_name="text-embedding-3-small",
            dimension=1536,
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model_repo="openai",
        )
        # Second call with different repo but same model_name + dimension
        get_embedding_client(
            model_name="text-embedding-3-small",
            dimension=1536,
            base_url="https://different.example.com",
            api_key="sk-other",
            model_repo="other-repo",
        )

        # Should still hit the cache (only one instance created)
        assert mock_init.call_count == 1

    def test_reset_clears_cache(self, mocker):
        """reset_embedding_client_cache() must empty the cache so the next call
        creates a fresh instance."""
        mock_init = mocker.patch(
            "nexent.memory.embedding_model.OpenAICompatibleEmbedding"
        )
        mock_instance = MagicMock()
        mock_init.return_value = mock_instance

        get_embedding_client(
            model_name="text-embedding-3-small",
            dimension=1536,
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
        )
        reset_embedding_client_cache()

        # After reset a new instance must be created
        get_embedding_client(
            model_name="text-embedding-3-small",
            dimension=1536,
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
        )

        assert mock_init.call_count == 2
