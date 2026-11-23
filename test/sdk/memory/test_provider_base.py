"""Unit tests for ``sdk.nexent.memory.providers.base``.

Covers:
- SearchableMemoryProvider / IngestibleMemoryProvider Protocols
- BaseMemoryProvider init / _build_headers / validate_config
"""

import pytest

from nexent.memory.providers.base import (
    BaseMemoryProvider,
    IngestibleMemoryProvider,
    SearchableMemoryProvider,
)


# ---------------------------------------------------------------------------
# Protocol satisfaction
# ---------------------------------------------------------------------------


class _SearchableConcrete:
    """Minimal concrete implementation of SearchableMemoryProvider."""

    @property
    def provider_name(self) -> str:
        return "searchable-1"

    async def search(self, request, limit=5, filters=None):
        return ["hit-1"]


class _IngestibleConcrete:
    """Minimal concrete implementation of IngestibleMemoryProvider."""

    @property
    def provider_name(self) -> str:
        return "ingestible-1"

    async def ingest(self, request):
        return "ok"


class _BothConcrete:
    """Implements both protocols."""

    @property
    def provider_name(self) -> str:
        return "both-1"

    async def search(self, request, limit=5, filters=None):
        return []

    async def ingest(self, request):
        return "ok"


def test_searchable_provider_protocol_satisfied_by_concrete_class():
    assert isinstance(_SearchableConcrete(), SearchableMemoryProvider)


def test_ingestible_provider_protocol_satisfied_by_concrete_class():
    assert isinstance(_IngestibleConcrete(), IngestibleMemoryProvider)


def test_provider_satisfies_both_protocols():
    assert isinstance(_BothConcrete(), SearchableMemoryProvider)
    assert isinstance(_BothConcrete(), IngestibleMemoryProvider)


def test_protocol_rejects_class_missing_required_methods():
    class _Incomplete:
        provider_name = "incomplete"

        async def search(self, request, limit=5, filters=None):
            return []

    # Missing `ingest` → should not satisfy IngestibleMemoryProvider.
    assert isinstance(_Incomplete(), SearchableMemoryProvider)
    assert not isinstance(_Incomplete(), IngestibleMemoryProvider)


def test_protocol_rejects_class_missing_search():
    class _Incomplete:
        provider_name = "incomplete"

        async def ingest(self, request):
            return "ok"

    assert not isinstance(_Incomplete(), SearchableMemoryProvider)
    assert isinstance(_Incomplete(), IngestibleMemoryProvider)


# ---------------------------------------------------------------------------
# BaseMemoryProvider: init / state
# ---------------------------------------------------------------------------


def test_base_provider_initializes_all_fields():
    provider = BaseMemoryProvider(
        provider_name="p1",
        api_key="k1",
        base_url="https://api.example.com",
        timeout=42,
    )
    # The private attribute is set in __init__; the public `provider_name`
    # property is provided by concrete subclasses.
    assert provider._provider_name == "p1"
    assert provider.api_key == "k1"
    assert provider.base_url == "https://api.example.com"
    assert provider.timeout == 42


def test_base_provider_defaults():
    provider = BaseMemoryProvider(provider_name="p1")
    assert provider._provider_name == "p1"
    assert provider.api_key is None
    assert provider.base_url is None
    assert provider.timeout == 30


def test_base_provider_supports_string_name():
    """The provider_name can be any string identifier."""
    for name in ("openai", "mem0", "a-very-long-custom-name-123", "ascii-only"):
        provider = BaseMemoryProvider(provider_name=name)
        assert provider._provider_name == name


# ---------------------------------------------------------------------------
# BaseMemoryProvider: _build_headers
# ---------------------------------------------------------------------------


def test_build_headers_without_api_key():
    provider = BaseMemoryProvider(provider_name="p1")
    headers = provider._build_headers()
    assert headers == {"Content-Type": "application/json"}
    assert "Authorization" not in headers


def test_build_headers_with_api_key():
    provider = BaseMemoryProvider(provider_name="p1", api_key="super-secret-key")
    headers = provider._build_headers()
    assert headers == {
        "Content-Type": "application/json",
        "Authorization": "Bearer super-secret-key",
    }


def test_build_headers_with_empty_api_key():
    """An empty api_key is falsy → no Authorization header added."""
    provider = BaseMemoryProvider(provider_name="p1", api_key="")
    headers = provider._build_headers()
    assert "Authorization" not in headers
    assert headers["Content-Type"] == "application/json"


def test_build_headers_includes_content_type_always():
    for key in (None, "valid-key"):
        p = BaseMemoryProvider(provider_name="p", api_key=key)
        headers = p._build_headers()
        assert headers["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# BaseMemoryProvider: validate_config
# ---------------------------------------------------------------------------


def test_validate_config_raises_when_provider_name_not_overridden():
    """When the subclass does not implement provider_name, validate_config fails.

    The current implementation references ``self.provider_name`` which only
    exists on subclasses (the base class sets ``_provider_name``). Until the
    base class exposes a property, calling ``validate_config`` without a
    subclass-defined ``provider_name`` raises ``AttributeError``. This test
    pins the current behaviour; if a future change adds the property the
    test should be updated.
    """
    provider = BaseMemoryProvider(provider_name="valid")
    with pytest.raises(AttributeError):
        provider.validate_config()


def test_validate_config_via_subclass_accepts_non_empty_name():
    """When the subclass exposes a provider_name property, validation passes."""

    class _Subclass(BaseMemoryProvider):
        @property
        def provider_name(self):
            return self._provider_name

    provider = _Subclass(provider_name="valid")
    provider.validate_config()


def test_validate_config_via_subclass_rejects_empty_name():
    class _Subclass(BaseMemoryProvider):
        @property
        def provider_name(self):
            return self._provider_name

    provider = _Subclass(provider_name="")
    with pytest.raises(ValueError, match="provider_name is required"):
        provider.validate_config()


def test_validate_config_via_subclass_allows_misc_configurations():
    """validate_config only checks provider_name; other fields are not validated."""

    class _Subclass(BaseMemoryProvider):
        @property
        def provider_name(self):
            return self._provider_name

    provider = _Subclass(
        provider_name="custom",
        api_key=None,
        base_url=None,
        timeout=0,
    )
    provider.validate_config()
    assert provider.timeout == 0
