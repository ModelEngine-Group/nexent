"""Unit tests for the process-wide adapter registry."""

import pytest
from nexent.core.gateway.registry import AdapterRegistry, get_registry, register_adapter


class _DummyAdapter:
    """Plain placeholder class used as a registered adapter target."""


def test_register_as_decorator_and_resolve():
    registry = AdapterRegistry()
    registry.register("Fake", "vlm")(_DummyAdapter)

    assert registry.resolve("fake", "vlm") is _DummyAdapter
    # Resolution is case-insensitive and strips surrounding whitespace.
    assert registry.resolve("  FAKE ", "vlm") is _DummyAdapter
    assert registry.has("fake", "vlm") is True
    assert registry.has("other", "vlm") is False
    assert registry.list_adapters() == [("fake", "vlm")]


def test_resolve_missing_pair_raises_key_error():
    registry = AdapterRegistry()
    with pytest.raises(KeyError, match="No adapter registered for factory='nope'"):
        registry.resolve("nope", "vlm")


def test_get_registry_returns_shared_singleton():
    assert get_registry() is get_registry()


def test_register_adapter_module_level_alias():
    @register_adapter("dummy", "vlm")
    class _DummyVLMAdapter:
        pass

    assert get_registry().resolve("dummy", "vlm") is _DummyVLMAdapter