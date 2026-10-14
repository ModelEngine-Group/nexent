from threading import Event

import pytest
from nexent.core.agents.agent_model import AgentConfig, AgentRunInfo
from nexent.core.models.capacity_budget import (
    CapacityReservePolicy,
    ContextBudgetCalculator,
)
from nexent.core.models.capacity_resolver import ModelCapacitySnapshot
from nexent.core.models.openai_llm import OpenAIModel
from nexent.core.utils.observer import MessageObserver
from pydantic import ValidationError


def _resolved_capacity() -> ModelCapacitySnapshot:
    return ModelCapacitySnapshot(
        provider="openai",
        model_name="test-model",
        context_window_tokens=16_384,
        max_input_tokens=None,
        max_output_tokens=4_096,
        default_output_reserve_tokens=2_048,
        requested_output_tokens=2_048,
        provider_input_limit_tokens=14_336,
        tokenizer_family="cl100k_base",
        counting_mode="estimated",
        unknown_capabilities=[],
        field_sources={},
        capability_profile_version="test-v1",
        fingerprint="w1-fingerprint",
    )


def test_typed_v2_snapshot_survives_runtime_models_and_dispatch_assignment():
    snapshot = ContextBudgetCalculator().calculate_context_budget(
        capacity_snapshot=_resolved_capacity(),
        reserve_policy=CapacityReservePolicy(),
    )
    agent_config = AgentConfig(
        name="test-agent",
        description="test",
        tools=[],
        model_name="main",
        context_budget_snapshot=snapshot,
    )
    run_info = AgentRunInfo(
        query="hello",
        model_config_list=[],
        observer=MessageObserver(),
        agent_config=agent_config,
        stop_event=Event(),
        context_budget_snapshot=agent_config.context_budget_snapshot,
    )
    model = OpenAIModel(
        observer=run_info.observer,
        model_id="test-model",
        api_base="http://localhost.invalid",
        api_key="test-key",
    )

    model.context_budget_snapshot = run_info.context_budget_snapshot

    assert model.context_budget_snapshot is snapshot
    assert model.context_budget_snapshot.compaction_trigger_threshold_tokens == 11_468
    assert model.context_budget_snapshot.compaction_target_tokens == 8_601


def test_monitoring_projection_fails_before_provider_dispatch():
    model = OpenAIModel(
        observer=MessageObserver(),
        model_id="test-model",
        api_base="http://localhost.invalid",
        api_key="test-key",
    )

    with pytest.raises(ValidationError):
        model.context_budget_snapshot = {
            "provider": "openai",
            "effective_input_limit_tokens": 14_336,
            "compaction_trigger_threshold_tokens": 11_468,
            "compaction_target_tokens": 8_601,
        }

    assert model.context_budget_snapshot is None
