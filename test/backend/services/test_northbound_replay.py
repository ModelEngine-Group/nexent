# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Verify the Northbound replay boundary and scoped Runtime forwarding."""

from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError
from starlette.responses import StreamingResponse

from .test_northbound_service import MockNorthboundContext, ns

RUN_ID = "a" * 32
CURSOR = f"{RUN_ID}:5"


@pytest.fixture
def replay(mocker):
    context = MockNorthboundContext()
    rate_limit = mocker.patch.object(ns, "check_and_consume_rate_limit", new_callable=AsyncMock)
    forward = mocker.patch.object(ns, "forward_conversation_resume", new_callable=AsyncMock)
    start = mocker.patch.object(ns, "forward_northbound_run", new_callable=AsyncMock)
    create = mocker.patch.object(ns, "create_new_conversation", new_callable=Mock)
    yield context, rate_limit, forward
    start.assert_not_awaited()
    create.assert_not_called()


@pytest.mark.asyncio
async def test_resume_forwards_owned_cursor_and_preserves_stream_headers(replay):
    context, rate_limit, forward = replay
    response = StreamingResponse(iter(()), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
    forward.return_value = response

    assert await ns.resume_streaming_chat(context, 42, CURSOR) is response

    rate_limit.assert_awaited_once_with(context.tenant_id)
    forward.assert_awaited_once_with(
        ns.AgentResume(conversation_id=42, run_id=RUN_ID, after_event_id=CURSOR),
        context.user_id, context.tenant_id,
    )
    assert response.headers["X-Request-Id"] == context.request_id
    assert response.headers["conversation_id"] == "42"
    assert response.headers["X-Accel-Buffering"] == "no"
    assert response.headers["Cache-Control"] == "no-cache"


@pytest.mark.asyncio
@pytest.mark.parametrize(("conversation_id", "cursor", "error", "message"), [
    (None, CURSOR, ValueError, "existing conversation ID"),
    (0, CURSOR, ValueError, "existing conversation ID"),
    (42, f"{RUN_ID}:0", ValidationError, "after_event_id"),
])
async def test_resume_rejects_invalid_input_before_rate_limit_or_forwarding(
    replay, conversation_id, cursor, error, message,
):
    context, rate_limit, forward = replay
    with pytest.raises(error, match=message):
        await ns.resume_streaming_chat(context, conversation_id, cursor)

    rate_limit.assert_not_awaited()
    forward.assert_not_awaited()


@pytest.mark.asyncio
async def test_resume_does_not_forward_when_tenant_is_rate_limited(replay):
    context, rate_limit, forward = replay
    rate_limit.side_effect = ns.LimitExceededError("tenant quota exhausted")

    with pytest.raises(ns.LimitExceededError, match="tenant quota exhausted"):
        await ns.resume_streaming_chat(context, 42, CURSOR)

    rate_limit.assert_awaited_once_with(context.tenant_id)
    forward.assert_not_awaited()
