# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Provider observations inform advisory context estimates without admission gates."""

from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest
from nexent.core.agents.context import ContextManager, ContextManagerConfig
from nexent.core.models.context_usage import (
    InputUsageObservation,
    context_model_key,
    request_characters,
)


def test_request_measurement_includes_tool_arguments_results_and_schema():
    messages = [{'role': 'user', 'content': 'hello'}]
    size = request_characters(messages, [])
    assert request_characters(messages + [{'role': 'tool', 'tool_call_id': 'call-1', 'content': 'result' * 80}], []) > size
    assert request_characters(messages, [{'type': 'function', 'function': {'name': 'read', 'description': 'x' * 500}}]) > size
    assert request_characters([{'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'call-1', 'function': {'arguments': 'x' * 500}}]}], []) > size


@pytest.mark.parametrize('tokens,origin', [(None, 'provider'), (10, 'estimated'), (-1, 'provider'), (True, 'provider')])
def test_invalid_usage_cannot_be_a_provider_anchor(tokens, origin):
    assert InputUsageObservation.capture(
        usage=SimpleNamespace(input_tokens=tokens, origin=origin), messages=[], tools=[],
        model_key='model', request_id='request', attempt=1,
    ) is None


def test_observation_is_immutable_and_calibration_accounts_for_new_payload():
    messages = [{'role': 'user', 'content': 'x' * 2000}]
    model = SimpleNamespace(model_id='model')
    observation = InputUsageObservation.capture(
        usage=SimpleNamespace(input_tokens=100, origin='provider'), messages=messages, tools=[],
        model_key=context_model_key(model), request_id='request', attempt=1,
    )
    with pytest.raises(FrozenInstanceError):
        observation.input_tokens = 5
    manager = ContextManager(ContextManagerConfig(chars_per_token=2))
    manager._observe_model_usage(model)
    model.last_context_observation = observation
    manager._observe_model_usage(model)
    assert manager._estimate_request(messages, []) == 100
    assert manager._estimate_request(messages + [{'role': 'tool', 'content': 'y' * 1000}], []) >= 600
    assert manager._estimate_request(messages, [{'description': 'z' * 1000}]) >= 600
    assert manager._estimate_request([{'role': 'user', 'content': 'short'}], []) < 100
    assert manager._estimate_basis == 'provider_calibrated_estimate'


def test_switching_model_discards_previous_usage_anchor():
    messages = [{'role': 'user', 'content': 'x' * 2000}]
    model = SimpleNamespace(model_id='first')
    manager = ContextManager(ContextManagerConfig(chars_per_token=2))
    manager._observe_model_usage(model)
    model.last_context_observation = InputUsageObservation.capture(
        usage=SimpleNamespace(input_tokens=100, origin='provider'), messages=messages, tools=[],
        model_key=context_model_key(model), request_id='request', attempt=1,
    )
    manager._observe_model_usage(model)
    assert manager._estimate_request(messages, []) == 100
    model.model_id = 'second'
    manager._observe_model_usage(model)
    assert manager._estimate_request(messages, []) >= 1000
    assert manager._estimate_basis == 'local_estimate'


@pytest.mark.parametrize('ratio', [0, -1, float('nan'), float('inf')])
def test_invalid_estimation_ratio_remains_advisory(ratio):
    manager = ContextManager(ContextManagerConfig(chars_per_token=ratio))
    assert manager._estimate_request([{'role': 'user', 'content': 'hello'}], []) >= 0
    from nexent.core.agents.context.runtime import ManagedContextRuntime
    assert ManagedContextRuntime(manager).chars_per_token > 0
    observation = InputUsageObservation(100, 50, 'model', 'request', 1)
    assert observation.estimate(input_characters=100, chars_per_token=ratio) > 100


def test_zero_provider_input_is_known_and_cached_tokens_are_not_added():
    observation = InputUsageObservation.capture(
        usage=SimpleNamespace(input_tokens=0, cached_input_tokens=100, origin='provider'),
        messages=[], tools=[], model_key='model', request_id='zero', attempt=1,
    )
    assert observation.input_tokens == 0
    assert observation.estimate(input_characters=observation.input_characters, chars_per_token=1.5) == 0


def test_preexisting_response_from_another_run_is_not_used():
    messages = [{'role': 'user', 'content': 'x' * 2000}]
    model = SimpleNamespace(model_id='shared')
    model.last_context_observation = InputUsageObservation.capture(
        usage=SimpleNamespace(input_tokens=1, origin='provider'), messages=messages, tools=[],
        model_key=context_model_key(model), request_id='other-conversation', attempt=1,
    )
    manager = ContextManager(ContextManagerConfig(chars_per_token=2))
    manager._observe_model_usage(model)
    assert manager._estimate_request(messages, []) == 1000
    assert manager._estimate_basis == 'local_estimate'
