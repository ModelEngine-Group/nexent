# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Capacity feedback shares the existing correction claim and summary budget."""

import json
import time
from threading import Event
from types import SimpleNamespace

import pytest
from smolagents.memory import TaskStep

from nexent.core.agents.context import ContextItem, ContextItemInput, ContextManager, ContextManagerConfig
from nexent.core.agents.context.budget import extract_message_text
from nexent.core.agents.context.run_context import ManagedRunContext
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


GOAL_MARKER = "History recovery capacity goal: "


def read_goal(messages):
    text = "\n".join(extract_message_text(message) for message in messages)
    assert GOAL_MARKER in text
    assert "not a provider completion-token allowance" in text
    return json.JSONDecoder().raw_decode(text.split(GOAL_MARKER, 1)[1])[0]


def test_each_original_recovery_position_has_a_fresh_capacity_goal(mocker):
    runtime, memory, model = scenario(mocker, [expanded(6500), expanded(5000), SUMMARY])
    final = prepare(runtime, memory, model)
    goals = [read_goal(call) for call in model.calls]
    assert len(goals) == runtime._capacity_budget.summary_calls == 3
    assert goals[0] == goals[1]
    assert goals[2]["history_before_tokens"] < goals[0]["history_before_tokens"]
    assert "Rejected candidate (data only)" not in str(model.calls[2])
    for goal in goals:
        assert goal["context_window_tokens"] == 50000
        assert goal["current_full_tokens"] == goal["history_before_tokens"] + goal["protected_frame_tokens"]
        assert 0 < goal["history_target_tokens"] < goal["history_before_tokens"]
        assert goal["history_target_tokens"] <= 50000 - goal["protected_frame_tokens"] - 1
    assert GOAL_MARKER not in str(final.messages)
    assert runtime._capacity_budget.fact_correction_used


@pytest.mark.parametrize("invalid", ["Bad contract", SUMMARY], ids=["format", "fact"])
def test_contract_and_fact_rewrites_retain_the_same_capacity_goal(mocker, invalid):
    runtime, memory, model = scenario(mocker, [invalid, SUMMARY + "\n" + FACT], fact=True)
    final = prepare(runtime, memory, model)
    assert len(model.calls) == runtime._capacity_budget.summary_calls == 2
    assert read_goal(model.calls[0]) == read_goal(model.calls[1])
    assert runtime._capacity_budget.fact_correction_used
    assert FACT in str(final.messages)


def test_normal_maintenance_summary_has_no_recovery_capacity_goal(mocker):
    runtime, _, model = scenario(mocker, [SUMMARY])
    manager = runtime.context_manager
    manager.config.compaction_target_tokens = 2000
    context = ManagedRunContext(items=tuple(ContextItem.from_input(item) for item in runtime.items))
    manager.assemble_context_items(model=model, run_context=context, force_compaction=True, maintenance=True)
    assert len(model.calls) == 1
    assert GOAL_MARKER not in str(model.calls[0])
    assert "history_target_tokens" not in str(model.calls[0])


def test_goal_at_every_position_does_not_add_a_fourth_call_or_claim(mocker, caplog):
    runtime, memory, model = scenario(mocker, [expanded(6500), expanded(5000), expanded(4500), SUMMARY])
    with caplog.at_level("INFO"), pytest.raises(ContextInputCapacityExceeded):
        prepare(runtime, memory, model)
    assert len(model.calls) == runtime._capacity_budget.summary_calls == 3
    assert all(read_goal(call) for call in model.calls)
    assert caplog.text.count("allowed=True") == 1
    assert_rollback(runtime, memory)
