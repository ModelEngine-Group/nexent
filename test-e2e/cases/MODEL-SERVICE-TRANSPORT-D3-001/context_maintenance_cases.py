# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Shared maintenance through actual model HTTP and SSE boundaries."""

from nexent.core.agents.context import (
    ContextItemInput,
    ContextManager,
    ContextManagerConfig,
)
from nexent.core.model_service.compatibility.legacy_chat_model import LegacyChatModel
from smolagents.memory import AgentMemory, TaskStep


def test_shared_context_maintenance_uses_completed_provider_usage(peer, request):
    module = request.module
    service, _, profile, limiter, journal, credentials = module.setup(peer, 'compatible_eof')
    model = LegacyChatModel(profile, service)
    persisted = []
    config = ContextManagerConfig(
        effective_input_limit_tokens=50, history_summary_sink=persisted.append,
        policy_layers={'request': {'processing_mode': 'passthrough'}},
    )
    manager = ContextManager(config)
    history_text = 'ORIGINAL-HISTORY-SENTINEL ' + 'historical evidence ' * 1000
    history = ContextItemInput(id='turn:1:2', type='conversation_turn', content={
        'user_message': history_text, 'assistant_final_answer': 'previous result',
        'user_message_id': 1, 'assistant_message_id': 2, 'attachments': [],
    })
    memory = AgentMemory(system_prompt='Keep original evidence.')
    memory.steps.append(TaskStep(task='current task'))
    run = manager.prepare_run_context(memory, 'Keep original evidence.', [history])
    initial = manager.assemble_final_context(model=model, memory=memory, current_run_start_idx=0, run_context=run)
    assert initial.evidence.exceeds_effective_input_limit
    model(initial.messages)
    observation = model.last_context_observation
    assert observation.input_tokens == 10
    same = manager.assemble_final_context(model=model, memory=memory, current_run_start_idx=0, run_context=run)
    assert same.evidence.final_token_estimate == 10
    assert same.evidence.observed_provider_input_tokens == 10
    assert same.evidence.token_estimate_basis == 'provider_calibrated_estimate'

    # Real auxiliary inference returns noncanonical prose, so it must not
    # replace the accepted checkpoint or the main-request observation.
    config.policy_layers = {'request': {'processing_mode': 'adaptive_compact'}}
    memory.steps.append(TaskStep(task='NEW-CURRENT-TASK ' + 'new input ' * 200))
    changed = manager.assemble_final_context(model=model, memory=memory, current_run_start_idx=0, run_context=run)
    assert changed.evidence.history_compression_triggered
    assert changed.evidence.final_token_estimate > 10
    assert changed.evidence.exceeds_effective_input_limit
    assert model.last_context_observation is observation
    assert not persisted and changed.evidence.new_summary_coverage is None
    response = model(changed.messages)
    assert response.content == 'compatible'
    actual = module.records(journal, scenario='compatible_eof')
    assert len(actual) == len(credentials) == 3  # Initial, rejected summary, next main request.
    sent = str(actual[-1]['body']['messages'])
    assert history_text in sent and 'NEW-CURRENT-TASK' in sent
    assert not limiter._entries


def test_shared_context_unknown_usage_does_not_block_request(peer, request):
    module = request.module
    service, _, profile, limiter, journal, credentials = module.setup(peer, 'compatible_no_usage')
    model = LegacyChatModel(profile, service)
    manager = ContextManager(ContextManagerConfig(effective_input_limit_tokens=1,
        policy_layers={'request': {'processing_mode': 'passthrough'}}))
    memory = AgentMemory(system_prompt='Preserve the input.')
    memory.steps.append(TaskStep(task='PROTECTED INPUT ' * 200))
    run = manager.prepare_run_context(memory, 'Preserve the input.')
    for _ in range(2):
        context = manager.assemble_final_context(model=model, memory=memory, current_run_start_idx=0, run_context=run)
        assert context.evidence.exceeds_effective_input_limit
        assert context.evidence.observed_provider_input_tokens is None
        assert context.evidence.token_estimate_basis == 'local_estimate'
        response = model(context.messages)
        assert response.content == 'unknown usage response' and response.token_usage is None
        assert model.last_context_observation is None
    assert len(module.records(journal, scenario='compatible_no_usage')) == len(credentials) == 2
    assert not limiter._entries


def test_explicit_overflow_rebuilds_shared_history_even_when_estimate_fits(peer, request):
    from nexent.core.agents.context.runtime import ManagedContextRuntime

    module = request.module
    service, _, profile, limiter, journal, credentials = module.setup(peer, 'shared_context_overflow')
    model = LegacyChatModel(profile, service)
    saved = []
    manager = ContextManager(ContextManagerConfig(effective_input_limit_tokens=1_000_000,
        history_summary_sink=saved.append, policy_layers={'request': {'processing_mode': 'adaptive_compact'}}))
    history = ContextItemInput(id='turn:1:2', type='conversation_turn', content={
        'user_message': 'SOURCE-FACT-001 is ORCHID-7429.\n' + 'old evidence ' * 200,
        'assistant_final_answer': 'Keep the exact fact.', 'user_message_id': 1, 'assistant_message_id': 2,
        'attachments': [],
    })
    memory = AgentMemory(system_prompt='Keep protected context.')
    runtime = ManagedContextRuntime(manager, [history])
    runtime.prepare_run(memory=memory, fallback_system_prompt='Keep protected context.')
    memory.steps.append(TaskStep(task='PROTECTED-CURRENT-TASK'))
    initial = runtime.prepare_step(model=model, memory=memory, current_run_start_idx=0)
    assert not initial.evidence.history_compression_triggered
    assert initial.evidence.final_token_estimate < initial.evidence.compaction_trigger_threshold_tokens
    response = model(initial.messages, context_rebuild=lambda: runtime.recover_step(
        model=model, memory=memory, current_run_start_idx=0))
    assert response.content == 'recovered' and response.model_attempt_number == 2
    assert len(saved) == 1 and saved[0].covered_through_message_id == 2
    captured = module.records(journal, scenario='shared_context_overflow')
    assert len(captured) == 3  # Rejected main, real summary, rebuilt main.
    assert len(credentials) == 2  # Two logical requests; the main retry retains frozen credentials.
    assert 'PROTECTED-CURRENT-TASK' not in str(captured[1]['body']['messages'])
    rebuilt = str(captured[-1]['body']['messages'])
    assert 'PROTECTED-CURRENT-TASK' in rebuilt and 'ORCHID-7429' in rebuilt
    assert 'old evidence ' * 200 not in rebuilt
    assert not limiter._entries
