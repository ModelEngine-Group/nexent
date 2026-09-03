"""Focused tests for ContextManager-owned managed assembly."""
from __future__ import annotations

import pytest
from smolagents.memory import ActionStep, TaskStep
from smolagents.monitoring import Timing

from nexent.core.agents.context import ContextManager
from nexent.core.agents.context import ContextItemInput
from nexent.core.agents.context import ContextManagerConfig


def _message_text(message):
    """Extract text from list-format or string-format message content."""
    content = message["content"] if isinstance(message, dict) else message.content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    return content


def _text_item(item_id, text, role="system"):
    item_type = "system" if role == "system" else "knowledge_base"
    return ContextItemInput(id=item_id, type=item_type, content={"text": text, "role": role})


@pytest.fixture(autouse=True)
def _system_prompt_step(monkeypatch):
    class SystemPromptStep:
        def __init__(self, system_prompt):
            self.system_prompt = system_prompt

        def to_messages(self):
            return [{"role": "system", "content": [{"type": "text", "text": self.system_prompt}]}]

    monkeypatch.setattr("smolagents.memory.SystemPromptStep", SystemPromptStep)


class _Memory:
    def __init__(self):
        self.system_prompt = None
        self.steps = []


class _Step:
    def __init__(self, role, content):
        self.role = role
        self.content = content

    def to_messages(self):
        return [{"role": self.role, "content": [{"type": "text", "text": self.content}]}]


def test_context_manager_assembles_stable_dynamic_and_history_messages():
    manager = ContextManager(ContextManagerConfig(token_threshold=10000))
    manager.register_item(_text_item("system:policy", "stable policy"))
    manager.register_item(_text_item("history:memory", "memory fact", "user"))
    manager.register_item(ContextItemInput(
        id="kb:fact", type="knowledge_base", content={"text": "kb fact", "role": "user"}
    ))
    memory = _Memory()

    run_context = manager.prepare_run_context(memory=memory, fallback_system_prompt="legacy")
    memory.steps.append(TaskStep(task="current task"))
    final = manager.assemble_final_context(
        model=None,
        memory=memory,
        current_run_start_idx=0,
        tools=[{"name": "z"}, {"name": "a"}],
        run_context=run_context,
    )

    assert [_message_text(message) for message in final.messages] == [
        "stable policy",
        "memory fact",
        "kb fact",
        "current task",
    ]
    assert final.evidence.stable_message_count == 1
    assert final.evidence.dynamic_message_count == 3
    assert final.evidence.stable_prefix_fingerprint
    assert final.evidence.purpose == "step"
    assert final.evidence.messages_fingerprint
    assert final.evidence.tools_fingerprint
    assert final.evidence.system_messages_fingerprint
    assert final.evidence.history_messages_fingerprint
    assert final.evidence.message_roles == ("system", "user", "user", "user")
    assert final.evidence.history_message_roles == ("user", "user", "user")
    assert final.tools == [{"name": "a"}, {"name": "z"}]


def test_ac_p6_002_emergency_archive_keeps_recent_turns_and_indexes_older_turns():
    manager = ContextManager(ContextManagerConfig(token_threshold=10000))
    manager.register_item(_text_item("system:policy", "stable policy"))
    for index in range(5):
        manager.register_item(ContextItemInput(
            id=f"turn:{index}",
            type="conversation_turn",
            content={
                "user_message": f"user request {index}",
                "assistant_final_answer": f"answer {index}",
                "user_message_id": index * 2 + 1,
                "assistant_message_id": index * 2 + 2,
            },
            metadata={"layout_order": index},
        ))
    memory = _Memory()
    run_context = manager.prepare_run_context(memory=memory, fallback_system_prompt="")

    final = manager.assemble_final_context(
        model=None, memory=memory, current_run_start_idx=0,
        run_context=run_context, target_input_budget_tokens=9000,
        emergency_archive=True,
    )

    assert final.evidence.archive_active is True
    assert final.evidence.archived_item_count == 2
    assert "turn:0" not in final.evidence.selected_item_ids
    assert "turn:4" in final.evidence.selected_item_ids
    assert [tool.name for tool in final.runtime_tools] == ["search_archived_history"]
    recall = manager.archive_tool.forward("user request 0", kinds=["chat_turn"])
    assert recall["results"][0]["source_id"] == "turn:0"
    rendered = "\n".join(_message_text(message) for message in final.messages)
    assert "user request 0" not in rendered
    assert "search_archived_history" in rendered


def test_context_fingerprint_bounds_cycles_and_excessive_depth():
    manager = ContextManager()
    cyclic = {}
    cyclic["self"] = cyclic
    deeply_nested = current = {}
    for _ in range(40):
        child = {}
        current["child"] = child
        current = child

    normalized_cycle = manager._normalize(cyclic)
    normalized_depth = manager._normalize(deeply_nested)

    assert normalized_cycle["self"]["__cycle__"] == "builtins.dict"
    assert "__max_depth__" in str(normalized_depth)
    assert len(manager._fingerprint(cyclic)) == 64


