from __future__ import annotations

import re

import pytest

from nexent.core.models.capacity_budget import (
    CONTEXT_BUDGET_RESOLVER_VERSION,
    CallerMaxTokensOverrideForbidden,
    CapacityReservePolicy,
    ContextBudgetCalculator,
    ContextBudgetCapacityMismatch,
    ContextBudgetFingerprintMismatch,
    ContextBudgetSnapshot,
    _compute_legacy_w2_fingerprint,
    compute_context_budget_fingerprint,
    parse_context_budget_snapshot,
    validate_context_budget_snapshot,
)
from nexent.core.models.capacity_resolver import ModelCapacitySnapshot


CASE_ID = 'UT-SDK-AUTO-9B9B36B05DA14338'


def _fingerprint_kwargs():
    return dict(
        resolver_version=CONTEXT_BUDGET_RESOLVER_VERSION,
        w1_fingerprint='w1-fp-0123456789abcdef0123456789ab',
        provider='openai',
        model_name='gpt-4o',
        requested_output_tokens=2048,
        output_reserve_source='model_default',
        uncertainty_reserve_tokens=12800,
        uncertainty_reserve_basis='context_window_10pct',
        approved_profile_reserve_tokens=None,
        effective_input_limit_tokens=125952,
        compaction_trigger_ratio=0.8,
        compaction_trigger_ratio_source='code_default',
        compaction_trigger_threshold_tokens=100762,
        compaction_target_ratio=0.6,
        compaction_target_ratio_source='code_default',
        compaction_target_tokens=75571,
        field_sources={
            'requested_output_tokens': 'model_default',
            'compaction_trigger_ratio': 'code_default',
            'compaction_target_ratio': 'code_default',
            'uncertainty_reserve_tokens': 'context_window_10pct',
        },
        warnings=(),
    )


def _recompute_snapshot_fingerprint(snapshot: ContextBudgetSnapshot) -> str:
    return compute_context_budget_fingerprint(
        resolver_version=snapshot.resolver_version,
        w1_fingerprint=snapshot.w1_fingerprint,
        provider=snapshot.provider,
        model_name=snapshot.model_name,
        requested_output_tokens=snapshot.requested_output_tokens,
        output_reserve_source=snapshot.output_reserve_source,
        uncertainty_reserve_tokens=snapshot.uncertainty_reserve_tokens,
        uncertainty_reserve_basis=snapshot.uncertainty_reserve_basis,
        approved_profile_reserve_tokens=snapshot.approved_profile_reserve_tokens,
        effective_input_limit_tokens=snapshot.effective_input_limit_tokens,
        compaction_trigger_ratio=snapshot.compaction_trigger_ratio,
        compaction_trigger_ratio_source=snapshot.compaction_trigger_ratio_source,
        compaction_trigger_threshold_tokens=snapshot.compaction_trigger_threshold_tokens,
        compaction_target_ratio=snapshot.compaction_target_ratio,
        compaction_target_ratio_source=snapshot.compaction_target_ratio_source,
        compaction_target_tokens=snapshot.compaction_target_tokens,
        field_sources=snapshot.field_sources,
        warnings=snapshot.warnings,
    )


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D1')
def test_context_budget_v2_fingerprint_determinism_and_snapshot_dispatch():
    base_kwargs = _fingerprint_kwargs()

    fp_default = compute_context_budget_fingerprint(**base_kwargs)
    fp_warned = compute_context_budget_fingerprint(
        **{**base_kwargs, 'warnings': ['uncertainty_reserve_active']}
    )
    fp_empty = compute_context_budget_fingerprint(
        **{**base_kwargs, 'warnings': []}
    )
    assert fp_default == fp_warned == fp_empty
    assert re.fullmatch(r'[0-9a-f]{32}', fp_default)

    reordered = dict(reversed(list(base_kwargs['field_sources'].items())))
    fp_reordered = compute_context_budget_fingerprint(
        **{**base_kwargs, 'field_sources': reordered}
    )
    assert fp_reordered == fp_default

    capacity = ModelCapacitySnapshot(
        provider='openai',
        model_name='gpt-4o',
        context_window_tokens=128000,
        max_output_tokens=4096,
        requested_output_tokens=2048,
        provider_input_limit_tokens=125952,
        counting_mode='exact',
        fingerprint='w1-fp-0123456789abcdef0123456789ab',
    )
    policy = CapacityReservePolicy()
    snapshot = ContextBudgetCalculator().calculate_context_budget(
        capacity_snapshot=capacity,
        reserve_policy=policy,
    )
    assert snapshot.schema_version == 2
    assert snapshot.resolver_version == '2.0.0'
    assert snapshot.fingerprint == _recompute_snapshot_fingerprint(snapshot)

    assert validate_context_budget_snapshot(snapshot) is snapshot

    expected_fp = _recompute_snapshot_fingerprint(snapshot)
    tampered_fp = 'deadbeef' * 4
    assert tampered_fp != expected_fp
    tampered = snapshot.model_copy(update={'fingerprint': tampered_fp})
    with pytest.raises(ContextBudgetFingerprintMismatch) as exc:
        validate_context_budget_snapshot(tampered)
    assert exc.value.expected == expected_fp
    assert exc.value.actual == tampered_fp

    legacy_payload = {
        'resolver_version': '1.0.0',
        'w1_fingerprint': 'w1-fp-0123456789abcdef0123456789ab',
        'provider': 'openai',
        'model_name': 'gpt-4o',
        'requested_output_tokens': 2048,
        'output_reserve_source': 'model_default',
        'uncertainty_reserve_tokens': 12800,
        'uncertainty_reserve_basis': 'context_window_10pct',
        'approved_profile_reserve_tokens': None,
        'soft_limit_ratio': 0.8,
        'soft_limit_ratio_source': 'code_default',
        'soft_input_budget_tokens': 100762,
        'hard_input_budget_tokens': 125952,
        'provider_input_limit_tokens': 125952,
        'field_sources': {
            'requested_output_tokens': 'model_default',
            'provider_input_limit_tokens': 'derived',
            'soft_limit_ratio': 'code_default',
            'soft_input_budget_tokens': 'derived',
            'hard_input_budget_tokens': 'derived',
        },
    }
    legacy_payload['fingerprint'] = _compute_legacy_w2_fingerprint(legacy_payload)
    migrated = parse_context_budget_snapshot(legacy_payload)
    assert migrated.schema_version == 2
    assert migrated.resolver_version == '2.0.0'
    assert migrated.compaction_target_ratio == 0.6
    assert migrated.compaction_trigger_ratio_source == 'legacy_payload'
    assert migrated.compaction_target_ratio_source == 'code_default'
    assert 'legacy_w2_v1_payload_migrated' in migrated.warnings

    mismatch = ContextBudgetCapacityMismatch(field='w1_fingerprint', expected='a', actual='b')
    assert 'context_budget_capacity_mismatch' in str(mismatch)
    assert mismatch.field == 'w1_fingerprint'
    assert mismatch.expected == 'a'
    assert mismatch.actual == 'b'

    forbidden = CallerMaxTokensOverrideForbidden(snapshot_value=2048, caller_value=4096)
    assert 'caller_max_tokens_override_forbidden' in str(forbidden)
    assert forbidden.snapshot_value == 2048
    assert forbidden.caller_value == 4096
