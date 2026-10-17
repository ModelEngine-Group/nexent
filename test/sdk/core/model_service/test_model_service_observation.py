# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""One service-owned trace across actual sync/async adapter calls and retries."""

import json
from contextlib import contextmanager
from unittest.mock import Mock

import pytest
from nexent.core.model_errors import ModelErrorCode, ModelInvocationTerminalError
from nexent.core.model_service.compatibility.legacy_chat_model import LegacyChatModel
from nexent.core.model_service.http_contracts import (
    ModelTransportError,
    RawHttpResponse,
)
from nexent.core.model_service.service import ModelServiceError
from nexent.core.model_service.sse import SSEEvent
from test_model_service import Sender, frame
from test_model_service import setup as setup  # noqa: PLC0414 - Shared pytest fixture.


@pytest.fixture
def monitoring():
    manager = Mock()
    calls, active = [], []

    @contextmanager
    def trace(*args, **kwargs):
        calls.append((args, kwargs))
        active.append(True)
        try:
            yield 'span'
        finally:
            active.clear()

    manager.trace_llm_request = trace
    return manager, calls, active


@pytest.mark.asyncio
@pytest.mark.parametrize('asynchronous', [False, True])
@pytest.mark.parametrize('streaming', [False, True])
@pytest.mark.parametrize('usage', [None, {'prompt_tokens': 10}, {'prompt_tokens': 10, 'completion_tokens': 0}])
async def test_usage_unknown_partial_and_zero_remain_distinct(setup, monitoring, asynchronous, streaming, usage):
    profile, request, _limiter, factory = setup
    manager, calls, active = monitoring
    request = request.model_copy(update={'stream': streaming})
    if streaming:
        response = [frame({'content': 'answer'}), frame(finish='stop')]
        if usage is not None:
            response.append(SSEEvent(json.dumps({'choices': [], 'usage': usage})))
        response.append(SSEEvent('[DONE]'))
    else:
        response = RawHttpResponse(200, {}, json.dumps({
            'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': 'answer'}, 'finish_reason': 'stop'}],
            **({'usage': usage} if usage is not None else {}),
        }).encode())
    sender = Sender([response])
    service = factory(sender, monitoring=manager)
    if streaming:
        if asynchronous:
            async with service.astream(request, profile) as events:
                assert active
                result = [event async for event in events][-1].message
        else:
            with service.stream(request, profile) as events:
                assert active
                result = list(events)[-1].message
    else:
        result = await service.ainvoke(request, profile) if asynchronous else service.invoke(request, profile)
    assert len(calls) == 1 and not active
    assert calls[0][1]['model.request_id'] == request.request_id
    assert 'base_url' not in repr(calls) and 'credential' not in repr(calls)
    tracker = manager.create_token_tracker.return_value
    assert tracker.record_first_token.call_count == int(streaming)
    if usage is not None and 'completion_tokens' in usage:
        tracker.record_completion.assert_called_once_with(10, 0, total_tokens=None)
    else:
        tracker.record_completion.assert_not_called()
    tracker.record_token.assert_not_called()
    assert result.usage.total_tokens is None
    manager.set_openinference_output.assert_called_once_with('answer')


def test_retry_and_early_close_share_trace_and_release_observation(setup, monitoring):
    profile, request, limiter, factory = setup
    manager, calls, active = monitoring
    request = request.model_copy(update={'stream': True})
    sender = Sender([ModelTransportError('HTTP_NETWORK_ERROR'), [frame({'content': 'partial'})]])
    service = factory(sender, monitoring=manager)
    with service.stream(request, profile) as events:
        assert next(events).delta == 'partial' and active
    assert len(calls) == 1 and not active and not limiter._entries
    begins = [call.args for call in manager.add_span_event.call_args_list if call.args[0] == 'model_attempt_begin']
    assert [args[1]['attempt'] for args in begins] == [1, 2]
    manager.create_token_tracker.return_value.record_completion.assert_not_called()
    assert sender.closed == 2


def test_terminal_error_closes_trace_without_provider_detail(setup, monitoring):
    profile, request, _limiter, factory = setup
    manager, calls, active = monitoring
    sender = Sender([ModelTransportError('HTTP_TLS_ERROR')])
    with pytest.raises(ModelServiceError):
        factory(sender, monitoring=manager).invoke(request, profile)
    assert len(calls) == 1 and not active
    manager.create_token_tracker.return_value.record_completion.assert_not_called()
    assert manager.add_span_event.call_args.args[1]['category'] == 'MODEL_TLS_ERROR'


def test_empty_length_retains_usage_event_and_legacy_diagnostics(setup, monitoring):
    profile, _request, limiter, factory = setup
    manager, _calls, active = monitoring
    sender = Sender([[
        frame({'reasoning_content': 'thought'}), frame(finish='length'),
        SSEEvent(json.dumps({'choices': [], 'usage': {'prompt_tokens': 10, 'completion_tokens': 20}})),
        SSEEvent('[DONE]'),
    ]])
    model = LegacyChatModel(profile, factory(sender, monitoring=manager))
    with pytest.raises(ModelInvocationTerminalError) as caught:
        model.generate([{'role': 'user', 'content': 'hello'}])
    assert caught.value.error_code == ModelErrorCode.EMPTY_RESPONSE_EXHAUSTED
    assert model.last_finish_reason == 'length'
    diagnostics = model.last_response_diagnostics
    assert diagnostics['reasoning_only_budget_exhausted']
    assert diagnostics['reasoning_char_count'] == len('thought')
    assert diagnostics['input_tokens'] == 10 and diagnostics['output_tokens'] == 20
    assert len(sender.calls) == 1 and not limiter._entries and not active
    usages = [call.args[1] for call in manager.add_span_event.call_args_list if call.args[0] == 'model_usage']
    assert usages[0]['input_tokens'] == 10 and usages[0]['attempt'] == 1
    manager.create_token_tracker.return_value.record_completion.assert_not_called()
