# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""SR-003..005: withdrawn recovery/source capabilities cannot be reactivated by old data."""

import importlib.util
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from smolagents.memory import TaskStep

from nexent.core.agents.context import (
    ContextItem,
    ContextItemInput,
    ContextManager,
    ContextManagerConfig,
)
from nexent.core.agents.context.action_history import (
    decode_execution_fields,
    register_historical_results,
)
from nexent.core.agents.context.execution_history import ExecutionHistory, result_text
from nexent.core.agents.context.history_compression import _validate_summary_contract
from test_persisted_codeagent_actions import history_turn
from test_post_response_context import runtime as make_runtime


@pytest.mark.parametrize("reclaimable_history", [False, True])
@pytest.mark.parametrize("message_format", ["codeagent", "openai_chat_completions"])
def test_first_oversized_prompt_does_not_dispatch_recovery_or_mutate_history(mocker, message_format, reclaimable_history):
    runtime = make_runtime(10000, message_format=message_format)
    manager = runtime.context_manager
    manager.config.history_summary_sink = mocker.Mock()
    summarize = mocker.patch.object(manager._history_compressor, "compress", side_effect=AssertionError("No recovery"))
    turn = history_turn(2, execution_records=[], question="h" * 4500 if reclaimable_history else "old task",
                        answer="completed")
    runtime.replace_items([turn])
    task = "n" * 7000 if reclaimable_history else "new oversized prompt " * 10000
    memory = SimpleNamespace(steps=[TaskStep(task=task)])
    model = SimpleNamespace(model_id="local-no-provider")
    runtime.prepare_run(memory=memory, fallback_system_prompt="Original system")
    before = deepcopy(runtime.items)
    context = runtime.prepare_step(model=model, memory=memory, current_run_start_idx=0)
    assert task in str(context.messages)
    assert runtime.usage_baseline.pending_estimate > manager.effective_input_limit_tokens
    summarize.assert_not_called()
    manager.config.history_summary_sink.assert_not_called()
    assert runtime.items == before and manager._history_candidate is None


@pytest.mark.parametrize(
    "text",
    [
        "ordinary accepted summary",
        "Keep result <OUTPUT_REF>message:42/unit-index:5</OUTPUT_REF>",
        "Retired user <OUTPUT_REF>message:41/user-message</OUTPUT_REF> typed source sha256:old /rows row_count=2",
    ],
)
@pytest.mark.parametrize("message_format", ["codeagent", "openai_chat_completions"])
def test_old_checkpoint_body_is_data_not_authorization(text, message_format):
    fetch = SimpleNamespace(calls=0)

    def read_persisted(*_):
        fetch.calls += 1
        raise AssertionError("No arbitrary database lookup")

    store = ExecutionHistory(read_persisted)
    item = ContextItem.from_input(
        ContextItemInput(
            id="old-checkpoint",
            type="history_summary",
            content={
                "summary": text,
                "covered_through_message_id": 42,
                "structured_source_proofs": [{"source_ref": "message:41/user-message"}],
                "execution_sources": [
                    {
                        "message_id": 42,
                        "unit_index": 5,
                        "content": json.dumps(
                            {"content": result_text({"STDOUT": "private"})}
                        ),
                    }
                ],
            },
            metadata={
                "execution_source_refs": ["message:41/user-message"],
                "structured_source_proofs": ["old"],
            },
        )
    )
    before = (deepcopy(item.content), deepcopy(item.metadata))
    registered = register_historical_results([item], store, "fresh")
    wire = ContextManager(message_format=message_format).build_context_messages(
        registered
    )
    assert text in str(wire) and (item.content, item.metadata) == before
    assert registered[0].metadata == {}
    with pytest.raises(PermissionError):
        store.read("fresh", "message:42/unit-index:5")
    with pytest.raises(ValueError):
        store.read("fresh", "message:41/user-message")
    assert fetch.calls == 0
    assert not hasattr(store, "structured_source_index") and not hasattr(
        store, "authorized_sources"
    )


def test_only_actual_authorized_result_reenables_an_existing_execution_reference():
    store = ExecutionHistory()
    turn = history_turn(question="old task", answer="done")
    register_historical_results([turn], store, "fresh")
    assert (
        "actual stdout"
        in json.loads(store.read("fresh", "message:42/unit-index:5"))["text"]
    )
    with pytest.raises(PermissionError):
        store.read("foreign", "message:42/unit-index:5")
    with pytest.raises(ValueError):
        store.read("fresh", "message:41/user-message")


@pytest.mark.parametrize(
    "raw",
    ["\x1b[31merror\x1b[0m", "\0\1\x1f", "progress\r\nnext\r", "中文🙂\t&<literal>"],
)
def test_real_log_control_characters_roundtrip_and_paginate(raw):
    fields = {"STDOUT": raw, "OUTPUT": "", "ERROR": raw}
    canonical = result_text(fields)
    assert decode_execution_fields({"content": canonical}) == fields
    store = ExecutionHistory()
    store.restore("owner", 42, 5, fields)
    middle = len(canonical) // 2
    assert (
        json.loads(store.read("owner", "message:42/unit-index:5", middle, 4))["text"]
        == canonical[middle : middle + 4]
    )
    with pytest.raises(PermissionError):
        store.read("other", "message:42/unit-index:5")


@pytest.mark.parametrize(
    "bad", ["<STDOUT>unclosed", "<STDOUT>ok</STDOUT>\ntrailing", "<OTHER>wrong</OTHER>"]
)
def test_malformed_execution_channels_are_not_granted(bad):
    assert decode_execution_fields({"content": bad}) is None


def test_original_summary_contract_does_not_add_a_missing_title():
    keys = tuple(ContextManagerConfig().summary_json_schema)
    body = "\n\n".join(
        "## " + key.replace("_", " ").title() + "\nRetained facts." for key in keys
    )
    assert _validate_summary_contract(body, keys) is None
    assert _validate_summary_contract("# Compact Result of History\n\n" + body, keys)


def test_withdrawn_modules_are_not_importable():
    assert importlib.util.find_spec("nexent.core.agents.context.recovery") is None
    assert (
        importlib.util.find_spec("nexent.core.agents.context.structured_sources")
        is None
    )


def test_legacy_native_records_without_unit_index_keep_protocol_history_without_granting_a_ref():
    from test_context_message_format import records as native_records

    entries = native_records(count=1)
    for record in entries:
        record.pop('unit_index', None)
    item = ContextItem.from_input(ContextItemInput(id='legacy', type='conversation_turn', content={
        'user_message': 'old task', 'assistant_final_answer': 'done', 'user_message_id': 41,
        'assistant_message_id': 42, 'execution_records': entries}))
    store = ExecutionHistory()
    registered = register_historical_results([item], store, 'new')
    messages = ContextManager(message_format='openai_chat_completions').build_context_messages(registered)
    assert any(message.get('tool_calls') for message in messages)
    assert any(message.get('role') == 'tool' for message in messages)
    with pytest.raises(PermissionError):
        store.read('new', 'message:42/unit-index:1')
