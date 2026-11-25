# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""PR4336: runtime capacity must not depend on retired model settings."""

import pytest
from nexent.core.models.capacity_resolver import resolve_capacity, ProviderCapabilityUnknown
from nexent.core.models.capacity_budget import CapacityReservePolicy, ContextBudgetCalculator


def capacity(**changes):
    return resolve_capacity(model_id="controlled", provider="custom", capability_profiles={},
        operator_overrides={"context_window_tokens": 128000, "max_output_tokens": 2048, **changes})


@pytest.mark.parametrize("retired", [{}, {"max_input_tokens": 1024},
    {"default_output_reserve_tokens": 100000}, {"max_input_tokens": 120000, "default_output_reserve_tokens": 128}])
def test_ac013_retired_values_do_not_change_capacity_or_fingerprint(retired):
    actual = capacity(**retired)
    expected = capacity()
    assert actual.provider_input_limit_tokens == 128000
    assert actual.fingerprint == expected.fingerprint
    assert actual.requested_output_tokens is None
    assert actual.max_input_tokens is None
    assert actual.default_output_reserve_tokens is None


def test_ac003_small_output_cap_does_not_trigger_fixed_default_conflict():
    snapshot = capacity()
    budget = ContextBudgetCalculator().calculate_context_budget(
        capacity_snapshot=snapshot, reserve_policy=CapacityReservePolicy())
    assert budget.effective_input_limit_tokens == 128000
    assert budget.compaction_trigger_threshold_tokens == 108000
    assert budget.compaction_target_tokens == 88000
    assert budget.requested_output_tokens is None


def test_ac005_missing_combined_window_cannot_be_replaced_by_retired_input_cap():
    with pytest.raises(ProviderCapabilityUnknown):
        capacity(context_window_tokens=None, max_input_tokens=100000)


def test_explicit_remaining_space_policy_takes_precedence_over_legacy_trigger():
    policy = CapacityReservePolicy(remaining_window_ratio=.1, remaining_window_max_tokens=20000,
        compaction_trigger_ratio=.5, compaction_trigger_ratio_source="tenant_config",
        maintenance_target_multiplier=3)
    budget = ContextBudgetCalculator().calculate_context_budget(capacity_snapshot=capacity(), reserve_policy=policy)
    assert budget.compaction_trigger_threshold_tokens == 115200
    assert budget.compaction_target_tokens == 89600


@pytest.mark.parametrize("values", [{"remaining_window_ratio": 0}, {"remaining_window_ratio": 1},
    {"remaining_window_max_tokens": 0}, {"maintenance_target_multiplier": 1},
    {"maintenance_target_multiplier": float("inf")}])
def test_invalid_maintenance_policy_is_rejected(values):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        CapacityReservePolicy(**values)
