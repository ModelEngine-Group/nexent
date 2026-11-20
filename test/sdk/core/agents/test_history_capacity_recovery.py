# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Approved local capacity recovery boundaries; the model boundary is controlled."""

from types import SimpleNamespace

import pytest
from nexent.core.agents.context import (
    ContextItemInput,
    ContextManager,
    ContextManagerConfig,
)
from nexent.core.agents.cores.smolagents.context import ManagedContextRuntime
from smolagents.memory import TaskStep

SUMMARY = """# Compact Result of History

## Task Overview

Continue the prior task.

## Completed Work

The old fact was recorded.

## Key Decisions

Keep the old fact.

## Unresolved Issues

None recorded.

## Pending Items

Continue the new request.

## Next Steps

Use the recorded fact.

## Context To Preserve

The old fact.
"""


def configured(mocker, *, history_chars=24000, query="new request", window=20000):
    config = ContextManagerConfig(
        context_window_tokens=window,
        effective_input_limit_tokens=window,
        chars_per_token=1,
        compaction_trigger_threshold_tokens=int(window * 0.8),
        compaction_target_tokens=int(window * 0.6),
        policy_layers={"platform": {"processing_mode": "adaptive_compact"}},
    )
    manager = ContextManager(config, message_format="codeagent")
    generated = mocker.patch.object(
        manager._history_compressor._llm,
        "generate_summary",
        return_value=SimpleNamespace(summary_text=SUMMARY, records=[]),
    )
    items = [
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
    ]
    runtime = ManagedContextRuntime(manager, items)
    memory = SimpleNamespace(steps=[TaskStep(task=query)])
    runtime.prepare_run(memory=memory, fallback_system_prompt="system instruction")
    return runtime, memory, SimpleNamespace(model_id="controlled"), generated


def test_b003_cold_rejection_recovers_only_old_history(mocker):
    runtime, memory, model, generated = configured(mocker)
    result = runtime.prepare_step(model=model, memory=memory, current_run_start_idx=0)
    assert (
        runtime._estimate(result.messages, result.tools) < runtime.context_window_tokens
    )
    assert "new request" in str(result.messages) and "system instruction" in str(
        result.messages
    )
    assert "old fact" in str(result.messages)
    assert generated.called
    assert runtime.context_manager._history_candidate.covered_through_message_id == 2
    assert len(memory.steps) == 1 and memory.steps[0].task == "new request"


def test_b001_normal_prepare_stays_pure_even_above_soft_threshold(mocker):
    runtime, memory, model, generated = configured(mocker, history_chars=17000)
    result = runtime.prepare_step(model=model, memory=memory, current_run_start_idx=0)
    assert (
        runtime.token_threshold
        < runtime._estimate(result.messages, result.tools)
        < runtime.context_window_tokens
    )
    generated.assert_not_called()
    assert runtime.context_manager._history_candidate is None


def test_b002_oversized_new_query_rejects_without_auxiliary_dispatch(mocker):
    runtime, memory, model, generated = configured(mocker, query="x" * 21000)
    with pytest.raises(ValueError, match="combined context window"):
        runtime.prepare_step(model=model, memory=memory, current_run_start_idx=0)
    generated.assert_not_called()
    assert runtime.context_manager._history_candidate is None


@pytest.mark.parametrize("format", ["codeagent", "openai_chat_completions"])
def test_b006_recovery_measures_rendered_frame_and_keeps_resources(mocker, format):
    runtime, memory, model, generated = configured(mocker)
    runtime.context_manager._message_format = format
    resource = ContextItemInput(
        id="required-resource",
        type="knowledge_base",
        content={"text": "resource " * 100},
    )
    runtime.items.append(resource)
    runtime._run_context = None
    recovered = runtime.prepare_step(
        model=model, memory=memory, current_run_start_idx=0
    )
    assert "resource " * 100 in str(recovered.messages)
    assert recovered.evidence.maintenance_phase == "local_capacity_recovery"
    assert recovered.evidence.provider_input_tokens is None
    assert recovered.evidence.non_history_tokens < runtime.context_window_tokens
    assert generated.called


@pytest.mark.parametrize(
    "failure", ["invalid", "no_gain", "exception", "stale", "cancel", "persist"]
)
def test_b008_failed_candidate_never_changes_committed_history(mocker, failure):
    from threading import Event
    from nexent.core.concurrency.cancellation import RunTerminated

    runtime, memory, model, generated = configured(mocker)
    model.stop_event = Event()
    manager = runtime.context_manager
    if failure == "invalid":
        generated.return_value = SimpleNamespace(
            summary_text="not a structured summary", records=[]
        )
    elif failure == "no_gain":
        generated.return_value = SimpleNamespace(
            summary_text=SUMMARY.replace("The old fact.", "x" * 25000), records=[]
        )
    elif failure == "exception":
        generated.side_effect = RuntimeError("summary unavailable")
    elif failure == "stale":

        def change_source(*args, **kwargs):
            runtime.items.append(
                ContextItemInput(
                    id="new-source", type="system", content={"text": "changed"}
                )
            )
            return SimpleNamespace(summary_text=SUMMARY, records=[])

        generated.side_effect = change_source
    elif failure == "cancel":

        def cancel(*args, **kwargs):
            model.stop_event.set()
            return SimpleNamespace(summary_text=SUMMARY, records=[])

        generated.side_effect = cancel
    elif failure == "persist":
        manager.config.history_summary_sink = mocker.Mock(
            side_effect=RuntimeError("store unavailable")
        )
    with pytest.raises((ValueError, RuntimeError, RunTerminated)):
        runtime.prepare_step(model=model, memory=memory, current_run_start_idx=0)
    assert manager._history_candidate is None
    assert manager._pending_history_summary_event is None
    assert manager._pending_capacity_candidate is None
    assert manager._representation_overrides == {}
    assert len(memory.steps) == 1


