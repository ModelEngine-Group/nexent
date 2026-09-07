import json
from types import SimpleNamespace

from nexent.core.agents.context.config import ContextManagerConfig
from nexent.core.agents.context.manager import ContextManager
from nexent.core.agents.context.models import ContextItem, ContextItemInput, ContextItemType


def _item(item_id, item_type, content, metadata=None):
    metadata = metadata or {}
    if item_type == ContextItemType.MEMORY:
        metadata = {"render_group": "memory", **metadata}
    return ContextItem.from_input(ContextItemInput(
        id=item_id, type=item_type, content=content, metadata=metadata,
    ))


class _Model:
    model_id = "test-model"

    def __init__(self):
        self.calls = 0

    def __call__(self, messages, stop_sequences):
        self.calls += 1
        prompt = json.loads(messages[0].content[0]["text"])
        return SimpleNamespace(content=json.dumps({
            "selections": {scope: [block["id"] for block in blocks]
                           for scope, blocks in prompt["blocks"].items()}
        }))


def test_under_budget_does_not_call_selector():
    manager = ContextManager(ContextManagerConfig(token_threshold=1000, chars_per_token=1.0))
    model = _Model()
    items = [_item("memory:user", ContextItemType.MEMORY, {"memory": "## P\n\n- concise"},
                   {"version_id": 1, "memory_type": "long_term", "scope": "user"})]
    result = manager._compact_to_soft_budget(items, [], [], [], model=model)
    assert result == items
    assert model.calls == 0


def test_tenant_and_user_use_one_call_and_later_action_hits_task_cache():
    manager = ContextManager(ContextManagerConfig(token_threshold=80, chars_per_token=1.0, keep_recent_steps=0))
    model = _Model()
    memories = [
        _item("memory:tenant", ContextItemType.MEMORY, {"memory": "## Policy\n\n- safe " * 20},
              {"version_id": 1, "memory_type": "long_term", "scope": "tenant"}),
        _item("memory:user", ContextItemType.MEMORY, {"memory": "## Preference\n\n- concise " * 20},
              {"version_id": 2, "memory_type": "long_term", "scope": "user"}),
    ]
    task = _item("current_task:0", ContextItemType.CURRENT_TASK, {"text": "answer"})
    first = manager._compact_to_soft_budget([*memories, task], [], [], [], model=model)
    action = _item("current_action:0", ContextItemType.CURRENT_ACTION, {"result": "done"})
    second = manager._compact_to_soft_budget([*memories, task, action], [], [], [], model=model)
    assert model.calls == 1
    assert any(item.metadata.get("representation") == "selected_blocks" for item in first)
    assert any(item.metadata.get("representation") == "selected_blocks" for item in second)
