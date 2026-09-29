'''D3 AGENT-IT case AGT-AUTO-01804EF17A1DF51B.

NL2Agent run switched from _resolve_safe_input_budget to
_resolve_context_budget. This test verifies ContextManagerConfig threshold
resolution and the snapshot-missing fallback inside
services.nl2agent_service.build_nl2agent_run_info.
'''

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from consts.model import HistoryItem, NL2AgentRunRequest
from nexent.core.agents.agent_model import AgentConfig
from nexent.core.agents.context import ContextItemInput, ContextItemType
from nexent.core.models.capacity_budget import ContextBudgetSnapshot
from nexent.core.models.capacity_resolver import ModelCapacitySnapshot


def _make_capacity_snapshot(**overrides):
    values = {
        'provider': 'openai',
        'model_name': 'gpt-4o',
        'context_window_tokens': 128000,
        'max_input_tokens': 128000,
        'max_output_tokens': 16384,
        'default_output_reserve_tokens': 4096,
        'requested_output_tokens': 4096,
        'provider_input_limit_tokens': 124000,
        'counting_mode': 'exact',
        'fingerprint': 'w1-fingerprint-test',
    }
    values.update(overrides)
    return ModelCapacitySnapshot(**values)


def _make_context_budget_snapshot(**overrides):
    values = {
        'w1_fingerprint': 'w1-fingerprint-test',
        'provider': 'openai',
        'model_name': 'gpt-4o',
        'requested_output_tokens': 4096,
        'output_reserve_source': 'model_default',
        'effective_input_limit_tokens': 120000,
        'uncertainty_reserve_tokens': 0,
        'uncertainty_reserve_basis': 'none',
        'compaction_trigger_ratio': 0.8,
        'compaction_trigger_ratio_source': 'code_default',
        'compaction_trigger_threshold_tokens': 96000,
        'compaction_target_ratio': 0.6,
        'compaction_target_ratio_source': 'code_default',
        'compaction_target_tokens': 72000,
        'fingerprint': 'w2-fingerprint-test',
    }
    values.update(overrides)
    return ContextBudgetSnapshot(**values)


def _patch_dependencies(monkeypatch, *, input_budget, capacity_monitoring, resolved_capacity_snapshot, context_budget_snapshot):
    from services import nl2agent_service

    monkeypatch.setattr(nl2agent_service, 'LOCAL_MCP_SERVER', 'http://localhost:9999')
    monkeypatch.setattr(nl2agent_service, 'get_current_user_id', lambda authorization: ('test-user', 'tenant-a'))
    monkeypatch.setattr(nl2agent_service, 'build_authorized_context_input', lambda run_info: None)

    fake_tenant_config_manager = MagicMock()
    fake_tenant_config_manager.get_model_config.return_value = {'model_name': 'gpt-4o', 'model_factory': 'openai'}
    monkeypatch.setattr(nl2agent_service, 'tenant_config_manager', fake_tenant_config_manager)

    async def _fake_binding_context(*, agent_id, tenant_id, user_id):
        return ContextItemInput(
            id='system:nl2agent_bound_resources',
            type=ContextItemType.SYSTEM,
            content={'text': '{}'},
            source=('database:agent_bindings',),
            priority=85,
            metadata={'authority': 'tenant'},
        )

    monkeypatch.setattr(nl2agent_service, '_build_verified_bound_resources_context', _fake_binding_context)

    async def _fake_join_query(minio_files, query, history):
        return query

    monkeypatch.setattr(nl2agent_service, 'join_minio_file_description_to_query', _fake_join_query)

    async def _fake_model_config_list(tenant_id):
        return []

    monkeypatch.setattr(nl2agent_service, 'create_model_config_list', _fake_model_config_list)

    def _fake_agent_config(language):
        return AgentConfig(
            name='__nl2agent_runtime__',
            description='Ephemeral natural-language agent builder',
            tools=[],
            max_steps=8,
            model_name='main_model',
        )

    monkeypatch.setattr(nl2agent_service, 'create_nl2agent_agent_config', _fake_agent_config)

    monkeypatch.setattr(
        nl2agent_service,
        '_resolve_input_budget',
        lambda default_model: (input_budget, capacity_monitoring, resolved_capacity_snapshot),
    )

    resolve_context_budget = MagicMock(return_value=context_budget_snapshot)
    monkeypatch.setattr(nl2agent_service, '_resolve_context_budget', resolve_context_budget)

    return nl2agent_service, resolve_context_budget


@pytest.mark.asyncio
@pytest.mark.case_id('AGT-AUTO-01804EF17A1DF51B')
@pytest.mark.stage('D3')
async def test_nl2agent_context_budget_resolution_and_fallback(monkeypatch):
    request = NL2AgentRunRequest(
        query='create a customer support agent',
        agent_id=1001,
        history=[HistoryItem(role='user', content='hello')],
    )

    snapshot = _make_context_budget_snapshot()
    resolved_capacity = _make_capacity_snapshot()
    input_budget = 124000
    capacity_monitoring = {
        'provider': 'openai',
        'model_name': 'gpt-4o',
        'fingerprint': 'w1-fingerprint-test',
    }
    nl2agent_service, resolve_context_budget = _patch_dependencies(
        monkeypatch,
        input_budget=input_budget,
        capacity_monitoring=capacity_monitoring,
        resolved_capacity_snapshot=resolved_capacity,
        context_budget_snapshot=snapshot,
    )
    run_info = await nl2agent_service.build_nl2agent_run_info(
        request, tenant_id='tenant-a', language='en', authorization='Bearer test-token',
    )
    resolve_context_budget.assert_called_once_with(
        capacity_snapshot=resolved_capacity,
        tenant_id='tenant-a',
        agent_requested_output_tokens=None,
        request_requested_output_tokens=None,
    )
    config = run_info.agent_config.context_manager_config
    assert config.token_threshold == snapshot.compaction_trigger_threshold_tokens
    assert config.effective_input_limit_tokens == snapshot.effective_input_limit_tokens
    assert config.compaction_trigger_threshold_tokens == snapshot.compaction_trigger_threshold_tokens
    assert config.compaction_target_tokens == snapshot.compaction_target_tokens
    assert config.context_window_tokens == resolved_capacity.context_window_tokens
    assert run_info.agent_config.capacity_snapshot == capacity_monitoring
    assert run_info.agent_config.context_budget_snapshot is snapshot

    input_budget = 32768
    nl2agent_service, resolve_context_budget = _patch_dependencies(
        monkeypatch,
        input_budget=input_budget,
        capacity_monitoring={},
        resolved_capacity_snapshot=None,
        context_budget_snapshot=None,
    )
    run_info = await nl2agent_service.build_nl2agent_run_info(
        request, tenant_id='tenant-a', language='en', authorization='Bearer test-token',
    )
    config = run_info.agent_config.context_manager_config
    assert config.token_threshold == input_budget
    assert config.effective_input_limit_tokens == 0
    assert config.compaction_trigger_threshold_tokens == 0
    assert config.compaction_target_tokens == 0
    assert config.context_window_tokens == input_budget
    assert run_info.agent_config.context_budget_snapshot is None
