# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
'''D3 AGENT-IT case AGT-AUTO-01804EF17A1DF51B.

NL2Agent run switched from _resolve_safe_input_budget to
_resolve_context_budget. This test verifies ContextManagerConfig threshold
resolution and the snapshot-missing fallback inside
Runtime's AgentOS creator context builder.
'''

from __future__ import annotations

from contracts.authentication import AuthenticatedIdentity
from unittest.mock import MagicMock

import pytest

from contracts.conversation import HistoryItem
from contracts.agent import NL2AgentRunRequest
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


@pytest.mark.asyncio
@pytest.mark.case_id("AGT-AUTO-01804EF17A1DF51B")
@pytest.mark.stage("D3")
async def test_nl2agent_context_budget_resolution_and_fallback(monkeypatch):
    from contracts.agentos import PreparedAgentCreatorRun
    from infrastructure.agentos_identity import ServicePrincipal
    from nexent.core.agents.agent_model import ModelConfig
    from runtime.agentos import prepared_agent_creator as runtime

    snapshot = _make_context_budget_snapshot()
    monkeypatch.setattr(runtime, "_materialize_model", lambda *_: ModelConfig(
        cite_name="model", model_name="demo", api_key="test", url="https://provider.invalid",
    ))
    payload = PreparedAgentCreatorRun.model_validate({
        "mode": "nl2agent", "agent_id": 7, "run_id": "a" * 32, "input": {"query": "Create an Agent"},
        "bound_resources": "Verified state", "model": {"model_id": 5, "alias": "model", "revision": "v1"},
        "input_budget": 124000, "context_window_tokens": 124000, "capacity_snapshot": {"provider": "openai"},
        "context_budget_snapshot": snapshot.model_dump(mode="json"),
    })
    actor = ServicePrincipal("test-user", "tenant-a")
    info = runtime.prepare_agent_creator_run(payload, actor)
    config = info.agent_config.context_manager_config
    assert config.token_threshold == snapshot.compaction_trigger_threshold_tokens
    assert config.effective_input_limit_tokens == snapshot.effective_input_limit_tokens
    assert config.compaction_trigger_threshold_tokens == snapshot.compaction_trigger_threshold_tokens
    assert config.compaction_target_tokens == snapshot.compaction_target_tokens
    assert config.context_window_tokens == 124000
    assert info.agent_config.capacity_snapshot == {"provider": "openai"}
    assert info.agent_config.context_budget_snapshot == snapshot
    fallback = runtime.prepare_agent_creator_run(payload.model_copy(update={
        "input_budget": 32768, "context_window_tokens": 32768, "capacity_snapshot": None, "context_budget_snapshot": None,
    }), actor)
    config = fallback.agent_config.context_manager_config
    assert config.token_threshold == config.context_window_tokens == 32768
    assert config.effective_input_limit_tokens == config.compaction_trigger_threshold_tokens == config.compaction_target_tokens == 0
    assert fallback.agent_config.context_budget_snapshot is None
