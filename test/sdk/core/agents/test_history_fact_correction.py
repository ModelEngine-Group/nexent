# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""SC-007: one concrete fact correction shares the existing recovery budget."""

from types import SimpleNamespace

import pytest
from nexent.core.agents.context import ContextItem, ContextItemInput, ContextManager
from nexent.core.agents.context.history_compression import HistoryCompressor
from nexent.core.agents.context.recovery import (
    ContextRecoveryBudget,
    RecoverySummaryModel,
)
from test_history_capacity_recovery import SUMMARY


class ControlledModel:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = []

    def __call__(self, messages, stop_sequences=None, max_tokens=None):
        self.calls.append(messages)
        return SimpleNamespace(
            content=next(self.outputs),
            token_usage=SimpleNamespace(input_tokens=100, output_tokens=10),
        )


def compressor_and_turn():
    manager = ContextManager()
    turn = ContextItem.from_input(
        ContextItemInput(
            id="old",
            type="conversation_turn",
            content={
                "user_message": "Explicit fact critical-task-001 = Code-123.",
                "assistant_final_answer": "Old accepted work.",
                "user_message_id": 1,
                "assistant_message_id": 2,
            },
        )
    )
    return HistoryCompressor(manager._llm), turn


def test_sc007_one_fact_correction_preserves_original_records_and_budget():
    compressor, turn = compressor_and_turn()
    model = ControlledModel([SUMMARY, SUMMARY + "\ncritical-task-001 = Code-123."])
    budget = ContextRecoveryBudget()
    bounded = RecoverySummaryModel(model, budget, lambda: False)
    result = compressor.compress(None, [turn], bounded, allow_fact_correction=True)
    assert (
        result.candidate is not None
        and len(model.calls) == 2
        and len(result.records) == 2
    )
    assert budget.summary_calls == 2 and budget.fact_correction_used
    assert sum(r.input_tokens for r in result.records) == 200
    assert "Exact protected identifier ledger" in str(model.calls[0])
    assert "critical-task-001" in str(model.calls[1]) and "Code-123" in str(
        model.calls[1]
    )
    assert bounded.claim_fact_correction() is False


def test_sc007_repeat_invalid_does_not_start_another_correction():
    compressor, turn = compressor_and_turn()
    model = ControlledModel([SUMMARY] * 3)
    budget = ContextRecoveryBudget()
    bounded = RecoverySummaryModel(model, budget, lambda: False)
    assert (
        compressor.compress(None, [turn], bounded, allow_fact_correction=True).candidate
        is None
    )
    assert len(model.calls) == 2
    assert (
        compressor.compress(None, [turn], bounded, allow_fact_correction=True).candidate
        is None
    )
    assert len(model.calls) == 3 and budget.summary_calls == 3
    assert (
        compressor.compress(None, [turn], bounded, allow_fact_correction=True).candidate
        is None
    )
    assert len(model.calls) == 3


def test_sc007_correction_never_dispatches_an_oversized_auxiliary_request():
    compressor, turn = compressor_and_turn()
    model = ControlledModel([SUMMARY])
    bounded = RecoverySummaryModel(
        model,
        ContextRecoveryBudget(),
        lambda: False,
        estimate=lambda messages: 100,
        input_limit=100,
    )
    assert (
        compressor.compress(None, [turn], bounded, allow_fact_correction=True).candidate
        is None
    )
    assert not model.calls


def test_sc007_cancelled_fact_correction_retains_candidate_none():
    from nexent.core.concurrency.cancellation import RunTerminated

    compressor, turn = compressor_and_turn()
    model = ControlledModel([SUMMARY])
    bounded = RecoverySummaryModel(model, ContextRecoveryBudget(), lambda: True)
    with pytest.raises(RunTerminated):
        compressor.compress(None, [turn], bounded, allow_fact_correction=True)
    assert not model.calls


def test_sc007_optional_ledger_hint_does_not_reject_a_fitting_source():
    import json
    import math

    compressor, turn = compressor_and_turn()
    answer = SUMMARY + "\ncritical-task-001 = Code-123."
    first = ControlledModel([answer])
    assert compressor.compress(None, [turn], first).candidate is not None
    hinted = first.calls[0]
    hint_marker = "\n\nExact protected identifier ledger:"
    unhinted = [
        {"role": message.role, "content": message.content} for message in hinted
    ]
    unhinted[1]["content"] = [dict(hinted[1].content[0])]
    text = unhinted[1]["content"][0]["text"]
    assert hint_marker in text
    unhinted[1]["content"][0]["text"] = text.split(hint_marker)[0]
    config = compressor._llm.config
    config.effective_input_limit_tokens = (
        math.floor(
            len(json.dumps(unhinted, ensure_ascii=False)) / config.chars_per_token
        )
        + 1
    )
    second = ControlledModel([answer])
    assert compressor.compress(None, [turn], second).candidate is not None
    assert [
        {"role": message.role, "content": message.content}
        for message in second.calls[0]
    ] == unhinted
