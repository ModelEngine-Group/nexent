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
    assert final.tools == [{"name": "a"}, {"name": "z"}]


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
        "assistant",
        "user",
    ]
    assert [_message_text(message) for message in final.messages[:3]] == [
        "stable policy",
        "final instruction",
        "memory fact",
    ]
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
