"""Focused tests for ContextManager-owned managed assembly."""
from __future__ import annotations

from nexent.core.agents.agent_context import ContextManager
from nexent.core.agents.agent_model import (
    KnowledgeBaseComponent,
    MemoryComponent,
    SystemPromptComponent,
)
from nexent.core.agents.summary_config import ContextManagerConfig


class _Memory:
    def __init__(self):
        self.system_prompt = None
        self.steps = []


class _Step:
    def __init__(self, role, content):
        self.role = role
        self.content = content

    def to_messages(self):
        return [{"role": self.role, "content": self.content}]


def test_context_manager_assembles_stable_dynamic_and_history_messages():
    manager = ContextManager(ContextManagerConfig(enabled=True, token_threshold=10000))
    manager.register_component(SystemPromptComponent(content="stable policy"))
    manager.register_component(MemoryComponent(formatted_content="memory fact"))
    manager.register_component(KnowledgeBaseComponent(summary="kb fact"))
    memory = _Memory()

    manager.prepare_run_context(memory=memory, fallback_system_prompt="legacy")
    memory.steps.append(_Step("user", "current task"))
    final = manager.assemble_final_context(
        model=None,
        memory=memory,
        current_run_start_idx=0,
        tools=[{"name": "z"}, {"name": "a"}],
    )

    assert [message["content"] for message in final.messages] == [
        "stable policy",
        "memory fact",
        "kb fact",
        "current task",
    ]
    assert final.evidence.stable_message_count == 1
    assert final.evidence.dynamic_message_count == 3
    assert final.evidence.stable_prefix_fingerprint
    assert final.tools == [{"name": "a"}, {"name": "z"}]


def test_context_manager_owns_final_answer_assembly():
    manager = ContextManager(ContextManagerConfig(enabled=True, token_threshold=10000))
    manager.register_component(SystemPromptComponent(content="stable policy"))
    manager.register_component(MemoryComponent(formatted_content="memory fact"))
    memory = _Memory()

    manager.prepare_run_context(memory=memory, fallback_system_prompt="legacy")
    memory.steps.append(_Step("assistant", "work trace"))
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
    )

    assert [message["role"] for message in final.messages] == [
        "system",
        "system",
        "user",
        "user",
        "assistant",
    ]
    assert [message["content"] for message in final.messages[:4]] == [
        "stable policy",
        "final instruction",
        "memory fact",
        "answer task: original task",
    ]
    assert final.evidence.stable_message_count == 2
    assert "context_purpose" in final.evidence.prefix_change_reasons or (
        final.evidence.prefix_change_reasons == ("initial_request",)
    )


def test_context_manager_attributes_tool_schema_change():
    manager = ContextManager(ContextManagerConfig(enabled=True, token_threshold=10000))
    manager.register_component(SystemPromptComponent(content="stable policy"))
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
    manager = ContextManager(ContextManagerConfig(enabled=True, token_threshold=10000))
    manager.register_component(SystemPromptComponent(content="stable policy"))
    memory = _Memory()

    run_context = manager.prepare_run_context(memory=memory, fallback_system_prompt="legacy")
    manager.assemble_final_context(
        model=None,
        memory=memory,
        current_run_start_idx=0,
        tools=[{"name": "search"}],
        run_context=run_context,
    )

    manager.clear_components()
    manager.register_component(SystemPromptComponent(content="new stable policy"))
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
