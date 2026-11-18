# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Unit tests for ``nexent.memory.policy`` Phase 2 additions."""

from nexent.memory.models import MemoryLayer
from nexent.memory.policy import MemoryRetrievalPolicy


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
