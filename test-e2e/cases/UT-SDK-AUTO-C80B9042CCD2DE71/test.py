from __future__ import annotations

import math

import pytest

from nexent.core.models.capacity_budget import (
    CONTEXT_BUDGET_FINGERPRINT_SCHEMA_VERSION,
    CONTEXT_BUDGET_RESOLVER_VERSION,
    ContextBudgetFingerprintMismatch,
    ContextBudgetSnapshot,
    compute_context_budget_fingerprint,
    parse_context_budget_snapshot,
    validate_context_budget_snapshot,
)
from nexent.core.models.capacity_budget import _compute_legacy_w2_fingerprint


def _build_v2_fingerprint(payload):
    return compute_context_budget_fingerprint(
        resolver_version=payload['resolver_version'],
        w1_fingerprint=payload['w1_fingerprint'],
        provider=payload['provider'],
        model_name=payload['model_name'],
        requested_output_tokens=payload['requested_output_tokens'],
        output_reserve_source=payload['output_reserve_source'],
        uncertainty_reserve_tokens=payload['uncertainty_reserve_tokens'],
        uncertainty_reserve_basis=payload['uncertainty_reserve_basis'],
        approved_profile_reserve_tokens=payload.get('approved_profile_reserve_tokens'),
        effective_input_limit_tokens=payload['effective_input_limit_tokens'],
        compaction_trigger_ratio=payload['compaction_trigger_ratio'],
        compaction_trigger_ratio_source=payload['compaction_trigger_ratio_source'],
        compaction_trigger_threshold_tokens=payload['compaction_trigger_threshold_tokens'],
        compaction_target_ratio=payload['compaction_target_ratio'],
        compaction_target_ratio_source=payload['compaction_target_ratio_source'],
        compaction_target_tokens=payload['compaction_target_tokens'],
        field_sources=payload['field_sources'],
        warnings=payload.get('warnings', ()),
    )


