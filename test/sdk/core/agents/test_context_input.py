"""Tests for the immutable authorized run snapshot."""

import pytest

from sdk.nexent.core.agents.context import ContextItemInput
from sdk.nexent.core.agents.context_input import ContextInput


def test_context_input_freezes_authorized_item_collection():
    item = ContextItemInput(id="system:one", type="system_prompt", content={"text": "authorized"})

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
        type="system_prompt",
        content={"text": "authorized"},
        metadata={"labels": ["original"]},
    )

    snapshot = ContextInput(items=(item,))
    item.content["text"] = "mutated"
    item.metadata["labels"].append("mutated")

    assert snapshot.items[0].content == {"text": "authorized"}
    assert snapshot.items[0].metadata == {"labels": ["original"]}
