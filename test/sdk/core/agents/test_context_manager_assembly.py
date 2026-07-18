"""Focused tests for ContextManager-owned managed assembly."""
from __future__ import annotations

from nexent.core.agents.agent_context import ContextManager
from nexent.core.agents.context import ContextItemInput
from nexent.core.agents.summary_config import ContextManagerConfig


def _message_text(message):
    """Extract text from list-format or string-format message content."""
    content = message["content"] if isinstance(message, dict) else message.content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    return content


def _text_item(item_id, text, role="system"):
    item_type = "system_prompt" if role == "system" else "history"
    return ContextItemInput(id=item_id, type=item_type, content={"text": text, "role": role})


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
    manager = ContextManager(ContextManagerConfig(enabled=True, token_threshold=10000))
    manager.register_item(_text_item("system:policy", "stable policy"))
    manager.register_item(_text_item("history:memory", "memory fact", "user"))
    manager.register_item(ContextItemInput(
        id="kb:fact", type="knowledge_base", content={"text": "kb fact", "role": "user"}
    ))
    memory = _Memory()

    manager.prepare_run_context(memory=memory, fallback_system_prompt="legacy")
    memory.steps.append(_Step("user", "current task"))
    final = manager.assemble_final_context(
        model=None,
        memory=memory,
        current_run_start_idx=0,
        tools=[{"name": "z"}, {"name": "a"}],
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


def test_context_manager_owns_final_answer_assembly():
    manager = ContextManager(ContextManagerConfig(enabled=True, token_threshold=10000))
    manager.register_item(_text_item("system:policy", "stable policy"))
    manager.register_item(_text_item("history:memory", "memory fact", "user"))
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
    assert [_message_text(message) for message in final.messages[:4]] == [
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
    manager = ContextManager(ContextManagerConfig(enabled=True, token_threshold=10000))
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
