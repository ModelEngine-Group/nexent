# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Main inference survives auxiliary maintenance failures and exhausted estimates."""

import pytest
from nexent.core.agents.context import (
    ContextItemInput,
    ContextManager,
    ContextManagerConfig,
)
from nexent.core.concurrency.cancellation import RunTerminated
from smolagents.memory import TaskStep
from test_history_context_runtime import (
    _Memory,
    _rendered_text,
    _summary_and_turns,
    _SummaryModel,
    _SystemPrompt,
)


def test_later_request_still_compacts_after_prior_attempt_budget_is_used(monkeypatch):
    monkeypatch.setattr("smolagents.memory.SystemPromptStep", _SystemPrompt)
    manager = ContextManager(ContextManagerConfig(
        soft_input_budget_tokens=20,
        policy_layers={"request": {"processing_mode": "adaptive_compact"}},
    ))
    memory = _Memory([TaskStep(task="current")])
    run = manager.prepare_run_context(memory, "", _summary_and_turns())
    manager._run_compaction_attempts = 3
    model = _SummaryModel()
    result = manager.assemble_final_context(
        model=model, memory=memory, current_run_start_idx=0, run_context=run,
    )
    assert model.calls
    assert 1 <= result.evidence.compaction_attempts <= 3


def test_auxiliary_failure_does_not_reject_main_context(monkeypatch):
    monkeypatch.setattr("smolagents.memory.SystemPromptStep", _SystemPrompt)
    manager = ContextManager(ContextManagerConfig(
        soft_input_budget_tokens=20,
        policy_layers={"request": {"processing_mode": "adaptive_compact"}},
    ))
    memory = _Memory([TaskStep(task="current protected task")])
    run = manager.prepare_run_context(memory, "", _summary_and_turns())
    def failed_compression(*args):
        raise RuntimeError("auxiliary service unavailable")
    monkeypatch.setattr(manager._history_compressor, "compress", failed_compression)
    result = manager.assemble_final_context(
        model=_SummaryModel(), memory=memory, current_run_start_idx=0, run_context=run,
    )
    rendered = _rendered_text(result.messages)
    assert "new question " * 100 in rendered
    assert "current protected task" in rendered
    assert result.evidence.compaction_stop_reason == "maintenance_failed"
    assert result.evidence.new_summary_coverage is None



def test_cooperative_cancellation_is_not_swallowed_by_maintenance(monkeypatch):
    monkeypatch.setattr("smolagents.memory.SystemPromptStep", _SystemPrompt)
    manager = ContextManager(ContextManagerConfig(
        soft_input_budget_tokens=20,
        policy_layers={"request": {"processing_mode": "adaptive_compact"}},
    ))
    memory = _Memory([TaskStep(task="current")])
    run = manager.prepare_run_context(memory, "", _summary_and_turns())
    def cancelled(*args):
        raise RunTerminated()
    monkeypatch.setattr(manager._history_compressor, "compress", cancelled)
    with pytest.raises(RunTerminated):
        manager.assemble_final_context(
            model=_SummaryModel(), memory=memory, current_run_start_idx=0, run_context=run,
        )


def test_truncated_summary_is_rejected_without_input_compression_retry():
    from nexent.core.agents.context.llm_summary import LLMSummary
    from nexent.core.agents.context.step_renderer import StepRenderer
    config = ContextManagerConfig()
    model = _SummaryModel()
    model.last_finish_reason = 'length'
    result = LLMSummary(config, StepRenderer(config)).generate_summary('original facts', model)
    assert result.summary_text is None
    assert len(model.calls) == 1
    assert len(result.records) == 1


def test_step_metrics_compare_the_same_context_estimate_basis(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from nexent.core.agents.core_agent import CoreAgent
    agent = CoreAgent.__new__(CoreAgent)
    agent.step_metrics = []
    agent._last_uncompressed_est = 400
    agent.context_runtime = SimpleNamespace(
        compression_stats=lambda: {'calls': 0}, token_counts=lambda: {'uncompressed': 400, 'compressed': 400},
        chars_per_token=1.5, token_threshold=1000,
    )
    monkeypatch.setattr('nexent.core.agents.core_agent.get_monitoring_manager', lambda: Mock())
    step = SimpleNamespace(step_number=1, token_usage=None,
                           model_input_messages=[{'role': 'user', 'content': 'small'}],
                           model_output_message={'role': 'assistant', 'content': 'answer'})
    agent._collect_step_metrics(step)
    assert agent.step_metrics[0]['memory_state']['estimated_input_tokens'] == 400
    assert agent.step_metrics[0]['compression_ratio'] == 0.0


def test_explicit_overflow_can_compact_history_below_the_estimated_threshold(monkeypatch):
    monkeypatch.setattr('smolagents.memory.SystemPromptStep', _SystemPrompt)
    saved = []
    manager = ContextManager(ContextManagerConfig(
        effective_input_limit_tokens=1_000_000, history_summary_sink=saved.append,
        policy_layers={'request': {'processing_mode': 'adaptive_compact'}},
    ))
    memory = _Memory([TaskStep(task='protected current task')])
    run = manager.prepare_run_context(memory, '', _summary_and_turns())
    model = _SummaryModel()
    result = manager.assemble_final_context(
        model=model, memory=memory, current_run_start_idx=0, run_context=run, force_compaction=True,
    )
    assert len(model.calls) == 1 and len(saved) == 1
    assert result.evidence.history_compression_triggered
    assert 'protected current task' in _rendered_text(result.messages)
    assert result.evidence.new_summary_coverage == 22


def test_accepted_checkpoint_is_not_repeatedly_summarized_without_new_turns(monkeypatch):
    monkeypatch.setattr('smolagents.memory.SystemPromptStep', _SystemPrompt)
    manager = ContextManager(ContextManagerConfig(
        effective_input_limit_tokens=1000,
        policy_layers={'request': {'processing_mode': 'adaptive_compact'}},
    ))
    memory = _Memory([TaskStep(task='current')])
    summary = ContextItemInput(id='summary:10', type='history_summary', content={
        'unit_id': 10, 'summary': 'accepted checkpoint ' * 1000, 'covered_through_message_id': 20,
    })
    run = manager.prepare_run_context(memory, '', [summary])
    model = _SummaryModel()
    result = manager.assemble_final_context(model=model, memory=memory, current_run_start_idx=0, run_context=run)
    assert model.calls == []
    assert result.evidence.history_compression_triggered is False
    assert 'accepted checkpoint ' * 1000 in _rendered_text(result.messages)
