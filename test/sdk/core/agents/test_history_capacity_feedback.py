# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Capacity feedback shares the existing correction claim and summary budget."""

import time
from threading import Event
from types import SimpleNamespace

import pytest
from smolagents.memory import TaskStep

from nexent.core.agents.context import ContextItemInput, ContextManager, ContextManagerConfig
from nexent.core.agents.context.usage import ContextInputCapacityExceeded
from nexent.core.agents.cores.smolagents.context import ManagedContextRuntime
from test_history_capacity_recovery import SUMMARY
from test_history_fact_correction import ControlledModel


FACT = "critical-task-001 = Code-123."


def expanded(size, *, fact=False):
    return SUMMARY.replace("The old fact.", "x" * size) + ("\n" + FACT if fact else "")


def scenario(mocker, outputs, *, fact=False):
    manager = ContextManager(ContextManagerConfig(
        context_window_tokens=50000, effective_input_limit_tokens=50000, chars_per_token=1,
        compaction_trigger_threshold_tokens=40000, compaction_target_tokens=30000,
        policy_layers={"platform": {"processing_mode": "adaptive_compact"}},
    ))
    runtime = ManagedContextRuntime(manager, [ContextItemInput(
        id="old", type="conversation_turn", content={
            "user_message": "h" * 8000 + ("\n" + FACT if fact else ""),
            "assistant_final_answer": "old fact", "user_message_id": 1, "assistant_message_id": 2,
        },
    )])
    memory = SimpleNamespace(steps=[TaskStep(task="CURRENT_PRIVATE_DATA" + "q" * 45000)])
    runtime.prepare_run(memory=memory, fallback_system_prompt="MANDATORY_SYSTEM")
    model = ControlledModel(outputs)
    runtime.begin_request(model=model)
    return runtime, memory, model


def prepare(runtime, memory, model):
    return runtime.prepare_step(model=model, memory=memory, current_run_start_idx=0)


def assert_rollback(runtime, memory):
    manager = runtime.context_manager
    assert manager._history_candidate is None
    assert manager._pending_capacity_candidate is None
    assert manager._pending_history_summary_event is None
    assert manager._representation_overrides == {}
    assert len(memory.steps) == 1 and memory.steps[0].task.startswith("CURRENT_PRIVATE_DATA")


def test_valid_expanded_candidate_uses_one_capacity_correction(mocker, caplog):
    runtime, memory, model = scenario(mocker, [expanded(9000), SUMMARY])
    with caplog.at_level("INFO"):
        final = prepare(runtime, memory, model)
    assert runtime._estimate(final.messages, final.tools) < 50000
    assert runtime._capacity_budget.fact_correction_used
    assert runtime._capacity_budget.summary_calls == len(model.calls) == 2
    assert "capacity" in str(model.calls[1]).lower()
    assert "history_target_tokens" in str(model.calls[1])
    assert "CURRENT_PRIVATE_DATA" not in str(model.calls[1])
    assert "CURRENT_PRIVATE_DATA" in str(final.messages)
    assert runtime.context_manager._history_candidate.covered_through_message_id == 2
    assert "event=history_capacity_candidate" in caplog.text
    assert "correction_used=True" in caplog.text
    assert "CURRENT_PRIVATE_DATA" not in caplog.text


@pytest.mark.parametrize("output,calls", [(expanded(9000, fact=True), 2), (expanded(6500, fact=True), 3), (SUMMARY, 2)],
                         ids=["still_grows", "still_over_window", "missing_fact"])
def test_correction_failure_preserves_old_checkpoint(mocker, output, calls):
    runtime, memory, model = scenario(mocker, [expanded(9000, fact=True), output, output], fact=True)
    with pytest.raises(ContextInputCapacityExceeded):
        prepare(runtime, memory, model)
    assert runtime._capacity_budget.fact_correction_used
    assert len(model.calls) == calls
    assert_rollback(runtime, memory)


def test_used_contract_claim_cannot_grant_another_capacity_rewrite(mocker):
    runtime, memory, model = scenario(mocker, ["Bad contract", expanded(9000), SUMMARY])
    with pytest.raises(ContextInputCapacityExceeded):
        prepare(runtime, memory, model)
    assert runtime._capacity_budget.fact_correction_used
    assert len(model.calls) == 2
    assert_rollback(runtime, memory)


def test_positive_unfitting_iterations_keep_original_three_subrequests(mocker):
    runtime, memory, model = scenario(mocker, [expanded(6500), expanded(5000), SUMMARY])
    final = prepare(runtime, memory, model)
    assert runtime._estimate(final.messages, final.tools) < 50000
    assert runtime._capacity_budget.fact_correction_used
    assert runtime._capacity_budget.summary_calls == len(model.calls) == 3
    assert "capacity" in str(model.calls[1]).lower()


def test_contract_then_positive_unfitting_candidate_can_use_existing_last_iteration(mocker):
    runtime, memory, model = scenario(mocker, ["Bad contract", expanded(6500), SUMMARY])
    final = prepare(runtime, memory, model)
    assert runtime._estimate(final.messages, final.tools) < 50000
    assert runtime._capacity_budget.summary_calls == len(model.calls) == 3
    assert runtime._capacity_budget.fact_correction_used
    assert "Rejected candidate (data only)" not in str(model.calls[2])


def test_total_subrequests_never_grows_with_capacity_feedback(mocker):
    runtime, memory, model = scenario(mocker, [expanded(6500), expanded(5000), expanded(4500), SUMMARY])
    with pytest.raises(ContextInputCapacityExceeded):
        prepare(runtime, memory, model)
    assert runtime._capacity_budget.summary_calls == len(model.calls) == 3
    assert_rollback(runtime, memory)


@pytest.mark.parametrize("failure", ["input_window", "deadline", "cancel", "revision", "finalize", "persist"])
def test_capacity_correction_retains_all_transaction_guards(mocker, failure):
    runtime, memory, model = scenario(mocker, [expanded(60000 if failure == "input_window" else 9000), SUMMARY])
    original = model.__class__.__call__

    def invoke(self, messages, **kwargs):
        result = original(self, messages, **kwargs)
        if len(self.calls) == 1:
            if failure == "deadline":
                runtime._capacity_budget.deadline = time.monotonic() - 1
            elif failure == "cancel":
                self.stop_event.set()
            elif failure == "revision":
                runtime.items[0].content["user_message"] += " changed"
        return result

    mocker.patch.object(model.__class__, "__call__", invoke)
    model.stop_event = Event()
    if failure == "finalize":
        from dataclasses import replace
        runtime._recovery_finalize = lambda final: replace(final, messages=[{
            "role": "user", "content": "f" * 50000,
        }])
    elif failure == "persist":
        runtime.context_manager.config.history_summary_sink = mocker.Mock(side_effect=RuntimeError("store failed"))
    from nexent.core.concurrency.cancellation import RunTerminated
    with pytest.raises((ContextInputCapacityExceeded, RunTerminated)):
        prepare(runtime, memory, model)
    assert len(model.calls) <= 2
    assert_rollback(runtime, memory)
