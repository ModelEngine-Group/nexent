# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Service event semantics must not treat tool identities or empty text as tokens."""

from unittest.mock import Mock

import pytest
from nexent.core.model_service.sse import SSEEvent
from test_model_service import Sender, frame
from test_model_service import setup as setup  # noqa: PLC0414 - Shared pytest fixture.


@pytest.mark.asyncio
@pytest.mark.parametrize('asynchronous', [False, True])
@pytest.mark.parametrize('delta,basis', [
    ({'content': 'answer'}, 'content'),
    ({'reasoning_content': 'thought'}, 'reasoning'),
    ({'tool_calls': [{'index': 0, 'function': {'arguments': '{}'}}]}, 'tool_delta'),
])
async def test_service_first_nonempty_delta(setup, asynchronous, delta, basis):
    profile, request, _limiter, factory = setup
    manager = Mock()
    from contextlib import nullcontext

    manager.trace_llm_request = lambda *a, **kw: nullcontext('span')
    sender = Sender([[
        frame({'role': 'assistant'}), frame({'content': ''}),
        frame({'tool_calls': [{'index': 0, 'id': 'call', 'function': {'name': 'f', 'arguments': ''}}]}),
        frame(delta), frame({'content': 'final'}), frame(finish='tool_calls'), SSEEvent('[DONE]'),
    ]])
    service = factory(sender, monitoring=manager)
    request = request.model_copy(update={'stream': True})
    if asynchronous:
        async with service.astream(request, profile) as stream:
            events = [event async for event in stream]
    else:
        with service.stream(request, profile) as stream:
            events = list(stream)
    assert events[-1].type == 'message_completed'
    assert events[-1].message.content_parts[-1]['text'].endswith('final')
    manager.create_token_tracker.return_value.record_first_token.assert_called_once_with(basis=basis)
    assert len(sender.calls) == 1 and sender.closed == 1
