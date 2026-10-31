# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Public Northbound final-answer mode validation and service propagation."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.responses import StreamingResponse

from test.backend.app.test_northbound_app import client


@pytest.mark.parametrize("options,expected", [({}, "complete"),
                                                  ({"final_answer_mode": "complete"}, "complete"),
                                                  ({"final_answer_mode": "delta"}, "delta")])
def test_northbound_validates_and_forwards_answer_mode(options, expected):
    async def events():
        yield 'data: {"type":"final_answer","content":"answer"}\n\n'

    with patch("apps.northbound_app._get_northbound_context", new_callable=AsyncMock) as identity, \
            patch("apps.northbound_app.start_streaming_chat", new_callable=AsyncMock) as run:
        identity.return_value = MagicMock()
        run.return_value = StreamingResponse(events(), media_type="text/event-stream")
        response = client.post("/nb/v1/chat/run", json={"agent_name": "agent", "query": "hello", **options})
    assert response.status_code == 200
    assert run.await_args.kwargs["final_answer_mode"] == expected
    assert response.headers["content-type"].startswith("text/event-stream")


@pytest.mark.parametrize("mode", ["unknown", "", True, 1, {}, []])
def test_northbound_rejects_invalid_answer_mode_before_side_effects(mode):
    with patch("apps.northbound_app._get_northbound_context", new_callable=AsyncMock) as identity, \
            patch("apps.northbound_app.start_streaming_chat", new_callable=AsyncMock) as run:
        response = client.post("/nb/v1/chat/run", json={
            "agent_name": "agent", "query": "hello", "final_answer_mode": mode,
        })
    assert response.status_code == 422
    assert any(error["loc"] == ["body", "final_answer_mode"] for error in response.json()["detail"])
    identity.assert_not_awaited()
    run.assert_not_awaited()
