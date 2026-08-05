"""Tests for provider registry."""

import pytest

from nexent.memory.providers.registry import (
    ProviderRegistry,
    get_provider_registry,
    reset_provider_registry,
)
from nexent.memory.providers.base import BaseMemoryProvider, SearchableMemoryProvider


class MockSearchableProvider:
    """Mock searchable provider for testing."""

    def __init__(self, name: str):
        self._name = name

    @property
    def provider_name(self) -> str:
        return self._name

    async def search(self, request, limit=5, filters=None):
        return []


class TestProviderRegistry:
    """Tests for ProviderRegistry."""

    def setup_method(self):
        self.registry = ProviderRegistry()

    def test_register_provider(self):
        provider = MockSearchableProvider("test-provider")
        self.registry.register(provider)
        assert "test-provider" in self.registry.list_providers()

    def test_get_registered_provider(self):
        provider = MockSearchableProvider("test-provider")
        self.registry.register(provider)
        retrieved = self.registry.get("test-provider")
        assert retrieved is provider

    def test_get_unregistered_provider(self):
        retrieved = self.registry.get("nonexistent")
        assert retrieved is None

    def test_unregister_provider(self):
        provider = MockSearchableProvider("test-provider")
        self.registry.register(provider)
        result = self.registry.unregister("test-provider")
        assert result is True
        assert "test-provider" not in self.registry.list_providers()

    def test_unregister_nonexistent(self):
        result = self.registry.unregister("nonexistent")
        assert result is False

    def test_clear_providers(self):
        provider1 = MockSearchableProvider("provider-1")
        provider2 = MockSearchableProvider("provider-2")
        self.registry.register(provider1)
        self.registry.register(provider2)
        self.registry.clear()
        assert len(self.registry.list_providers()) == 0

    def test_list_providers_empty(self):
        assert self.registry.list_providers() == []


class TestGlobalRegistry:
    """Tests for global registry functions."""

    def setup_method(self):
        reset_provider_registry()

    def teardown_method(self):
        reset_provider_registry()

    def test_get_global_registry(self):
        reg1 = get_provider_registry()
        reg2 = get_provider_registry()
        assert reg1 is reg2

    def test_reset_registry(self):
        reg1 = get_provider_registry()
        provider = MockSearchableProvider("test-provider")
        reg1.register(provider)
        reset_provider_registry()
        reg2 = get_provider_registry()
        assert len(reg2.list_providers()) == 0
