# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
from unittest.mock import call

import pytest
from starlette.responses import StreamingResponse

from contracts.agentos import BackgroundRun, CompatibilityConversationRun
from infrastructure.agentos_identity import ServicePrincipal
from runtime.api.agent import execution


@pytest.mark.asyncio
async def test_runtime_supplies_its_materializer_to_the_compatibility_stream(mocker):
    from runtime.adapters.nexent.factory import materialize_legacy_run
    from runtime.executions import agent_run_manager
    from runtime.thread_management import agent_stream_producer_tasks, channel_cleanup_tasks, runtime_thread_manager

    actor = ServicePrincipal("actor", "tenant")
    legacy_stream = mocker.patch.object(execution, "run_legacy_agent_stream", return_value=StreamingResponse(iter(())))

    response = await execution.run_agentos_conversation(CompatibilityConversationRun(
        request={"query": "run", "conversation_id": 42}, preparation="legacy", user_message="saved",
    ), actor)

    assert response is legacy_stream.return_value
    options = legacy_stream.await_args.kwargs
    assert options["legacy_materializer"] is materialize_legacy_run
    assert options["thread_manager"] is runtime_thread_manager
    assert options["execution_host"].registry is agent_run_manager
    assert options["execution_host"].producer_tasks is agent_stream_producer_tasks
    assert options["execution_host"].cleanup_tasks is channel_cleanup_tasks
    assert options["agent_request"]._track_execution
    assert options["skip_user_save"]
    assert (options["user_id"], options["tenant_id"]) == (actor.user_id, actor.tenant_id)


@pytest.mark.asyncio
async def test_compatibility_stream_requires_a_pool_before_starting_a_conversation(mocker):
    from contracts.agent import AgentRequest
    from management.services.agent import conversation_preparation, lifecycle, subscription

    mocker.patch.object(lifecycle, "get_default_thread_manager", return_value=None)
    create = mocker.patch.object(conversation_preparation, "create_new_conversation")

    with pytest.raises(RuntimeError, match="requires a thread manager"):
        await subscription.run_agent_stream(AgentRequest(query="run"), None, "actor", "tenant")

    create.assert_not_called()


@pytest.mark.asyncio
async def test_compatibility_stream_requires_runtime_state_before_conversation_writes(mocker):
    from contracts.agent import AgentRequest
    from management.services.agent import conversation_preparation, subscription

    create = mocker.patch.object(conversation_preparation, "create_new_conversation")
    with pytest.raises(RuntimeError, match="requires a Runtime host"):
        await subscription.run_agent_stream(
            AgentRequest(query="run"), None, "actor", "tenant", thread_manager=object(),
        )
    create.assert_not_called()


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
        BackgroundRun(run_id=run_id, request={"query": "run", "conversation_id": 42}, preparation="legacy"), actor,
    ))
    try:
        await asyncio.wait_for(streaming.wait(), timeout=1)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    owned.assert_called_once_with(42, actor)
    assert state.call_args_list == [
        call(run_id, "actor", "tenant", 42),
        call(run_id, "actor", "tenant", 42, request_stop=True, prevent_start=True),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation_name", ["background", "inspect", "evaluation-case"])
async def test_retired_compatibility_routes_are_absent(mocker, operation_name):
    import httpx

    from contracts.agentos import CompatibilityOperation, NAMESPACE
    from contracts.constants import environment
    from infrastructure.agentos_identity import sign_call
    from runtime.api.application import app

    mocker.patch.object(environment, "JWT_SECRET", "fixture-retired-background-key")
    lookup = mocker.patch.object(execution, "_require_owned_conversation")
    start = mocker.patch.object(execution, "run_agent_stream")
    actor = ServicePrincipal("actor", "tenant")
    path = NAMESPACE + "v1/compat/agent/" + operation_name
    body = b'{"conversation_id":42}'
    token = sign_call(CompatibilityOperation.RUN, body, actor)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://runtime") as client:
        for payload in (body, b"{}"):
            for headers in ({}, {"Authorization": f"Bearer {token}"}, {"Authorization": "Bearer invalid"}):
                response = await client.post(path, content=payload, headers=headers)
                assert response.status_code == 404
                assert response.json() == {"code": "AGENTOS_OPERATION_NOT_FOUND"}
    assert path not in {getattr(route, "path", None) for route in app.routes}
    lookup.assert_not_called()
    start.assert_not_called()