def test_b004_provider_overflow_cannot_reset_local_recovery_budget(mocker):
    runtime, memory, model, generated = configured(mocker)
    result = runtime.prepare_step(model=model, memory=memory, current_run_start_idx=0)
    count = generated.call_count
    with pytest.raises(ValueError):
        runtime.recover_step(model=model, memory=memory, current_run_start_idx=0)
    assert generated.call_count == count
    assert runtime.context_manager._history_candidate is not None
    assert "old fact" in str(result.messages)


def test_b009_committed_old_summary_survives_later_main_failure(mocker):
    sink = mocker.Mock()
    runtime, memory, model, generated = configured(mocker)
    runtime.context_manager.config.history_summary_sink = sink
    runtime.prepare_step(model=model, memory=memory, current_run_start_idx=0)
    candidate = runtime.context_manager._history_candidate
    sink.assert_called_once_with(candidate)
    # The main request has not completed; no new response usage/output is accepted.
    assert runtime.usage_baseline.actual_input_tokens is None
    assert candidate.covered_through_message_id == 2
    assert (
        runtime.context_manager.consume_history_summary_event()["status"] == "accepted"
    )
    assert runtime.context_manager._history_candidate is candidate


def test_b002_exact_protected_boundary_rejects_without_summary(mocker):
    runtime, memory, model, generated = configured(mocker, query="x" * 20000)
    protected = ContextManager(runtime.context_manager.config).prepare_items_context(
        "system instruction"
    )
    manager = runtime.context_manager
    frame = manager.assemble_context_items(
        model=model,
        current_items=runtime._memory_adapter._project_current_run(memory, 0),
        run_context=protected,
    )
    manager.config.effective_input_limit_tokens = runtime._estimate(
        frame.messages, frame.tools
    )
    with pytest.raises(ValueError):
        runtime.prepare_step(model=model, memory=memory, current_run_start_idx=0)
    generated.assert_not_called()


def test_b007_summary_wrapper_enforces_total_calls_and_deadline():
    import time
    from nexent.core.agents.context.recovery import (
        ContextRecoveryBudget,
        RecoverySummaryModel,
    )

    calls = []

    class Model:
        def __call__(self, messages, stop_sequences=None):
            calls.append(messages)
            return SimpleNamespace(content="ok")

    budget = ContextRecoveryBudget()
    model = RecoverySummaryModel(Model(), budget, lambda: False)
    for _ in range(3):
        model([])
    with pytest.raises(ValueError, match="summary budget"):
        model([])
    assert len(calls) == 3
    expired = RecoverySummaryModel(
        Model(), ContextRecoveryBudget(deadline=time.monotonic() - 1), lambda: False
    )
    with pytest.raises(ValueError, match="deadline"):
        expired([])
    assert len(calls) == 3


def test_b004_failed_summary_and_prepare_reentry_share_one_transaction(mocker):
    runtime, memory, model, generated = configured(mocker)
    generated.side_effect = RuntimeError("controlled summary failure")
    with pytest.raises(RuntimeError, match="controlled summary failure"):
        runtime.prepare_step(model=model, memory=memory, current_run_start_idx=0)
    calls = generated.call_count
    budget = runtime._capacity_budget
    assert budget.used
    with pytest.raises(ValueError):
        runtime.prepare_step(model=model, memory=memory, current_run_start_idx=0)
    with pytest.raises(ValueError):
        runtime.recover_step(model=model, memory=memory, current_run_start_idx=0)
    assert generated.call_count == calls
    assert runtime._capacity_budget is budget
    runtime.begin_request(model=model)
    assert runtime._capacity_budget is not budget and not runtime._capacity_budget.used
    generated.side_effect = None
    result = runtime.prepare_step(model=model, memory=memory, current_run_start_idx=0)
    assert result.evidence.maintenance_phase == "local_capacity_recovery"


def test_b008_raw_memory_mutation_cannot_hide_in_projection_cache(mocker):
    runtime, memory, model, generated = configured(mocker)

    def change_memory(*args, **kwargs):
        memory.steps[0].task = "changed during summary"
        return SimpleNamespace(summary_text=SUMMARY, records=[])

    generated.side_effect = change_memory
    with pytest.raises(ValueError):
        runtime.prepare_step(model=model, memory=memory, current_run_start_idx=0)
    assert runtime.context_manager._history_candidate is None
    assert runtime.context_manager._pending_history_summary_event is None


