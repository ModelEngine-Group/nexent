from types import SimpleNamespace

from nexent.core.agents.context.config import ContextManagerConfig
from nexent.core.agents.context.manager import ContextManager
from nexent.core.agents.context.models import (
    ContextItem,
    ContextItemInput,
    ContextItemType,
)


class _Model:
    model_id = "test-model"

    def __init__(self):
        self.calls = []

    def __call__(self, messages, stop_sequences):
        self.calls.append(messages)
        return SimpleNamespace(content="Only the transaction rollback preference.")


def _item(item_id, item_type, content, metadata=None):
    return ContextItem.from_input(
        ContextItemInput(
            id=item_id,
            type=item_type,
            content=content,
            metadata=metadata or {},
        )
    )


def test_ac026_long_term_compaction_is_turn_aware_cached_and_run_local():
    manager = ContextManager(
        ContextManagerConfig(token_threshold=400, chars_per_token=1.0)
    )
    memory = _item(
        "memory:active",
        ContextItemType.MEMORY,
        {
            "memory": (
                "The user prefers transaction rollback behavior. "
                "They also like blue dashboards. "
            )
            * 20
        },
        {"version_id": 7, "memory_type": "long_term"},
    )
    task = _item(
        "current_task:0",
        ContextItemType.CURRENT_TASK,
        {"text": "How should this database transaction be rolled back?"},
    )
    model = _Model()

    first = manager._compact_long_term_memory(memory, [memory, task], model=model)
    second = manager._compact_long_term_memory(memory, [memory, task], model=model)

    assert first.content["memory"] == "Only the transaction rollback preference."
    assert first.metadata["compact_scope"] == "run_turn"
    assert first.metadata["version_id"] == 7
    assert "persisted" not in first.metadata
    assert second is first
    assert len(model.calls) == 1
    assert memory.content["memory"].startswith("The user prefers")
    records = manager.get_all_compression_stats()["records"]
    record = records[0]
    assert record.call_type == "long_term_memory_turn_compact"
    assert record.details["persisted"] is False
    assert record.output_tokens <= record.details["target_tokens"]
    assert records[1].cache_hit is True


def test_ac026_long_term_compaction_rejects_over_target_output_and_records_failure():
    manager = ContextManager(
        ContextManagerConfig(token_threshold=256, chars_per_token=1.0)
    )
    memory = _item(
        "memory:active",
        ContextItemType.MEMORY,
        {"memory": "source fact " * 100},
        {"version_id": 8, "memory_type": "long_term"},
    )
    task = _item(
        "current_task:0",
        ContextItemType.CURRENT_TASK,
        {"text": "Find relevant facts"},
    )

    class _OverTargetModel:
        model_id = "over-target"

        def __call__(self, messages, stop_sequences):
            return SimpleNamespace(content="x" * 100)

    compacted = manager._compact_long_term_memory(
        memory, [memory, task], model=_OverTargetModel()
    )

    assert compacted is memory
    record = manager.get_all_compression_stats()["records"][0]
    assert record.details["outcome"] == "invalid_output"
    assert record.output_tokens > record.details["target_tokens"]


def test_ac026_current_action_changes_turn_cache_key():
    manager = ContextManager(
        ContextManagerConfig(token_threshold=400, chars_per_token=1.0)
    )
    memory = _item(
        "memory:active",
        ContextItemType.MEMORY,
        {"memory": "stable transaction preference " * 30},
        {"version_id": 9, "memory_type": "long_term"},
    )
    task = _item(
        "current_task:0",
        ContextItemType.CURRENT_TASK,
        {"text": "Manage the transaction"},
    )
    first_action = _item(
        "current_action:0",
        ContextItemType.CURRENT_ACTION,
        {"result": "Transaction opened"},
    )
    second_action = _item(
        "current_action:1",
        ContextItemType.CURRENT_ACTION,
        {"result": "Rollback requested"},
    )
    model = _Model()

    first = manager._compact_long_term_memory(
        memory, [memory, task, first_action], model=model
    )
    second = manager._compact_long_term_memory(
        memory, [memory, task, first_action, second_action], model=model
    )

    assert len(model.calls) == 2
    assert first.metadata["turn_context_hash"] != second.metadata["turn_context_hash"]
