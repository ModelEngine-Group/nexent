"""Tests for embedding registry."""

import pytest

from nexent.memory.embedding_registry import (
    EmbeddingModelInfo,
    EmbeddingModelRegistry,
    get_embedding_registry,
    reset_embedding_registry,
    _sanitize_index_component,
)


class TestSanitizeIndexComponent:
    """Tests for _sanitize_index_component helper."""

    def test_lowercase_conversion(self):
        assert _sanitize_index_component("Text-Embedding") == "text-embedding"

    def test_slash_replacement(self):
        assert _sanitize_index_component("text/embedding") == "text_embedding"

    def test_special_chars_replacement(self):
        assert _sanitize_index_component("model@v1.0") == "model_v1.0"

    def test_underscore_preserved(self):
        assert _sanitize_index_component("text_embedding_v1") == "text_embedding_v1"


class TestEmbeddingModelInfo:
    """Tests for EmbeddingModelInfo dataclass."""

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
        index_name = info.get_index_name()
        # Hyphens are preserved per the regex pattern [^a-z0-9_.-]
        assert index_name == "mem_bge-m3_1024"


class TestEmbeddingModelRegistry:
    """Tests for EmbeddingModelRegistry."""

    def setup_method(self):
        self.registry = EmbeddingModelRegistry()

    def test_register_model(self):
        info = self.registry.register(
            model_name="text-embedding-3-small",
            dimension=1536,
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model_repo="openai",
        )
        assert info.model_name == "text-embedding-3-small"
        assert info.dimension == 1536

    def test_get_registered_model(self):
        self.registry.register(
            model_name="text-embedding-3-small",
            dimension=1536,
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
        )
        info = self.registry.get("text-embedding-3-small", 1536)
        assert info is not None
        assert info.model_name == "text-embedding-3-small"

    def test_get_unregistered_model(self):
        info = self.registry.get("nonexistent", 1536)
        assert info is None

    def test_list_index_names(self):
        self.registry.register(
            model_name="text-embedding-3-small",
            dimension=1536,
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
        )
        self.registry.register(
            model_name="bge-m3",
            dimension=1024,
            base_url="https://example.com",
            api_key="sk-test",
        )
        names = self.registry.list_index_names()
        assert len(names) == 2

    def test_clear_registry(self):
        self.registry.register(
            model_name="text-embedding-3-small",
            dimension=1536,
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
        )
        self.registry.clear()
        names = self.registry.list_index_names()
        assert len(names) == 0


class TestGlobalRegistry:
    """Tests for global registry functions."""

    def setup_method(self):
        reset_embedding_registry()

    def teardown_method(self):
        reset_embedding_registry()

    def test_get_global_registry(self):
        reg1 = get_embedding_registry()
        reg2 = get_embedding_registry()
        assert reg1 is reg2

    def test_reset_registry(self):
        reg1 = get_embedding_registry()
        reg1.register(
            model_name="text-embedding-3-small",
            dimension=1536,
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
        )
        reset_embedding_registry()
        reg2 = get_embedding_registry()
        assert len(reg2.list_index_names()) == 0
