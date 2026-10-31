# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Internal Northbound mode negotiation and native-route isolation."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.responses import StreamingResponse

from test.backend.app.test_agent_app import runtime_client


@pytest.mark.parametrize("query,expected", [("", "complete"),
                                          ("?final_answer_mode=complete", "complete"),
                                          ("?final_answer_mode=delta", "delta")])
def test_internal_northbound_forwards_answer_mode(query, expected):
    async def events():
        yield "data: done\n\n"

    with patch("runtime.api.agent.execution.verify_internal_runtime_jwt", return_value=("user", "tenant")), \
            patch("runtime.api.agent.execution.run_agent_stream", new_callable=AsyncMock) as run:
        run.return_value = StreamingResponse(events(), media_type="text/event-stream")
        response = runtime_client.post("/agent/internal/northbound/run" + query,
                                       json={"agent_id": 1, "query": "hello"})
    assert response.status_code == 200
    assert run.await_args.kwargs["final_answer_mode"] == expected
    assert run.await_args.kwargs["skip_user_save"] is True
    assert run.await_args.kwargs["user_id"] == "user"


def test_internal_northbound_rejects_invalid_mode_before_running():
    with patch("runtime.api.agent.execution.run_agent_stream", new_callable=AsyncMock) as run:
        response = runtime_client.post("/agent/internal/northbound/run?final_answer_mode=invalid",
                                       json={"agent_id": 1, "query": "hello"})
    assert response.status_code == 422
    run.assert_not_awaited()


def test_native_route_does_not_opt_in_to_complete_mode():
    async def events():
        yield "data: done\n\n"

    with patch("runtime.api.agent.execution.get_current_user_id", return_value=("user", "tenant")), \
            patch("runtime.api.agent.execution.run_agent_stream", new_callable=AsyncMock) as run:
        run.return_value = StreamingResponse(events(), media_type="text/event-stream")
        response = runtime_client.post("/agent/run", json={"agent_id": 1, "query": "hello"})
    assert response.status_code == 200
    assert "final_answer_mode" not in run.await_args.kwargs
