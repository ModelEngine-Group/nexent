# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Only a missing constant title is normalizable; all source obligations remain strict."""

import pytest

from nexent.core.agents.context import ContextManagerConfig
from nexent.core.agents.context.history_compression import _validate_summary_contract
from nexent.core.agents.context.recovery import (
    ContextRecoveryBudget,
    RecoverySummaryModel,
)
from test_history_capacity_recovery import SUMMARY
from test_history_fact_correction import ControlledModel, compressor_and_turn

TOP = "# Compact Result of History"
BODY = SUMMARY.split("\n\n", 1)[1]
KEYS = tuple(ContextManagerConfig().summary_json_schema)
FACT = "critical-task-001 = Code-123."


@pytest.mark.parametrize("ending", ["", "\n\n"])
def test_only_missing_fixed_title_preserves_all_body_bytes(ending):
    body = BODY + "\n" + FACT + ending
    assert (
        _validate_summary_contract(body, KEYS, source_text=FACT) == TOP + "\n\n" + body
    )


def test_existing_complete_contract_keeps_existing_canonical_behavior():
    assert _validate_summary_contract(SUMMARY, KEYS) == SUMMARY.strip()


@pytest.mark.parametrize(
    "body",
    [
        BODY.replace("## Task Overview", "### Task Overview", 1),
        BODY.replace("## Task Overview", "## Temporary", 1)
        .replace("## Completed Work", "## Task Overview", 1)
        .replace("## Temporary", "## Completed Work", 1),
        BODY.replace("## Key Decisions", "", 1),
        BODY + "\n## Completed Work\nDuplicate body.",
        BODY + "\n## Unknown\nUnknown body.",
        BODY + "\n### Nested\nNested body.",
        BODY.replace("Continue the prior task.", "", 1),
        "Here is a summary:\n" + BODY,
        "# Incorrect title\n" + BODY,
        BODY + "\nWord count: 42",
    ],
)
def test_title_normalization_cannot_repair_other_contract_errors(body):
    assert _validate_summary_contract(body, KEYS) is None


def test_missing_title_never_excuses_a_missing_protected_fact():
    assert _validate_summary_contract(BODY, KEYS, source_text=FACT) is None


def test_missing_title_uses_original_response_usage_without_a_correction_call():
    compressor, turn = compressor_and_turn()
    body = BODY + "\n" + FACT
    model = ControlledModel([body])
    budget = ContextRecoveryBudget()
    result = compressor.compress(
        None,
        [turn],
        RecoverySummaryModel(model, budget, lambda: False),
        allow_fact_correction=True,
    )
    assert result.candidate.summary["markdown"] == TOP + "\n\n" + body
    assert len(model.calls) == len(result.records) == budget.summary_calls == 1
    assert (
        result.records[0].input_tokens == 100 and result.records[0].output_tokens == 10
    )
    assert not budget.fact_correction_used


@pytest.mark.parametrize("missing_fact", [False, True])
def test_format_and_fact_correction_share_the_existing_one_claim(missing_fact):
    compressor, turn = compressor_and_turn()
    bad = SUMMARY.replace("## Key Decisions", "", 1) + (
        "" if missing_fact else "\n" + FACT
    )
    model = ControlledModel([bad, SUMMARY + "\n" + FACT])
    budget = ContextRecoveryBudget()
    bounded = RecoverySummaryModel(model, budget, lambda: False)
    result = compressor.compress(None, [turn], bounded, allow_fact_correction=True)
    assert result.candidate is not None
    assert len(model.calls) == len(result.records) == budget.summary_calls == 2
    assert budget.fact_correction_used and not bounded.claim_fact_correction()
    feedback = str(model.calls[1])
    assert "Task Overview" in feedback and "Context To Preserve" in feedback
    assert "critical-task-001" in feedback and "Code-123" in feedback


def test_format_repair_followed_by_missing_fact_cannot_claim_an_extra_rewrite():
    compressor, turn = compressor_and_turn()
    bad = SUMMARY.replace("## Key Decisions", "", 1)
    model = ControlledModel([bad, SUMMARY, SUMMARY])
    budget = ContextRecoveryBudget()
    bounded = RecoverySummaryModel(model, budget, lambda: False)
    assert (
        compressor.compress(None, [turn], bounded, allow_fact_correction=True).candidate
        is None
    )
    assert len(model.calls) == 2 and budget.fact_correction_used
    assert (
        compressor.compress(None, [turn], bounded, allow_fact_correction=True).candidate
        is None
    )
    assert len(model.calls) == budget.summary_calls == 3
    assert (
        compressor.compress(None, [turn], bounded, allow_fact_correction=True).candidate
        is None
    )
    assert len(model.calls) == 3


def test_invalid_contract_without_recovery_correction_authorization_stays_rejected():
    compressor, turn = compressor_and_turn()
    model = ControlledModel(["Invalid response."])
    assert compressor.compress(None, [turn], model).candidate is None
    assert len(model.calls) == 1


def test_contract_correction_still_cannot_dispatch_an_input_at_the_window_limit():
    compressor, turn = compressor_and_turn()
    model = ControlledModel(["Invalid response."])
    budget = ContextRecoveryBudget()
    bounded = RecoverySummaryModel(
        model,
        budget,
        lambda: False,
        estimate=lambda messages: 100 if not model.calls else 101,
        input_limit=101,
    )
    assert (
        compressor.compress(None, [turn], bounded, allow_fact_correction=True).candidate
        is None
    )
    assert budget.fact_correction_used and len(model.calls) == budget.summary_calls == 1


def test_failed_contract_correction_rolls_back_and_prepare_reentry_cannot_rewrite():
    from copy import deepcopy
    from types import SimpleNamespace

    from nexent.core.agents.context import ContextItemInput, ContextManager
    from nexent.core.agents.cores.smolagents.context import ManagedContextRuntime
    from smolagents.memory import TaskStep

    manager = ContextManager(
        ContextManagerConfig(
            context_window_tokens=20000,
            effective_input_limit_tokens=20000,
            chars_per_token=1,
            policy_layers={"platform": {"processing_mode": "adaptive_compact"}},
        )
    )
    runtime = ManagedContextRuntime(
        manager,
        [
            ContextItemInput(
                id="old",
                type="conversation_turn",
                content={
                    "user_message": "h" * 14000,
                    "assistant_final_answer": "Old fact.",
                    "user_message_id": 1,
                    "assistant_message_id": 2,
                },
            )
        ],
    )
    memory = SimpleNamespace(steps=[TaskStep(task="current " + "n" * 8000)])
    runtime.prepare_run(memory=memory, fallback_system_prompt="System")
    before = [deepcopy(item.content) for item in runtime.items]
    model = ControlledModel(["Invalid format.", "Still invalid format."])
    with pytest.raises(ValueError, match="combined context window"):
        runtime.prepare_step(model=model, memory=memory, current_run_start_idx=0)
    assert len(model.calls) == 2 and runtime._capacity_budget.fact_correction_used
    assert manager._history_candidate is None
    assert manager._pending_capacity_candidate is None
    assert [item.content for item in runtime.items] == before
    with pytest.raises(ValueError):
        runtime.prepare_step(model=model, memory=memory, current_run_start_idx=0)
    assert len(model.calls) == 2