@pytest.mark.case_id('UT-SDK-AUTO-C80B9042CCD2DE71')
@pytest.mark.stage('D1')
def test_parse_context_budget_snapshot_v2_fingerprint_and_legacy_migration():
    v2_payload = {
        'w1_fingerprint': 'w1-fp-v2-0001',
        'provider': 'openai',
        'model_name': 'gpt-4o',
        'requested_output_tokens': 2000,
        'output_reserve_source': 'agent',
        'effective_input_limit_tokens': 100000,
        'uncertainty_reserve_tokens': 5000,
        'uncertainty_reserve_basis': 'approved_profile',
        'approved_profile_reserve_tokens': 5000,
        'compaction_trigger_ratio': 0.9,
        'compaction_trigger_ratio_source': 'tenant_config',
        'compaction_trigger_threshold_tokens': 90000,
        'compaction_target_ratio': 0.7,
        'compaction_target_ratio_source': 'tenant_config',
        'compaction_target_tokens': 70000,
        'field_sources': {
            'effective_input_limit_tokens': 'derived',
            'compaction_target_ratio': 'tenant_config',
        },
        'warnings': ['seed_warning'],
        'schema_version': 2,
        'resolver_version': '2.0.0',
    }
    v2_fingerprint = _build_v2_fingerprint(v2_payload)
    v2_payload['fingerprint'] = v2_fingerprint

    snapshot = parse_context_budget_snapshot(v2_payload)

    assert isinstance(snapshot, ContextBudgetSnapshot)
    assert snapshot.schema_version == CONTEXT_BUDGET_FINGERPRINT_SCHEMA_VERSION
    assert snapshot.schema_version == 2
    assert snapshot.resolver_version == CONTEXT_BUDGET_RESOLVER_VERSION
    assert snapshot.resolver_version == '2.0.0'
    assert snapshot.w1_fingerprint == 'w1-fp-v2-0001'
    assert snapshot.provider == 'openai'
    assert snapshot.model_name == 'gpt-4o'
    assert snapshot.requested_output_tokens == 2000
    assert snapshot.output_reserve_source == 'agent'
    assert snapshot.effective_input_limit_tokens == 100000
    assert snapshot.uncertainty_reserve_tokens == 5000
    assert snapshot.uncertainty_reserve_basis == 'approved_profile'
    assert snapshot.approved_profile_reserve_tokens == 5000
    assert snapshot.compaction_trigger_ratio == 0.9
    assert snapshot.compaction_trigger_ratio_source == 'tenant_config'
    assert snapshot.compaction_trigger_threshold_tokens == 90000
    assert snapshot.compaction_target_ratio == 0.7
    assert snapshot.compaction_target_ratio_source == 'tenant_config'
    assert snapshot.compaction_target_tokens == 70000
    assert snapshot.field_sources == {
        'effective_input_limit_tokens': 'derived',
        'compaction_target_ratio': 'tenant_config',
    }
    assert snapshot.fingerprint == v2_fingerprint

    wrong_v2_fingerprint = '0' * 32
    assert wrong_v2_fingerprint != v2_fingerprint
    v2_bad_payload = dict(v2_payload)
    v2_bad_payload['fingerprint'] = wrong_v2_fingerprint
    with pytest.raises(ContextBudgetFingerprintMismatch) as excinfo:
        parse_context_budget_snapshot(v2_bad_payload)
    assert excinfo.value.expected == v2_fingerprint
    assert excinfo.value.actual == wrong_v2_fingerprint

    assert validate_context_budget_snapshot(snapshot) is snapshot
    assert parse_context_budget_snapshot(snapshot) is snapshot

    tampered_instance = snapshot.model_copy(update={'effective_input_limit_tokens': 99999})
    with pytest.raises(ContextBudgetFingerprintMismatch) as excinfo2:
        parse_context_budget_snapshot(tampered_instance)
    assert excinfo2.value.actual == snapshot.fingerprint
    assert excinfo2.value.expected != excinfo2.value.actual

    legacy_payload = {
        'w1_fingerprint': 'w1-fp-legacy-0001',
        'provider': 'anthropic',
        'model_name': 'claude-sonnet',
        'requested_output_tokens': 1000,
        'output_reserve_source': 'model_default',
        'uncertainty_reserve_tokens': 12000,
        'uncertainty_reserve_basis': 'context_window_10pct',
        'provider_input_limit_tokens': 120000,
        'soft_limit_ratio': 0.8,
        'soft_limit_ratio_source': 'code_default',
        'soft_input_budget_tokens': 96000,
        'hard_input_budget_tokens': 120000,
        'field_sources': {
            'provider_input_limit_tokens': 'operator',
            'soft_limit_ratio': 'operator',
            'soft_input_budget_tokens': 'derived',
            'hard_input_budget_tokens': 'derived',
            'requested_output_tokens': 'model_default',
            'uncertainty_reserve_tokens': 'context_window_10pct',
            'custom_key': 'agent',
        },
        'resolver_version': '1.0.0',
    }
    legacy_fingerprint = _compute_legacy_w2_fingerprint(legacy_payload)
    legacy_payload['fingerprint'] = legacy_fingerprint

    migrated = parse_context_budget_snapshot(legacy_payload)

    assert isinstance(migrated, ContextBudgetSnapshot)
    assert migrated.effective_input_limit_tokens == 120000
    assert migrated.compaction_trigger_ratio == 0.8
    assert migrated.compaction_trigger_ratio_source == 'legacy_payload'
    assert migrated.compaction_trigger_threshold_tokens == 96000
    assert migrated.compaction_target_ratio == 0.6
    assert migrated.compaction_target_ratio_source == 'code_default'
    assert migrated.compaction_target_tokens == max(1, math.floor(120000 * 0.6))
    assert migrated.schema_version == 2
    assert migrated.resolver_version == '2.0.0'

    expected_field_sources = {
        'requested_output_tokens': 'model_default',
        'uncertainty_reserve_tokens': 'context_window_10pct',
        'custom_key': 'agent',
        'effective_input_limit_tokens': 'operator',
        'compaction_trigger_ratio': 'operator',
        'compaction_trigger_threshold_tokens': 'derived',
        'compaction_target_ratio': 'code_default',
        'compaction_target_tokens': 'derived',
    }
    assert dict(migrated.field_sources) == expected_field_sources
    for removed in (
        'provider_input_limit_tokens',
        'soft_limit_ratio',
        'soft_input_budget_tokens',
        'hard_input_budget_tokens',
    ):
        assert removed not in migrated.field_sources

    assert list(migrated.warnings) == ['legacy_w2_v1_payload_migrated']

    migrated_fingerprint = compute_context_budget_fingerprint(
        resolver_version='2.0.0',
        w1_fingerprint='w1-fp-legacy-0001',
        provider='anthropic',
        model_name='claude-sonnet',
        requested_output_tokens=1000,
        output_reserve_source='model_default',
        uncertainty_reserve_tokens=12000,
        uncertainty_reserve_basis='context_window_10pct',
        approved_profile_reserve_tokens=None,
        effective_input_limit_tokens=120000,
        compaction_trigger_ratio=0.8,
        compaction_trigger_ratio_source='legacy_payload',
        compaction_trigger_threshold_tokens=96000,
        compaction_target_ratio=0.6,
        compaction_target_ratio_source='code_default',
        compaction_target_tokens=max(1, math.floor(120000 * 0.6)),
        field_sources=expected_field_sources,
        warnings=['legacy_w2_v1_payload_migrated'],
    )
    assert migrated.fingerprint == migrated_fingerprint

    wrong_legacy_fingerprint = 'f' * 32
    assert wrong_legacy_fingerprint != legacy_fingerprint
    legacy_bad_payload = dict(legacy_payload)
    legacy_bad_payload['fingerprint'] = wrong_legacy_fingerprint
    with pytest.raises(ContextBudgetFingerprintMismatch) as excinfo3:
        parse_context_budget_snapshot(legacy_bad_payload)
    assert excinfo3.value.expected == legacy_fingerprint
    assert excinfo3.value.actual == wrong_legacy_fingerprint

    boundary_payload = dict(legacy_payload)
    boundary_payload['provider_input_limit_tokens'] = 1
    boundary_payload['soft_input_budget_tokens'] = 1
    boundary_payload['hard_input_budget_tokens'] = 1
    boundary_payload['field_sources'] = dict(legacy_payload['field_sources'])
    boundary_payload['fingerprint'] = _compute_legacy_w2_fingerprint(boundary_payload)
    boundary = parse_context_budget_snapshot(boundary_payload)
    assert boundary.effective_input_limit_tokens == 1
    assert boundary.compaction_target_tokens == max(1, math.floor(1 * 0.6))
    assert boundary.compaction_target_tokens == 1
    assert boundary.schema_version == 2

    migrated_again = parse_context_budget_snapshot(legacy_payload)
    assert migrated_again == migrated
    assert migrated_again.fingerprint == migrated.fingerprint
    assert migrated_again.model_dump() == migrated.model_dump()
