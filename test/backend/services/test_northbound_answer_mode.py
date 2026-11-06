# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Northbound service mode propagation without changing run payloads."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from .test_northbound_service import MockNorthboundContext, ns


@pytest.mark.asyncio
@pytest.mark.parametrize("options,expected", [({}, "complete"),
                                           ({"final_answer_mode": "complete"}, "complete"),
                                           ({"final_answer_mode": "delta"}, "delta")])
async def test_start_chat_forwards_answer_mode_and_retains_headers(options, expected):
    response = MagicMock(status_code=200, headers={})
    with patch.object(ns, "check_and_consume_rate_limit", new_callable=AsyncMock), \
            patch.object(ns, "idempotency_start", new_callable=AsyncMock), \
            patch.object(ns, "get_conversation_history_internal", new_callable=AsyncMock) as history, \
            patch.object(ns, "forward_agent_run", new_callable=AsyncMock, return_value=response) as forward:
        history.return_value = {"data": {"history": []}}
        result = await ns.start_streaming_chat(
            ctx=MockNorthboundContext(token_id=0), conversation_id=123,
            agent_name="test_agent", query="hello", **options)
    assert result is response
    assert forward.await_args.kwargs["final_answer_mode"] == expected
    assert response.headers["conversation_id"] == "123"
    assert response.headers["X-Request-Id"]
    assert response.headers["X-Accel-Buffering"] == "no"
