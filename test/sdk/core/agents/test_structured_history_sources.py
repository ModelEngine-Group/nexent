# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""SC-001..003: source-covered bulk is recoverable, outside facts remain strict."""

import json
from types import SimpleNamespace

import pytest
from nexent.core.agents.context import (
    ContextItem,
    ContextItemInput,
    ContextManager,
    ContextManagerConfig,
)
from nexent.core.agents.context.action_history import register_authorized_sources
from nexent.core.agents.context.execution_history import ExecutionHistory
from nexent.core.agents.context.native_history import decode_history_event
from nexent.core.agents.cores.smolagents.context import ManagedContextRuntime
from smolagents.memory import TaskStep
from test_context_message_format import records
from test_history_capacity_recovery import SUMMARY


OWNER = "authorized-history-owner"


def bulk_runtime(mocker, message_format, *, outside=False, incomplete=False):
    page = {
        "batch": 7,
        "rows": [
            {
                "record": f"business-record-{i:05d}",
                "amount": 100000 + i,
                "credit": 100 + i,
                "description": "original row data " * 20,
            }
            for i in range(80)
        ],
    }
    original = json.dumps(page, separators=(",", ":"))
    native = records(count=1)
    for index, record in enumerate(native, 1):
        record["unit_index"] = index
        if record["record_type"] == "tool_result":
            event = json.loads(record["content"])
            previous_result = event["result"]
            event["result"] = original[:-1] if incomplete else original
            if event.get("content") == previous_result:
                event["content"] = event["result"]
            record["content"] = json.dumps(event)
            record["execution_event"] = decode_history_event(record)
    turn = ContextItem.from_input(
        ContextItemInput(
            id="old",
            type="conversation_turn",
            content={
                "user_message": (
                    "Explicit task fact business-record-00001 must remain inline."
                    if outside
                    else "Inspect the saved row data, preserving source truth."
                ),
                "assistant_final_answer": "The native call completed.",
                "user_message_id": 41,
                "assistant_message_id": 42,
                "execution_records": native,
            },
        )
    )
    history = ExecutionHistory()
    items = register_authorized_sources([turn], history, OWNER)
    config = ContextManagerConfig(
        context_window_tokens=20000,
        effective_input_limit_tokens=20000,
        chars_per_token=1,
        compaction_trigger_threshold_tokens=16000,
        compaction_target_tokens=12000,
        execution_history=history,
        policy_layers={"platform": {"processing_mode": "adaptive_compact"}},
    )
    config.execution_owner = OWNER
    manager = ContextManager(config, message_format=message_format)
    # Keep non-bulk call identities; no row identifiers are enumerated by this model output.
    generated = mocker.patch.object(
        manager._history_compressor._llm,
        "generate_summary",
        return_value=SimpleNamespace(
            summary_text=SUMMARY
            + "\nNative call step-a-call-0 / local-step-a-0 completed.",
            records=[],
        ),
    )
    runtime = ManagedContextRuntime(manager, items)
    memory = SimpleNamespace(steps=[TaskStep(task="Continue the task")])
    runtime.prepare_run(memory=memory, fallback_system_prompt="Mandatory instructions")
    return (
        runtime,
        memory,
        SimpleNamespace(model_id="controlled"),
        history,
        page,
        original,
        generated,
    )


@pytest.mark.parametrize("message_format", ["codeagent", "openai_chat_completions"])
def test_sc001_real_native_source_allows_bulk_recovery_without_copying_all_row_ids(
    mocker, message_format
):
    runtime, memory, model, history, page, original, generated = bulk_runtime(
        mocker, message_format
    )
    final = runtime.prepare_step(model=model, memory=memory, current_run_start_idx=0)
    assert final.evidence.maintenance_phase == "local_capacity_recovery"
    assert final.evidence.final_token_estimate < 20000
    assert generated.called
    assert "business-record-00079" not in str(final.messages)
    assert "message:42/unit-index:2" in str(final.messages)
    offset = original.index('"amount":100040')
    recalled = json.loads(history.read(OWNER, "message:42/unit-index:2", offset, 60))
    assert recalled["text"] == original[offset : offset + 60]
    assert page["rows"][40]["amount"] == 100040
    with pytest.raises(PermissionError):
        history.read("foreign-owner", "message:42/unit-index:2")


@pytest.mark.parametrize("message_format", ["codeagent", "openai_chat_completions"])
def test_sc002_same_identifier_outside_bulk_is_still_required(mocker, message_format):
    runtime, memory, model, history, page, original, generated = bulk_runtime(
        mocker, message_format, outside=True
    )
    with pytest.raises(ValueError):
        runtime.prepare_step(model=model, memory=memory, current_run_start_idx=0)
    assert generated.called
    assert runtime.context_manager._history_candidate is None
    assert runtime.context_manager._pending_history_summary_event is None


def test_sc003_partial_json_does_not_authorize_bulk_exemption(mocker):
    runtime, memory, model, history, page, original, generated = bulk_runtime(
        mocker, "codeagent", incomplete=True
    )
    with pytest.raises(ValueError):
        runtime.prepare_step(model=model, memory=memory, current_run_start_idx=0)
    assert runtime.context_manager._history_candidate is None
