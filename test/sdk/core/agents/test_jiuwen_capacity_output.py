# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Shared CM capacity must survive Jiuwen observations without changing execution policy."""

import json
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from nexent.core.agents.contracts.output import StepObservation
from nexent.core.agents.contracts.config import AgentConfig
from nexent.core.agents.contracts.run import AgentRunInfo
from nexent.core.agents.context import ContextManagerConfig
from nexent.core.agents.cores.smolagents.context import ManagedContextRuntime
from nexent.core.agents.cores.jiuwen.adapter import JiuwenAdapter
from nexent.core.agents.cores.jiuwen.context import JiuwenContextBridge
from nexent.core.concurrency import RunCancellationScope
from nexent.core.model_service.contracts import AssistantMessage, ModelError, TokenUsage
from nexent.core.utils.observer import MessageObserver
from pydantic import ValidationError


def make(mode, window=65536):
    config = ContextManagerConfig(context_window_tokens=window, token_threshold=24000,
        effective_input_limit_tokens=32000, compaction_trigger_threshold_tokens=24000,
        policy_layers={"agent": {"processing_mode": mode}})
    info = AgentRunInfo(query="Current", observer=MessageObserver(), stop_event=Event(), model_config_list=[],
        agent_config=AgentConfig(name="fixture", description="Fixture", model_name="fixture", agent_core="jiuwen", tools=[],
            context_manager_config=config))
    adapter = JiuwenAdapter(info)
    model = Mock()
    model.profile.connection.timeout_seconds = 5
    bridge = JiuwenContextBridge(info, RunCancellationScope(), Mock(), model, [])
    adapter.context_bridge = bridge
    reference = ManagedContextRuntime(bridge.context_manager)
    return adapter, info.observer, reference


@pytest.mark.parametrize("mode", ["passthrough", "adaptive_compact"])
@pytest.mark.parametrize("failed", [False, True])
def test_public_step_reuses_the_actual_nexent_cm_capacity(mode, failed):
    adapter, observer, reference = make(mode)
    adapter.events.begin_step(None)
    if failed:
        adapter.events.record_error(ModelError(category="MODEL_PROTOCOL_ERROR", scope="protocol", retryable=False,
            safe_message="Model response failed", request_id="request"))
    else:
        adapter.events.model_event(SimpleNamespace(type="message_completed", message=AssistantMessage(
            content_parts=[{"type": "text", "text": "Answer"}], finish_reason="stop",
            usage=TokenUsage(input_tokens=24, output_tokens=3, total_tokens=27, origin="provider"))))
    event = next(json.loads(e) for e in observer.get_cached_message() if json.loads(e)["type"] == "step_observation")
    assert event["context_capacity"] == {
        "context_window_tokens": reference.context_window_tokens,
        "token_threshold": reference.token_threshold,
        "effective_input_limit_tokens": reference.effective_input_limit_tokens,
        "context_processing_mode": reference.processing_mode,
    }
    assert reference.processing_mode == mode
    assert (event["step_error"] is not None) is failed
    assert reference.context_manager.compression_calls_log == []


def test_capacity_is_owned_by_each_run_not_cached_from_another_agent():
    first, first_observer, _ = make("passthrough", 65536)
    second, second_observer, _ = make("passthrough", 131072)
    for adapter in [first, second]:
        adapter.events.begin_step(None)
        adapter.events.model_event(SimpleNamespace(type="message_completed", message=AssistantMessage(finish_reason="stop")))
    values = [next(json.loads(e)["context_capacity"]["context_window_tokens"] for e in observer.get_cached_message()
                   if json.loads(e)["type"] == "step_observation") for observer in [first_observer, second_observer]]
    assert values == [65536, 131072]


def test_legacy_observation_with_no_capacity_remains_unknown():
    observation = StepObservation(turn_id="turn", block_id="block", step_number=1, duration=0)
    assert getattr(observation, "context_capacity", None) is None
    assert observation.usage.input_tokens is None


@pytest.mark.parametrize("value", [-1, 0, True, "65536"])
def test_public_capacity_rejects_invalid_or_coerced_values(value):
    with pytest.raises(ValidationError):
        StepObservation.model_validate({"turn_id": "turn", "block_id": "block", "step_number": 1, "duration": 0,
            "context_capacity": {"context_window_tokens": value}})


def test_unknown_window_and_unspecified_budget_remain_unknown_on_a_real_cm():
    adapter, observer, reference = make("passthrough", None)
    reference.context_manager.config.effective_input_limit_tokens = 0
    adapter.events.begin_step(None)
    adapter.events.model_event(SimpleNamespace(type="message_completed", message=AssistantMessage(finish_reason="stop")))
    observation = next(json.loads(e) for e in observer.get_cached_message() if json.loads(e)["type"] == "step_observation")
    assert observation["context_capacity"]["context_window_tokens"] is None
    assert observation["context_capacity"]["effective_input_limit_tokens"] is None
    assert observation["context_capacity"]["token_threshold"] == 24000
    assert observation["usage"]["input_tokens"] is None
