"""Integration tests for run-local ContextItem registration and rendering."""

import pytest

from sdk.nexent.core.agents.context import ContextManager
from sdk.nexent.core.agents.context import ContextItem, ContextItemInput
from sdk.nexent.core.agents.context import ContextManagerConfig


def _item(item_id: str, text: str) -> ContextItemInput:
    return ContextItemInput(id=item_id, type="system", content={"text": text})


def test_context_manager_registers_items_in_order():
    manager = ContextManager(ContextManagerConfig())
    manager.register_item(_item("system:first", "first"))
    manager.register_item(_item("system:second", "second"))

    assert [item.id for item in manager.get_registered_items()] == ["system:first", "system:second"]
    assert [message["content"][0]["text"] for message in manager.build_context_messages()] == ["first", "second"]


def test_context_manager_rejects_duplicate_registered_item_id():
    manager = ContextManager()
    manager.register_item(_item("same", "first"))

    with pytest.raises(ValueError, match="duplicate context item id"):
        manager.register_item(_item("same", "second"))


def test_replace_items_clears_stale_run_data():
    manager = ContextManager()
    manager.register_item(_item("stale", "stale"))

    manager.replace_items([_item("fresh", "fresh")])

    assert [item.id for item in manager.get_registered_items()] == ["fresh"]
    assert "stale" not in str(manager.build_context_messages())


def test_replace_items_is_atomic_when_ids_are_invalid():
    manager = ContextManager()
    manager.register_item(_item("existing", "existing"))

    with pytest.raises(ValueError, match="duplicate context item id"):
        manager.replace_items([_item("same", "one"), _item("same", "two")])

    assert [item.id for item in manager.get_registered_items()] == ["existing"]


def test_replace_items_rejects_mixed_public_and_normalized_items():
    manager = ContextManager()
    public = _item("public", "public")
    normalized = ContextItem.from_input(_item("normalized", "normalized"))

    with pytest.raises(TypeError, match="cannot mix public inputs and normalized items"):
        manager.replace_items([public, normalized])


def test_clear_items_restores_empty_fallback_state():
    manager = ContextManager()
    manager.register_item(_item("system:x", "x"))

    manager.clear_items()

    assert manager.get_registered_items() == []
    assert manager.build_system_prompt() == []
