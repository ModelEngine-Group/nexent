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


from sdk.nexent.memory.policy import MemoryStoragePolicy


def test_uses_full_context_for_layer_accepts_enum():
    assert MemoryStoragePolicy.uses_full_context_for_layer(MemoryLayer.TENANT) is True
    assert MemoryStoragePolicy.uses_full_context_for_layer(MemoryLayer.USER) is True
    assert MemoryStoragePolicy.uses_full_context_for_layer(MemoryLayer.AGENT) is False


def test_uses_full_context_for_layer_accepts_string():
    assert MemoryStoragePolicy.uses_full_context_for_layer("tenant") is True
    assert MemoryStoragePolicy.uses_full_context_for_layer("user") is True
    assert MemoryStoragePolicy.uses_full_context_for_layer("agent") is False


def test_uses_full_context_for_layer_handles_invalid():
    assert MemoryStoragePolicy.uses_full_context_for_layer("bogus") is False
    assert MemoryStoragePolicy.uses_full_context_for_layer(None) is False