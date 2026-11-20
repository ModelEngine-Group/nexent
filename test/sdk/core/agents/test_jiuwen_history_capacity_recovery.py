# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Native frames share the bounded historical recovery contract."""

from types import SimpleNamespace

import pytest
from nexent.core.agents.context import ContextItem, ContextItemInput
from test_history_capacity_recovery import SUMMARY
from test_jiuwen_context import make_bridge


def native_recovery(mocker, *, query="CURRENT_TASK", history_chars=24000):
    old = ContextItem.from_input(
        ContextItemInput(
            id="old",
            type="conversation_turn",
            content={
                "user_message": "h" * history_chars,
                "assistant_final_answer": "old fact",
                "user_message_id": 1,
                "assistant_message_id": 2,
            },
        )
    )
    bridge, info = make_bridge("adaptive_compact", [old])
    bridge.context_manager.config.chars_per_token = 1
    info.query = query
    generated = mocker.patch.object(
        bridge.context_manager._history_compressor._llm,
        "generate_summary",
        return_value=SimpleNamespace(summary_text=SUMMARY, records=[]),
    )
    bridge.begin_request()
    return bridge, generated


def test_b003_native_recovery_preserves_instruction_task_schema_and_unfinished_call(
    mocker,
):
    bridge, generated = native_recovery(mocker)
    messages = [
        {"role": "system", "content": "mandatory instruction"},
        {"role": "user", "content": "CURRENT_TASK"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "unfinished",
                    "type": "function",
                    "function": {"name": "lookup", "arguments": "{}"},
                }
            ],
        },
    ]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "authorized lookup",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    result = bridge._assemble(messages, tools)
    assert "mandatory instruction" in str(result) and "CURRENT_TASK" in str(result)
    assert result[-1]["tool_calls"][0]["id"] == "unfinished"
    assert bridge._tools and bridge._tools[0]["name"] == "lookup"
    assert bridge.last_evidence.maintenance_phase == "local_capacity_recovery"
    assert bridge.last_evidence.provider_input_tokens is None
    assert bridge.context_manager._history_candidate.covered_through_message_id == 2
    assert generated.called


@pytest.mark.parametrize(
    "query,history_chars", [("x" * 11000, 24000), ("CURRENT_TASK", 4000)]
)
def test_b001_b002_native_large_protected_and_normal_prepare_never_summarize(
    mocker, query, history_chars
):
    bridge, generated = native_recovery(
        mocker, query=query, history_chars=history_chars
    )
    messages = [{"role": "user", "content": query}]
    if len(query) >= 10000:
        with pytest.raises(ValueError, match="combined context window"):
            bridge._assemble(messages, [])
    else:
        bridge._assemble(messages, [])
    generated.assert_not_called()


def test_b004_native_prepare_reentry_does_not_reset_failed_transaction(mocker):
    bridge, generated = native_recovery(mocker)
    generated.side_effect = RuntimeError("controlled failure")
    messages = [{"role": "user", "content": "CURRENT_TASK"}]
    with pytest.raises(RuntimeError, match="controlled failure"):
        bridge._assemble(messages, [])
    calls = generated.call_count
    budget = bridge._capacity_budget
    with pytest.raises(ValueError):
        bridge._assemble(messages, [])
    assert generated.call_count == calls and bridge._capacity_budget is budget
    assert budget.used and bridge.context_manager._history_candidate is None
