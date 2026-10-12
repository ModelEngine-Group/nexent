from __future__ import annotations

import pytest

from nexent.core.models.capacity_budget import (
    CapacityReservePolicy,
    ContextBudgetCalculator,
    InvalidReservePolicy,
    NoSafeInputCapacity,
    RequestBudgetOverrides,
    RequestedOutputExceedsCapacity,
    ReserveExceedsCapacity,
    UncertaintyReserveBasisUnknown,
    validate_context_budget_snapshot,
)
from nexent.core.models.capacity_resolver import ModelCapacitySnapshot

CASE_ID = 'UT-SDK-AUTO-5DD3BD24C1EF4718'


def _make_snapshot(
    *,
    provider: str = 'openai',
    model_name: str = 'gpt-x',
    context_window_tokens: int | None = None,
    max_input_tokens: int | None = None,
    max_output_tokens: int | None = None,
    requested_output_tokens: int = 2000,
    unknown_capabilities: frozenset[str] | set[str] | list[str] = frozenset(),
    fingerprint: str = 'w1-fp-0001',
) -> ModelCapacitySnapshot:
    return ModelCapacitySnapshot(
        provider=provider,
        model_name=model_name,
        context_window_tokens=context_window_tokens,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        requested_output_tokens=requested_output_tokens,
        provider_input_limit_tokens=0,
        counting_mode='exact',
        unknown_capabilities=list(unknown_capabilities),
        fingerprint=fingerprint,
    )


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D1')
def test_context_budget_calculator_contract_and_exceptions() -> None:
    calculator = ContextBudgetCalculator()

    normal_snapshot = _make_snapshot(
        max_input_tokens=10000,
        context_window_tokens=8000,
        max_output_tokens=4000,
        requested_output_tokens=2000,
    )
    default_policy = CapacityReservePolicy()
    budget = calculator.calculate_context_budget(
        capacity_snapshot=normal_snapshot,
        reserve_policy=default_policy,
        requested_output_tokens=None,
    )

    assert budget.effective_input_limit_tokens == 6000
    assert budget.requested_output_tokens == 2000
    assert budget.output_reserve_source == 'model_default'
    assert budget.uncertainty_reserve_tokens == 0
    assert budget.uncertainty_reserve_basis == 'none'
    assert list(budget.warnings) == []
    assert budget.compaction_trigger_threshold_tokens == 4800
    assert budget.compaction_target_tokens == 3600
    assert budget.field_sources['effective_input_limit_tokens'] == 'derived'
    assert budget.field_sources['compaction_trigger_threshold_tokens'] == 'derived'
    assert budget.field_sources['compaction_target_tokens'] == 'derived'
    assert budget.field_sources['compaction_trigger_ratio'] == 'code_default'
    assert budget.field_sources['compaction_target_ratio'] == 'code_default'
    assert budget.field_sources['uncertainty_reserve_tokens'] == 'none'
    assert budget.field_sources['requested_output_tokens'] == 'model_default'
    assert budget.schema_version == 2
    assert budget.resolver_version == '2.0.0'
    assert budget.w1_fingerprint == 'w1-fp-0001'
    assert budget.provider == 'openai'
    assert budget.model_name == 'gpt-x'
    assert validate_context_budget_snapshot(budget) is budget

    cw_snapshot = _make_snapshot(
        context_window_tokens=10000,
        max_input_tokens=20000,
        requested_output_tokens=2000,
        unknown_capabilities={'tokenizer'},
    )
    cw_budget = calculator.calculate_context_budget(
        capacity_snapshot=cw_snapshot,
        reserve_policy=CapacityReservePolicy(),
    )
    assert cw_budget.uncertainty_reserve_tokens == 1000
    assert cw_budget.uncertainty_reserve_basis == 'context_window_10pct'
    assert 'uncertainty_reserve_active' in cw_budget.warnings

    profile_budget = calculator.calculate_context_budget(
        capacity_snapshot=cw_snapshot,
        reserve_policy=CapacityReservePolicy(approved_profile_reserve_tokens=500),
    )
    assert profile_budget.uncertainty_reserve_tokens == 500
    assert profile_budget.uncertainty_reserve_basis == 'approved_profile'
    assert profile_budget.approved_profile_reserve_tokens == 500

    override_budget = calculator.calculate_context_budget(
        capacity_snapshot=normal_snapshot,
        reserve_policy=default_policy,
        request_overrides=RequestBudgetOverrides(requested_output_tokens=3000),
    )
    assert override_budget.requested_output_tokens == 3000
    assert override_budget.output_reserve_source == 'request'
    assert override_budget.effective_input_limit_tokens == 5000
    assert override_budget.field_sources['requested_output_tokens'] == 'request'

    tiny_snapshot = _make_snapshot(
        context_window_tokens=100,
        max_input_tokens=None,
        max_output_tokens=None,
        requested_output_tokens=99,
    )
    tiny_budget = calculator.calculate_context_budget(
        capacity_snapshot=tiny_snapshot,
        reserve_policy=default_policy,
    )
    assert tiny_budget.compaction_trigger_threshold_tokens == 1
    assert tiny_budget.compaction_target_tokens == 1

    with pytest.raises(InvalidReservePolicy):
        calculator.calculate_context_budget(
            capacity_snapshot=normal_snapshot,
            reserve_policy=default_policy,
            requested_output_tokens=0,
        )

    with pytest.raises(InvalidReservePolicy):
        calculator.calculate_context_budget(
            capacity_snapshot=normal_snapshot,
            reserve_policy=default_policy,
            request_overrides=RequestBudgetOverrides(requested_output_tokens=1000),
        )

    with pytest.raises(RequestedOutputExceedsCapacity):
        calculator.calculate_context_budget(
            capacity_snapshot=normal_snapshot,
            reserve_policy=default_policy,
            requested_output_tokens=5000,
        )

    no_limits_snapshot = _make_snapshot(
        context_window_tokens=None,
        max_input_tokens=None,
        max_output_tokens=None,
        requested_output_tokens=2000,
    )
    with pytest.raises(NoSafeInputCapacity):
        calculator.calculate_context_budget(
            capacity_snapshot=no_limits_snapshot,
            reserve_policy=default_policy,
        )

    non_positive_snapshot = _make_snapshot(
        context_window_tokens=1000,
        max_input_tokens=None,
        max_output_tokens=None,
        requested_output_tokens=2000,
    )
    with pytest.raises(NoSafeInputCapacity):
        calculator.calculate_context_budget(
            capacity_snapshot=non_positive_snapshot,
            reserve_policy=default_policy,
        )

    no_window_unknown_snapshot = _make_snapshot(
        context_window_tokens=None,
        max_input_tokens=20000,
        max_output_tokens=None,
        requested_output_tokens=2000,
        unknown_capabilities={'tokenizer'},
    )
    with pytest.raises(UncertaintyReserveBasisUnknown):
        calculator.calculate_context_budget(
            capacity_snapshot=no_window_unknown_snapshot,
            reserve_policy=default_policy,
        )

    with pytest.raises(ReserveExceedsCapacity):
        calculator.calculate_context_budget(
            capacity_snapshot=normal_snapshot,
            reserve_policy=CapacityReservePolicy(approved_profile_reserve_tokens=99999),
        )
