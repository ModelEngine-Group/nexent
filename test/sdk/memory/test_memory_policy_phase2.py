"""Unit tests for ``sdk.nexent.memory.policy`` Phase 2 additions."""

import sys
import types
from unittest.mock import MagicMock

import pytest


# Path setup
sys.path.insert(
    0,
    __import__("os").path.join(__import__("os").path.dirname(__file__), "../../.."),
)


# Stub SDK internals
nexent_pkg = types.ModuleType("nexent")
memory_pkg = types.ModuleType("nexent.memory")


class MemoryLayer:
    TENANT = "tenant"
    USER = "user"
    AGENT = "agent"

    def __init__(self, value):
        self.value = value


class MemoryType:
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"

    def __init__(self, value):
        self.value = value


memory_models = types.ModuleType("nexent.memory.models")
memory_models.MemoryLayer = MemoryLayer
memory_models.MemoryType = MemoryType
sys.modules["nexent.memory.models"] = memory_models

memory_pkg.models = memory_models
nexent_pkg.memory = memory_pkg
sys.modules["nexent"] = nexent_pkg
sys.modules["nexent.memory"] = memory_pkg


# Stub the gateway bridge: ``sdk.nexent.memory.embedding_model`` is imported by
# ``sdk/nexent/__init__.py`` and now references the gateway adapters. The real
# gateway eagerly registers every vendor adapter, which pulls absolute
# ``nexent.*`` imports that these mocked modules cannot satisfy.
gateway_pkg = types.ModuleType("sdk.nexent.core.gateway")
gateway_pkg.__path__ = []
modality_pkg = types.ModuleType("sdk.nexent.core.gateway.modality")
modality_pkg.__path__ = []
for _name in ("OpenAICompatibleEmbeddingAdapter", "EmbeddingAdapter", "RerankAdapter"):
    setattr(modality_pkg, _name, MagicMock(name=f"gateway.modality.{_name}"))
gateway_pkg.modality = modality_pkg
gateway_pkg.EmbeddingContext = MagicMock(name="gateway.EmbeddingContext")
sys.modules["sdk.nexent.core.gateway"] = gateway_pkg
sys.modules["sdk.nexent.core.gateway.modality"] = modality_pkg


from sdk.nexent.memory.policy import MemoryRetrievalPolicy


def test_uses_full_context_for_layer_accepts_enum():
    assert MemoryRetrievalPolicy.uses_full_context_for_layer(MemoryLayer.TENANT) is True
    assert MemoryRetrievalPolicy.uses_full_context_for_layer(MemoryLayer.USER) is True
    assert MemoryRetrievalPolicy.uses_full_context_for_layer(MemoryLayer.AGENT) is False


def test_uses_full_context_for_layer_accepts_string():
    assert MemoryRetrievalPolicy.uses_full_context_for_layer("tenant") is True
    assert MemoryRetrievalPolicy.uses_full_context_for_layer("user") is True
    assert MemoryRetrievalPolicy.uses_full_context_for_layer("agent") is False


def test_uses_full_context_for_layer_handles_invalid():
    assert MemoryRetrievalPolicy.uses_full_context_for_layer("bogus") is False
    assert MemoryRetrievalPolicy.uses_full_context_for_layer(None) is False