def test_context_fingerprint_degrades_when_normalization_fails():
    class BrokenDump:
        def model_dump(self):
            raise RuntimeError("broken observational payload")

    fingerprint = ContextManager()._fingerprint([BrokenDump()])

    assert len(fingerprint) == 64


def test_prepare_run_projects_fallback_system_prompt_without_mutating_memory():
    manager = ContextManager(ContextManagerConfig(token_threshold=10000))
    memory = _Memory()

    run_context = manager.prepare_run_context(
        memory=memory,
        fallback_system_prompt="runtime fallback",
    )
    final = manager.assemble_final_context(
        model=None,
        memory=memory,
        current_run_start_idx=0,
        run_context=run_context,
    )

    assert memory.system_prompt is None
    assert [_message_text(message) for message in final.messages] == ["runtime fallback"]
    assert run_context.items[0].id == "system:fallback"


def test_context_manager_owns_final_answer_assembly():
    manager = ContextManager(ContextManagerConfig(token_threshold=10000))
    manager.register_item(_text_item("system:policy", "stable policy"))
    manager.register_item(_text_item("history:memory", "memory fact", "user"))
    memory = _Memory()

    run_context = manager.prepare_run_context(memory=memory, fallback_system_prompt="legacy")
    memory.steps.append(ActionStep(
        step_number=1, timing=Timing(start_time=0), action_output="work trace",
        model_output="work trace",
    ))
    final = manager.assemble_final_context(
        model=None,
        memory=memory,
        current_run_start_idx=0,
        purpose="final_answer",
        task="original task",
        final_answer_templates={
            "final_answer": {
                "pre_messages": "final instruction",
                "post_messages": "answer task: {{ task }}",
            }
        },
        run_context=run_context,
    )

    assert [message["role"] for message in final.messages] == [
        "system",
        "system",
        "user",
        "user",
        "user",
    ]
    assert [_message_text(message) for message in final.messages[:3]] == [
        "stable policy",
        "final instruction",
        "memory fact",
    ]
    action_history = _message_text(final.messages[3])
    assert '<completed_action_history read_only="true">' in action_history
    assert "recorded_result:\nwork trace" in action_history
    assert "Calling tools:" not in action_history
    assert "Observation:" not in action_history
    assert final.evidence.purpose == "final_answer"
    assert final.evidence.final_answer_prompt_fingerprint
    assert _message_text(final.messages[-1]) == "answer task: original task"
    assert final.evidence.stable_message_count == 2
    assert "context_purpose" in final.evidence.prefix_change_reasons or (
        final.evidence.prefix_change_reasons == ("initial_request",)
    )


def test_context_manager_attributes_tool_schema_change():
    manager = ContextManager(ContextManagerConfig(token_threshold=10000))
    manager.register_item(_text_item("system:policy", "stable policy"))
    memory = _Memory()

    manager.prepare_run_context(memory=memory, fallback_system_prompt="legacy")
    first = manager.assemble_final_context(
        model=None,
        memory=memory,
        current_run_start_idx=0,
        tools=[{"type": "function", "function": {"name": "search", "parameters": {}}}],
    )
    second = manager.assemble_final_context(
        model=None,
        memory=memory,
        current_run_start_idx=0,
        tools=[{"type": "function", "function": {"name": "search", "parameters": {"type": "object"}}}],
    )

    assert first.evidence.prefix_change_reasons == ("initial_request",)
    assert second.evidence.prefix_change_reasons == ("tool_schema_version",)


def test_context_manager_reports_multiple_stable_change_reasons():
    manager = ContextManager(ContextManagerConfig(token_threshold=10000))
    manager.register_item(_text_item("system:policy", "stable policy"))
    memory = _Memory()

    run_context = manager.prepare_run_context(memory=memory, fallback_system_prompt="legacy")
    manager.assemble_final_context(
        model=None,
        memory=memory,
        current_run_start_idx=0,
        tools=[{"name": "search"}],
        run_context=run_context,
    )

    manager.clear_items()
    manager.register_item(_text_item("system:policy", "new stable policy"))
    new_run_context = manager.prepare_run_context(memory=memory, fallback_system_prompt="legacy")
    second = manager.assemble_final_context(
        model=None,
        memory=memory,
        current_run_start_idx=0,
        tools=[{"name": "browse"}],
        run_context=new_run_context,
    )

    assert "tool_schema_version" in second.evidence.prefix_change_reasons
    assert "system_prompt_version" in second.evidence.prefix_change_reasons
