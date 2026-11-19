# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Verify Runtime ownership of prepared execution and retirement of old ingress."""

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from contracts.agentos import AgentOperation, NAMESPACE
from contracts.constants import environment
from infrastructure.agentos_identity import sign_call
from runtime.agentos import prepared_run
from test.backend.app.test_agentos_prepared_run import ACTOR, payload, runtime


@pytest.mark.asyncio
async def test_runtime_uses_prepared_materializer_and_runtime_thread_manager(mocker, payload, runtime):
    thread_manager = SimpleNamespace()
    mocker.patch.object(prepared_run, "runtime_thread_manager", thread_manager)

    async def model_stream(info, *, thread_manager):
        assert info is runtime.info
        assert thread_manager is prepared_run.runtime_thread_manager
        yield '{"type":"final_answer","content":"done"}'

    mocker.patch.object(prepared_run, "agent_run", side_effect=model_stream)
    result = await prepared_run.start_prepared_run(payload, ACTOR)
    await asyncio.wait_for(asyncio.gather(*runtime.tasks), timeout=2)

    assert result.run_id == payload.run_id and result.conversation_id == payload.conversation_id
    runtime.prepare.assert_awaited_once_with(payload, ACTOR, prepared_run.prepare_run_snapshot)
    runtime.registry.register_agent_run.assert_called_once_with(payload.conversation_id, runtime.info, ACTOR.user_id)
    runtime.release.assert_called_once_with(runtime.info, payload.conversation_id, ACTOR.user_id, "completed")


@pytest.mark.asyncio
async def test_failed_worker_registration_discards_workspace_before_generation(mocker, payload, runtime):
    runtime.registry.register_agent_run.side_effect = RuntimeError("registry rejected execution")
    discard = mocker.patch.object(prepared_run, "discard_prepared_workspace")
    model_stream = mocker.patch.object(prepared_run, "agent_run")
    await prepared_run.start_prepared_run(payload, ACTOR)
    await asyncio.wait_for(asyncio.gather(*runtime.tasks), timeout=2)

    discard.assert_called_once_with(runtime.info)
    model_stream.assert_not_called()
    runtime.release.assert_not_called()
    runtime.journal.return_value.repair_terminal.assert_called_once_with("failed")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation_name", ["background", "inspect", "evaluation-case"])
async def test_retired_compatibility_routes_are_absent(mocker, operation_name):
    from runtime.api.application import app

    mocker.patch.object(environment, "JWT_SECRET", "fixture-retired-background-key")
    start = mocker.patch.object(prepared_run, "start_prepared_run")
    path = NAMESPACE + "v1/compat/agent/" + operation_name
    body = b'{"conversation_id":42}'
    token = sign_call(AgentOperation.RUN, body, ACTOR)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://runtime") as client:
        for content in (body, b"{}"):
            for headers in ({}, {"Authorization": f"Bearer {token}"}, {"Authorization": "Bearer invalid"}):
                response = await client.post(path, content=content, headers=headers)
                assert response.status_code == 404
                assert response.json() == {"code": "AGENTOS_OPERATION_NOT_FOUND"}
    assert path not in {getattr(route, "path", None) for route in app.routes}
    start.assert_not_awaited()
