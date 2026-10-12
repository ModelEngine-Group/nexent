import logging
from unittest import mock

import pytest

from agents import create_agent_info
from agents.create_agent_info import _resolve_context_budget
from nexent.core.models.capacity_budget import (
    CapacityReservePolicy,
    ContextBudgetSnapshot,
    RequestBudgetOverrides,
    UncertaintyReserveBasisUnknown,
)
from nexent.core.models.capacity_resolver import ModelCapacitySnapshot


def _model_capacity_snapshot(**overrides):
    data = {
        'provider': 'openai',
        'model_name': 'gpt-4o',
        'context_window_tokens': 128000,
        'max_input_tokens': 128000,
        'max_output_tokens': 16384,
        'default_output_reserve_tokens': 4096,
        'requested_output_tokens': 4096,
        'provider_input_limit_tokens': 123904,
        'tokenizer_family': 'o200k_base',
        'counting_mode': 'exact',
        'fingerprint': 'w1-fingerprint',
    }
    data.update(overrides)
    return ModelCapacitySnapshot(**data)


def _context_budget_snapshot(**overrides):
    data = {
        'w1_fingerprint': 'w1-fingerprint',
        'provider': 'openai',
        'model_name': 'gpt-4o',
        'requested_output_tokens': 4096,
        'output_reserve_source': 'model_default',
        'effective_input_limit_tokens': 123904,
        'uncertainty_reserve_tokens': 12800,
        'uncertainty_reserve_basis': 'context_window_10pct',
        'compaction_trigger_ratio': 0.8,
        'compaction_trigger_ratio_source': 'code_default',
        'compaction_trigger_threshold_tokens': 99123,
        'compaction_target_ratio': 0.6,
        'compaction_target_ratio_source': 'code_default',
        'compaction_target_tokens': 74342,
        'fingerprint': 'w2-fingerprint',
    }
    data.update(overrides)
    return ContextBudgetSnapshot(**data)


@pytest.mark.case_id('UT-BE-AUTO-9411BBC4D2CE908C')
@pytest.mark.stage('D1')
def test_resolve_context_budget_w2_snapshot_and_w1_fallback(caplog):
    capacity_with_window = _model_capacity_snapshot()
    reserve_policy = CapacityReservePolicy()
    calculator = mock.MagicMock()

    with mock.patch.object(
        create_agent_info,
        'ContextBudgetCalculator',
        return_value=calculator,
    ), mock.patch.object(
        create_agent_info.tenant_config_manager,
        'get_capacity_reserve_policy',
        return_value=reserve_policy,
    ):
        assert (
            _resolve_context_budget(
                capacity_snapshot=None,
                tenant_id='tenant-1',
                agent_requested_output_tokens=None,
                request_requested_output_tokens=None,
            )
            is None
        )
        calculator.calculate_context_budget.assert_not_called()

        expected = _context_budget_snapshot()
        calculator.calculate_context_budget.return_value = expected
        resolved = _resolve_context_budget(
            capacity_snapshot=capacity_with_window,
            tenant_id='tenant-1',
            agent_requested_output_tokens=None,
            request_requested_output_tokens=None,
        )
        assert resolved is expected
        assert resolved.effective_input_limit_tokens == expected.effective_input_limit_tokens
        assert (
            resolved.compaction_trigger_threshold_tokens
            == expected.compaction_trigger_threshold_tokens
        )
        assert resolved.compaction_target_tokens == expected.compaction_target_tokens
        assert resolved.output_reserve_source == 'model_default'
        call_kwargs = calculator.calculate_context_budget.call_args.kwargs
        assert call_kwargs['output_reserve_source'] == 'model_default'
        assert call_kwargs['requested_output_tokens'] is None
        assert call_kwargs['request_overrides'] is None

        calculator.reset_mock()
        calculator.calculate_context_budget.return_value = _context_budget_snapshot(
            output_reserve_source='agent',
            requested_output_tokens=8192,
        )
        resolved = _resolve_context_budget(
            capacity_snapshot=capacity_with_window,
            tenant_id='tenant-1',
            agent_requested_output_tokens=8192,
            request_requested_output_tokens=16384,
        )
        assert resolved.output_reserve_source == 'agent'
        call_kwargs = calculator.calculate_context_budget.call_args.kwargs
        assert call_kwargs['output_reserve_source'] == 'agent'
        assert call_kwargs['requested_output_tokens'] == 8192
        assert isinstance(call_kwargs['request_overrides'], RequestBudgetOverrides)
        assert call_kwargs['request_overrides'].requested_output_tokens == 16384

        calculator.reset_mock()
        calculator.calculate_context_budget.side_effect = UncertaintyReserveBasisUnknown(
            'context_window_tokens missing'
        )
        with caplog.at_level(logging.WARNING):
            resolved = _resolve_context_budget(
                capacity_snapshot=_model_capacity_snapshot(context_window_tokens=None),
                tenant_id='tenant-1',
                agent_requested_output_tokens=None,
                request_requested_output_tokens=None,
            )
        assert resolved is None
        assert 'falling back to W1 input_budget' in caplog.text
