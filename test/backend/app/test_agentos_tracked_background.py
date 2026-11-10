# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio

import pytest
from starlette.responses import StreamingResponse

from contracts.agentos import BackgroundRun
from infrastructure.agentos_identity import ServicePrincipal
from runtime.api.agent import execution


@pytest.mark.asyncio
async def test_background_disconnect_requests_stop_for_the_dispatched_run(mocker):
    run_id = "c" * 32
    actor = ServicePrincipal("actor", "tenant")
    streaming = asyncio.Event()
    state = mocker.patch.object(execution, "read_execution", side_effect=[None, {"status": "running"}])
    owned = mocker.patch.object(execution, "_require_owned_conversation")

    async def direct(_name, function, *args, **kwargs):
        kwargs.pop("lane", None)
        kwargs.pop("owner", None)
        return function(*args, **kwargs)

    async def stream(agent_request, **kwargs):
        assert agent_request._projection_run_id == run_id
        assert kwargs["skip_user_save"]

        async def chunks():
            streaming.set()
            await asyncio.Future()
            yield "unreachable"

        return StreamingResponse(chunks())

    mocker.patch.object(execution, "run_blocking", direct)
    mocker.patch.object(execution, "run_agent_stream", stream)
    task = asyncio.create_task(execution.run_agentos_tracked_background(
        BackgroundRun(run_id=run_id, request={"query": "run", "conversation_id": 42}), actor,
    ))
    try:
        await asyncio.wait_for(streaming.wait(), timeout=1)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    owned.assert_called_once_with(42, actor)
    assert state.call_args_list == [
        mocker.call(run_id, "actor", "tenant", 42),
        mocker.call(run_id, "actor", "tenant", 42, request_stop=True, prevent_start=True),
    ]