def test_b007_recovery_passes_same_deadline_without_mutating_main_model():
    from nexent.core.agents.context.recovery import (
        ContextRecoveryBudget,
        RecoverySummaryModel,
    )
    from nexent.core.agents.cores.smolagents.context import adapt_context_model
    import time

    calls = []

    class Service:
        def invoke(self, *args, **kwargs):
            calls.append(kwargs["deadline"])
            return SimpleNamespace(content="summary")

    class Model:
        def __init__(self):
            self.service = Service()
            self.counter = 0

        def __call__(self, messages, **kwargs):
            self.counter += 1
            return self.service.invoke(messages, **kwargs)

    original = Model()
    deadline = time.monotonic() + 20
    wrapper = RecoverySummaryModel(
        adapt_context_model(original),
        ContextRecoveryBudget(deadline=deadline),
        lambda: False,
    )
    assert wrapper([]).content == "summary"
    assert calls == [deadline]
    assert original.counter == 0 and isinstance(original.service, Service)


def test_b008_actual_final_guard_frame_must_fit_before_checkpoint_commit(mocker):
    from dataclasses import replace
    from nexent.core.agents.contracts.context import ContextMessage

    runtime, memory, model, generated = configured(mocker)
    sink = mocker.Mock()
    runtime.context_manager.config.history_summary_sink = sink

    def oversized_final_guard(context):
        return replace(
            context,
            messages=[
                *context.messages,
                ContextMessage(
                    role="user", content=[{"type": "text", "text": "overlay" * 4000}]
                ),
            ],
        )

    runtime.begin_request(model=model, recovery_finalize=oversized_final_guard)
    with pytest.raises(ValueError):
        runtime.prepare_step(model=model, memory=memory, current_run_start_idx=0)
    assert generated.called and runtime._capacity_budget.used
    sink.assert_not_called()
    assert runtime.context_manager._history_candidate is None
    assert runtime.context_manager._pending_history_summary_event is None


def test_b005_summary_overflow_never_retries_with_truncated_old_facts(mocker):
    from nexent.core.agents.context.recovery import (
        ContextRecoveryBudget,
        RecoverySummaryModel,
    )

    runtime, memory, model, generated = configured(mocker)
    # Exercise the real summary error path with only the transport seam controlled.
    from nexent.core.agents.context.llm_summary import LLMSummary

    llm = LLMSummary(runtime.context_manager.config, runtime.context_manager._renderer)
    call = mocker.patch.object(
        llm,
        "_do_generate_summary",
        side_effect=ValueError("maximum context length exceeded"),
    )
    truncate = mocker.patch.object(llm._renderer, "truncate_text_to_tokens")
    wrapped = RecoverySummaryModel(model, ContextRecoveryBudget(), lambda: False)
    result = llm.generate_summary("all old facts must remain available", wrapped)
    assert result.summary_text is None
    call.assert_called_once()
    truncate.assert_not_called()


def test_b008_accepted_guard_frame_has_actual_evidence_and_one_checkpoint(mocker):
    from dataclasses import replace
    from nexent.core.agents.contracts.context import ContextMessage

    runtime, memory, model, generated = configured(mocker)

    def final_guard(context):
        return replace(
            context,
            messages=[
                *context.messages,
                ContextMessage(
                    role="user",
                    content=[{"type": "text", "text": "guarded final overlay"}],
                ),
            ],
        )

    runtime.begin_request(model=model, recovery_finalize=final_guard)
    result = runtime.prepare_step(model=model, memory=memory, current_run_start_idx=0)
    assert result.evidence.maintenance_phase == "local_capacity_recovery"
    assert result.evidence.final_token_estimate == runtime._estimate(
        result.messages, result.tools
    )
    assert (
        result.evidence.calibrated_input_estimate
        == result.evidence.final_token_estimate
    )
    assert result.evidence.messages_fingerprint == runtime.context_manager._fingerprint(
        result.messages
    )
    assert result.evidence.message_roles[-1] == "user"
    assert "guarded final overlay" in str(result.messages)


def test_b004_explicit_provider_overflow_may_recover_when_local_estimate_fit(mocker):
    runtime, memory, model, generated = configured(mocker, history_chars=8000)
    first = runtime.prepare_step(model=model, memory=memory, current_run_start_idx=0)
    generated.assert_not_called()
    assert first.evidence.final_token_estimate < runtime.token_threshold
    recovered = runtime.recover_step(
        model=model, memory=memory, current_run_start_idx=0
    )
    assert generated.called and runtime._capacity_budget.used
    assert recovered.evidence.maintenance_phase == "provider_overflow_recovery"
    assert recovered.evidence.final_token_estimate < first.evidence.final_token_estimate
    count = generated.call_count
    with pytest.raises(ValueError):
        runtime.recover_step(model=model, memory=memory, current_run_start_idx=0)
    assert generated.call_count == count
