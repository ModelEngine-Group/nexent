"""Tests for memory policies."""

import pytest

from nexent.memory.models import MemoryLayer, MemoryType
from nexent.memory.policy import (
    MemoryAccessPolicy,
    MemoryStoragePolicy,
    MemoryRetrievalPolicy,
)


class TestMemoryAccessPolicy:
    """Tests for MemoryAccessPolicy."""

    def test_agent_can_write_to_agent_short_term(self):
        assert MemoryAccessPolicy.can_agent_write(
            MemoryLayer.AGENT, MemoryType.SHORT_TERM
        ) is True

    def test_agent_cannot_write_to_user_long_term(self):
        assert MemoryAccessPolicy.can_agent_write(
            MemoryLayer.USER, MemoryType.LONG_TERM
        ) is False

    def test_agent_cannot_write_to_tenant_long_term(self):
        assert MemoryAccessPolicy.can_agent_write(
            MemoryLayer.TENANT, MemoryType.LONG_TERM
        ) is False

    def test_agent_cannot_write_to_agent_long_term(self):
        assert MemoryAccessPolicy.can_agent_write(
            MemoryLayer.AGENT, MemoryType.LONG_TERM
        ) is False

    def test_agent_can_read_all_layers(self):
        for layer in MemoryLayer:
            for mem_type in MemoryType:
                assert MemoryAccessPolicy.can_agent_read(layer, mem_type) is True

    def test_dreaming_can_write_to_user_long_term(self):
        assert MemoryAccessPolicy.can_dreaming_write(
            MemoryLayer.USER, MemoryType.LONG_TERM
        ) is True

    def test_dreaming_cannot_write_to_tenant_long_term(self):
        assert MemoryAccessPolicy.can_dreaming_write(
            MemoryLayer.TENANT, MemoryType.LONG_TERM
        ) is False

    def test_dreaming_cannot_write_to_agent_short_term(self):
        assert MemoryAccessPolicy.can_dreaming_write(
            MemoryLayer.AGENT, MemoryType.SHORT_TERM
        ) is False

    def test_get_default_search_layers(self):
        layers = MemoryAccessPolicy.get_default_search_layers()
        assert MemoryLayer.TENANT in layers
        assert MemoryLayer.USER in layers
        assert MemoryLayer.AGENT in layers
        assert len(layers) == 3


class TestMemoryStoragePolicy:
    """Tests for MemoryStoragePolicy."""

    def test_agent_requires_vector_index(self):
        assert MemoryStoragePolicy.requires_vector_index(MemoryLayer.AGENT) is True

    def test_user_does_not_require_vector_index(self):
        assert MemoryStoragePolicy.requires_vector_index(MemoryLayer.USER) is False

    def test_tenant_does_not_require_vector_index(self):
        assert MemoryStoragePolicy.requires_vector_index(MemoryLayer.TENANT) is False

    def test_get_storage_layers_for_agent(self):
        layers = MemoryStoragePolicy.get_storage_layers_for_layer(MemoryLayer.AGENT)
        assert MemoryLayer.AGENT in layers

    def test_get_storage_layers_for_user(self):
        layers = MemoryStoragePolicy.get_storage_layers_for_layer(MemoryLayer.USER)
        assert MemoryLayer.USER in layers

    def test_max_stores_per_run(self):
        assert MemoryStoragePolicy.MAX_STORES_PER_RUN == 3


class TestMemoryRetrievalPolicy:
    """Tests for MemoryRetrievalPolicy."""

    def test_tenant_uses_full_context(self):
        assert MemoryRetrievalPolicy.uses_full_context(MemoryLayer.TENANT) is True

    def test_user_uses_full_context(self):
        assert MemoryRetrievalPolicy.uses_full_context(MemoryLayer.USER) is True

    def test_agent_does_not_use_full_context(self):
        assert MemoryRetrievalPolicy.uses_full_context(MemoryLayer.AGENT) is False

    def test_agent_uses_vector_search(self):
        assert MemoryRetrievalPolicy.uses_vector_search(MemoryLayer.AGENT) is True

    def test_tenant_does_not_use_vector_search(self):
        assert MemoryRetrievalPolicy.uses_vector_search(MemoryLayer.TENANT) is False

    def test_validate_top_k_positive(self):
        result = MemoryRetrievalPolicy.validate_top_k(10)
        assert result == 10

    def test_validate_top_k_zero(self):
        result = MemoryRetrievalPolicy.validate_top_k(0)
        assert result == MemoryRetrievalPolicy.DEFAULT_TOP_K

    def test_validate_top_k_negative(self):
        result = MemoryRetrievalPolicy.validate_top_k(-5)
        assert result == MemoryRetrievalPolicy.DEFAULT_TOP_K

    def test_validate_top_k_exceeds_max(self):
        result = MemoryRetrievalPolicy.validate_top_k(500)
        assert result == MemoryRetrievalPolicy.MAX_TOP_K

    def test_default_top_k(self):
        assert MemoryRetrievalPolicy.DEFAULT_TOP_K == 5

    def test_max_top_k(self):
        assert MemoryRetrievalPolicy.MAX_TOP_K == 100

    def test_default_threshold(self):
        assert MemoryRetrievalPolicy.DEFAULT_THRESHOLD == 0.65
