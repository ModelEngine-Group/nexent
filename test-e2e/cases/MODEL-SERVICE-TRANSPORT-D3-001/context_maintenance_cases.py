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
