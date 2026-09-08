"""Tests for embedding model metadata and the embedding client factory."""

from unittest.mock import MagicMock

from nexent.core.gateway import EmbeddingContext
from nexent.memory.embedding_model import (
    EmbeddingModelInfo,
    _sanitize_index_component,
    get_embedding_client,
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
# get_embedding_client                                                         #
# --------------------------------------------------------------------------- #

class TestEmbeddingClientFactory:
    """Tests for the uncached embedding client factory."""

    def test_builds_adapter_from_context(self, mocker):
        """The adapter is constructed from an EmbeddingContext built out of the arguments."""
        mock_init = mocker.patch(
            "nexent.memory.embedding_model.OpenAICompatibleEmbeddingAdapter"
        )
        mock_instance = MagicMock()
        mock_init.return_value = mock_instance

        client = get_embedding_client(
            model_name="text-embedding-3-small",
            dimension=1536,
            base_url="https://api.openai.com/v1/embeddings",
            api_key="sk-test",
        )

        assert client is mock_instance
        mock_init.assert_called_once_with(
            EmbeddingContext(
                model_name="text-embedding-3-small",
                base_url="https://api.openai.com/v1/embeddings",
                api_key="sk-test",
                modality="embedding",
                factory="openai",
                embedding_dim=1536,
                ssl_verify=True,
            )
        )

    def test_model_repo_prefixes_model_name(self, mocker):
        """model_repo is prepended so vendors such as SiliconFlow receive "BAAI/bge-m3"."""
        mock_init = mocker.patch(
            "nexent.memory.embedding_model.OpenAICompatibleEmbeddingAdapter"
        )

        get_embedding_client(
            model_name="bge-m3",
            dimension=1024,
            base_url="https://api.siliconflow.cn/v1/embeddings",
            api_key="sk-test",
            model_repo="BAAI",
        )

        context = mock_init.call_args[0][0]
        assert context.model_name == "BAAI/bge-m3"
        assert context.embedding_dim == 1024

    def test_every_call_builds_a_new_adapter(self, mocker):
        """Identical arguments must not be served from a shared instance."""
        mock_init = mocker.patch(
            "nexent.memory.embedding_model.OpenAICompatibleEmbeddingAdapter"
        )
        mock_init.side_effect = lambda context: MagicMock(context=context)

        first = get_embedding_client(
            model_name="text-embedding-3-small",
            dimension=1536,
            base_url="https://api.openai.com/v1/embeddings",
            api_key="sk-test",
        )
        second = get_embedding_client(
            model_name="text-embedding-3-small",
            dimension=1536,
            base_url="https://api.openai.com/v1/embeddings",
            api_key="sk-test",
        )

        assert mock_init.call_count == 2
        assert first is not second

    def test_changed_endpoint_and_credentials_are_not_shared(self):
        """Same repo/name/dimension with a different endpoint, key or TLS setting
        must never reuse another caller's client.

        Regression guard for the removed process-wide cache, whose key was
        ``"{model_repo}:{model_name}:{dimension}"`` and therefore handed tenant
        A's endpoint and API key to tenant B. Real adapters are used because
        constructing one performs no I/O.
        """
        tenant_a = get_embedding_client(
            model_name="bge-m3",
            dimension=1024,
            base_url="https://api.siliconflow.cn/v1/embeddings",
            api_key="sk-tenant-a",
            model_repo="BAAI",
            ssl_verify=True,
        )
        tenant_b = get_embedding_client(
            model_name="bge-m3",
            dimension=1024,
            base_url="http://10.0.0.7:8000/v1/embeddings",
            api_key="sk-tenant-b",
            model_repo="BAAI",
            ssl_verify=False,
        )

        assert tenant_a is not tenant_b
        assert tenant_a._base_url == "https://api.siliconflow.cn/v1/embeddings"
        assert tenant_a._headers["Authorization"] == "Bearer sk-tenant-a"
        assert tenant_a._ssl_verify is True
        assert tenant_b._base_url == "http://10.0.0.7:8000/v1/embeddings"
        assert tenant_b._headers["Authorization"] == "Bearer sk-tenant-b"
        assert tenant_b._ssl_verify is False
