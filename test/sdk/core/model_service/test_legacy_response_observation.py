# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Old diagnostic and cache consumers retain actual normalized response data."""

import pytest
from nexent.core.model_errors import ModelInvocationTerminalError
from nexent.core.model_service.contracts import TokenUsage
from nexent.core.model_service.errors import normalize_model_error
from nexent.core.model_service.http_contracts import ModelTransportError
from test_legacy_chat_model import setup as setup  # noqa: PLC0414 - Shared pytest fixture.


@pytest.mark.parametrize('suppress', [False, True])
def test_response_diagnostics_are_available_even_when_observer_is_suppressed(setup, suppress):
    model, _state, _calls, _observer = setup
    model.generate([{'role': 'user', 'content': 'hello'}], _suppress_attempt_stream=suppress)
    diagnostics = model.last_response_diagnostics
    assert diagnostics['content_char_count'] == len('answer')
    assert diagnostics['reasoning_char_count'] == len('thought')
    assert diagnostics['content_chunk_count'] == diagnostics['reasoning_chunk_count'] == 1
    assert diagnostics['input_tokens'] == 10 and diagnostics['output_tokens'] == 0
    assert diagnostics['finish_reason'] == 'stop'
    assert 'chunk_count' not in diagnostics
    assert model.last_retry_count == 1 and model.last_reasoning_preview is None


@pytest.mark.parametrize('semantics,input_tokens,cached,available', [
    ('supported', 10, 3, True),
    ('supported', 0, 0, True),
    ('unknown', 10, 3, False),
    ('unsupported', 10, 3, False),
    ('supported', None, 3, False),
    ('supported', 10, None, False),
    ('supported', 10, 11, False),
])
def test_cache_statistics_require_reported_counts_and_declared_semantics(setup, semantics, input_tokens, cached, available):
    model, state, _calls, _observer = setup
    values = model.profile.model_dump()
    values["capabilities"]["usage"]["input_includes_cached"] = semantics
    model.profile = type(model.profile).model_validate(values)
    state['usage'] = TokenUsage(input_tokens=input_tokens, cached_input_tokens=cached, origin='provider')
    model.generate([{'role': 'user', 'content': 'hello'}])
    assert model.last_cached_input_token_count == cached
    if available:
        usage = model.last_prompt_cache_usage
        assert usage.cached_input_tokens == cached
        assert usage.uncached_input_tokens == input_tokens - cached
        assert usage.provider_cache_hit == (cached > 0)
        assert usage.hit_ratio == (round(cached / input_tokens, 4) if input_tokens else 0.0)
        assert usage.estimated_saved_input_tokens == 0
    else:
        assert model.last_prompt_cache_usage is None


def test_failed_next_invocation_never_reuses_previous_response_usage_or_diagnostics(setup):
    model, state, _calls, _observer = setup
    model.generate([{'role': 'user', 'content': 'first'}])
    state['error'] = normalize_model_error(ModelTransportError('HTTP_TLS_ERROR'), request_id='failure', attempt=2, max_attempts=3)
    with pytest.raises(ModelInvocationTerminalError):
        model.generate([{'role': 'user', 'content': 'second'}])
    assert model.last_input_token_count is model.last_output_token_count is model.last_finish_reason is None
    assert model.last_prompt_cache_usage is model.last_cached_input_token_count is None
    assert model.last_response_diagnostics['content_char_count'] == 0
    assert model.last_response_diagnostics['reasoning_char_count'] == 0
