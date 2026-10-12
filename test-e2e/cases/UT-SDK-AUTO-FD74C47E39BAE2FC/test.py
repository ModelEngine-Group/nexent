from __future__ import annotations

import pytest

from smolagents.memory import AgentMemory, TaskStep

from nexent.core.agents.context.config import ContextManagerConfig
from nexent.core.agents.context.manager import ContextManager
from nexent.core.agents.context.models import ContextItem, ContextItemInput, ContextItemType
from nexent.core.agents.context.policy import ContextPolicy, ContextProcessingMode, PolicyLayers


CASE_ID = 'UT-SDK-AUTO-FD74C47E39BAE2FC'

ADAPTIVE_LAYERS = PolicyLayers(
    request=ContextPolicy(processing_mode=ContextProcessingMode.ADAPTIVE_COMPACT),
)

PASSTHROUGH_LAYERS = PolicyLayers(
    request=ContextPolicy(processing_mode=ContextProcessingMode.PASSTHROUGH),
)

SUMMARY_TEXT = (
    '# Compact Result of History\n'
    '## Task Overview\nx\n'
    '## Completed Work\nx\n'
    '## Key Decisions\nx\n'
    '## Unresolved Issues\nx\n'
    '## Pending Items\nx\n'
    '## Next Steps\nx\n'
    '## Context To Preserve\nx\n'
)


class _FakeResponse:
    def __init__(self, content):
        self.content = content


class _FakeModel:
    def __init__(self, text):
        self._text = text

    def __call__(self, messages, stop_sequences=None, **kwargs):
        return _FakeResponse(self._text)


def _turn_input(index, user_text, assistant_text):
    return ContextItemInput(
        id='turn:' + str(index),
        type=ContextItemType.CONVERSATION_TURN,
        content={
            'user_message': user_text,
            'assistant_final_answer': assistant_text,
            'user_message_id': index,
            'assistant_message_id': index,
        },
        metadata={'layout_order': index},
    )


def _history_tokens(inputs):
    return sum(ContextItem.from_input(item).token_estimate for item in inputs)


def _memory(steps):
    memory = AgentMemory(system_prompt='system')
    memory.steps = list(steps)
    return memory


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D1')
def test_adaptive_compaction_trigger_target_effective_and_non_history_checkpoint():
    model = _FakeModel(SUMMARY_TEXT)

    # Threshold fallback: no effective limit, trigger/target left unset.
    fallback_manager = ContextManager(ContextManagerConfig(
        token_threshold=10000,
        compaction_trigger_threshold_tokens=0,
        compaction_target_tokens=0,
        policy_layers=ADAPTIVE_LAYERS,
    ))
    assert fallback_manager._compaction_trigger_threshold_tokens() == 10000
    assert fallback_manager._compaction_target_tokens() == 7500

    # Passthrough mode never compacts history.
    passthrough_manager = ContextManager(ContextManagerConfig(
        effective_input_limit_tokens=5000,
        compaction_trigger_threshold_tokens=500,
        compaction_target_tokens=1000,
        policy_layers=PASSTHROUGH_LAYERS,
    ))
    passthrough_turns = [_turn_input(1, 'q' * 2000, 'a')]
    passthrough_memory = _memory([])
    passthrough_run = passthrough_manager.prepare_run_context(
        passthrough_memory, '', items=list(passthrough_turns),
    )
    passthrough_final = passthrough_manager.assemble_final_context(
        model=model, memory=passthrough_memory, current_run_start_idx=0,
        run_context=passthrough_run,
    )
    assert passthrough_final.evidence.history_compression_triggered is False
    assert passthrough_final.evidence.compaction_stop_reason == 'not_triggered'

    # Scenario A: compressible history (non_history < compaction_target).
    manager_a = ContextManager(ContextManagerConfig(
        effective_input_limit_tokens=5000,
        compaction_trigger_threshold_tokens=500,
        compaction_target_tokens=1000,
        policy_layers=ADAPTIVE_LAYERS,
    ))
    turns_a = [_turn_input(1, 'q' * 2000, 'a')]
    memory_a = _memory([])
    run_a = manager_a.prepare_run_context(memory_a, '', items=list(turns_a))
    final_a = manager_a.assemble_final_context(
        model=model, memory=memory_a, current_run_start_idx=0, run_context=run_a,
    )
    evidence_a = final_a.evidence
    expected_history_a = _history_tokens(turns_a)
    assert evidence_a.processing_mode == 'adaptive_compact'
    assert evidence_a.non_history_tokens < evidence_a.compaction_target_tokens
    assert evidence_a.non_history_tokens == max(
        0, evidence_a.raw_token_estimate - evidence_a.compressible_history_tokens
    )
    assert evidence_a.compressible_history_tokens == expected_history_a
    assert evidence_a.history_compression_triggered is True
    assert evidence_a.compaction_stop_reason in {
        'history_target_reached', 'request_target_reached'
    }
    assert evidence_a.new_summary_coverage is not None

    # Scenario B: non_history already exceeds effective limit.
    manager_b = ContextManager(ContextManagerConfig(
        effective_input_limit_tokens=100,
        compaction_trigger_threshold_tokens=50,
        compaction_target_tokens=40,
        policy_layers=ADAPTIVE_LAYERS,
    ))
    turns_b = [_turn_input(1, 'q', 'a')]
    memory_b = _memory([TaskStep(task='t' * 5000)])
    run_b = manager_b.prepare_run_context(memory_b, '', items=list(turns_b))
    final_b = manager_b.assemble_final_context(
        model=model, memory=memory_b, current_run_start_idx=0, run_context=run_b,
    )
    evidence_b = final_b.evidence
    expected_history_b = _history_tokens(turns_b)
    assert evidence_b.non_history_tokens >= evidence_b.effective_input_limit_tokens
    assert evidence_b.history_compression_triggered is False
    assert evidence_b.compaction_stop_reason == 'history_target_reached'
    assert evidence_b.exceeds_effective_input_limit is True
    assert evidence_b.final_token_estimate > evidence_b.effective_input_limit_tokens
    assert evidence_b.compressible_history_tokens == expected_history_b
    assert evidence_b.non_history_tokens == max(
        0, evidence_b.raw_token_estimate - evidence_b.compressible_history_tokens
    )
    assert 'turn:1' in evidence_b.selected_item_ids

    # Scenario C: target/effective boundary (target <= non_history < effective).
    manager_c = ContextManager(ContextManagerConfig(
        effective_input_limit_tokens=3000,
        compaction_trigger_threshold_tokens=500,
        compaction_target_tokens=1000,
        policy_layers=ADAPTIVE_LAYERS,
    ))
    # The history must exceed the effective-limit remainder.  A smaller
    # fixture only reaches the trigger threshold and correctly avoids a
    # pointless summary, which does not exercise this boundary branch.
    turns_c = [_turn_input(1, 'q' * 12000, 'a')]
    memory_c = _memory([TaskStep(task='t' * 2400)])
    run_c = manager_c.prepare_run_context(memory_c, '', items=list(turns_c))
    final_c = manager_c.assemble_final_context(
        model=model, memory=memory_c, current_run_start_idx=0, run_context=run_c,
    )
    evidence_c = final_c.evidence
    expected_history_c = _history_tokens(turns_c)
    assert evidence_c.non_history_tokens >= evidence_c.compaction_target_tokens
    assert evidence_c.non_history_tokens < evidence_c.effective_input_limit_tokens
    assert evidence_c.history_compression_triggered is True
    assert evidence_c.compaction_stop_reason in {
        'history_target_reached', 'request_target_reached'
    }
    assert evidence_c.compressible_history_tokens == expected_history_c
