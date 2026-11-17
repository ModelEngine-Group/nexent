# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Tests for the immutable authorized run snapshot."""

import pytest

from nexent.core.agents.context import ContextItemInput
from nexent.core.agents.contracts.context import ContextInput


def test_context_input_freezes_authorized_item_collection():
    item = ContextItemInput(id="system:one", type="system", content={"text": "authorized"})

    snapshot = ContextInput(items=(item,))

    assert snapshot.items == (item,)
    with pytest.raises(AttributeError):
        snapshot.items = ()


def test_context_input_rejects_mutable_collection():
    with pytest.raises(TypeError, match="immutable tuples"):
        ContextInput(items=[])


def test_context_input_detaches_nested_payload_from_config_item():
    item = ContextItemInput(
        id="system:one",
        type="system",
        content={"text": "authorized"},
        metadata={"labels": ["original"]},
    )

    snapshot = ContextInput(items=(item,))
    item.content["text"] = "mutated"
    item.metadata["labels"].append("mutated")

    assert snapshot.items[0].content == {"text": "authorized"}
    assert snapshot.items[0].metadata == {"labels": ["original"]}
