import pytest
from pydantic import ValidationError

from nexent.core.agents.context import (
    ContextItem, ContextItemInput, ContextItemRenderer, ContextItemType,
    ConversationTurnContextItem, HistorySummaryContextItem,
    normalize_context_inputs,
)


def test_context_item_types_match_runtime_regions():
    assert {kind.value for kind in ContextItemType} == {
        "system", "tool", "skill", "memory", "knowledge_base",
        "managed_agent", "external_agent", "history_summary",
        "conversation_turn", "current_task", "current_planning", "current_action",
    }


def test_input_is_serializable_and_does_not_retain_source_objects():
    value = ContextItemInput(id="system", type="system", content={"text": "policy"})
    item = ContextItem.from_input(value)
    assert item.content == {"text": "policy"}
    assert item.token_estimate > 0
    with pytest.raises(ValidationError, match="JSON serializable"):
        ContextItemInput(id="x", type="system", content={"text": object()})
    with pytest.raises(ValidationError, match="_source_component"):
        ContextItemInput(id="x", type="system", content={"text": "x"}, metadata={"_source_component": "x"})


def test_turn_is_atomic_and_summary_is_a_separate_item():
    turn = ContextItemInput(id="turn", type="conversation_turn", content={
        "user_message": "question", "assistant_final_answer": "answer",
        "user_message_id": 1, "assistant_message_id": 2,
    })
    summary = ContextItemInput(id="summary", type="history_summary", content={
        "summary": {"task_overview": "older"}, "covered_through_message_id": 2,
    })
    items = normalize_context_inputs([turn, summary])
    assert [item.type.value for item in items] == ["history_summary", "conversation_turn"]
    assert isinstance(items[0], HistorySummaryContextItem)
    assert isinstance(items[1], ConversationTurnContextItem)
    assert all(not item.supports_compact for item in items)
    messages = ContextItemRenderer().render(items)
    assert [message["role"] for message in messages] == ["user", "user", "assistant"]


def test_turn_requires_complete_pair_and_message_ids():
    with pytest.raises(ValidationError, match="assistant_final_answer"):
        ContextItemInput(id="turn", type="conversation_turn", content={
            "user_message": "question", "user_message_id": 1, "assistant_message_id": 2,
        })


def test_current_action_compact_keeps_tool_result_and_removes_reasoning():
    item = ContextItem.from_input(ContextItemInput(
        id="action", type="current_action",
        content={
            "step_number": 1, "tool_calls": [{"name": "search", "arguments": {"q": "x"}}],
            "observations": "o" * 5000, "error": None, "result": "done",
            "model_output": "private process", "messages": [{"role": "assistant", "content": "raw"}],
        },
    ))
    compact = item.compact()
    assert compact.content["tool_calls"] == item.content["tool_calls"]
    assert "done" in compact.content["result"]
    assert len(compact.content["observations"]) < 5000
    assert "model_output" not in compact.content
    assert "messages" not in compact.content


def test_compact_failure_is_not_cached(monkeypatch):
    item = ContextItem.from_input(ContextItemInput(id="kb", type="knowledge_base", content={"text": "x"}))
    calls = 0
    def fail():
        nonlocal calls
        calls += 1
        raise RuntimeError("failed")
    monkeypatch.setattr(item, "_build_compact_result", fail)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            item.compact()
    assert calls == 2
    assert item.representation_cache_stats == (0, 0)


def test_normalization_rejects_duplicate_ids_and_copies_payload():
    value = ContextItemInput(id="same", type="system", content={"text": "one"})
    with pytest.raises(ValueError, match="duplicate"):
        normalize_context_inputs([value, value])
    item = ContextItem.from_input(value)
    value.content["text"] = "mutated"
    assert item.content["text"] == "one"
