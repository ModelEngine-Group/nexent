# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""The old background RPC delegates preparation without starting a local worker."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from contracts.agentos import BackgroundRun, TrackedBackgroundResult
from contracts.errors.exceptions import RuntimeServiceTimeoutError, RuntimeServiceUnavailableError
from infrastructure.agentos_identity import ServicePrincipal
from runtime.agentos import management_dispatch
from runtime.api.agent import execution


@pytest.mark.asyncio
async def test_default_background_dispatch_keeps_actor_request_and_run_id(mocker):
    async def inline(_task, function, *args, **kwargs):
        kwargs.pop("lane", None)
        kwargs.pop("owner", None)
        return function(*args, **kwargs)

    actor = ServicePrincipal("actor", "tenant")
    payload = BackgroundRun(run_id="a" * 32, request={"query": "hello", "conversation_id": 42, "model_id": 7})
    result = TrackedBackgroundResult(run_id=payload.run_id, conversation_id=42, assistant_message_id=61, chunks=3)
    mocker.patch.object(execution, "run_blocking", side_effect=inline)
    owned = mocker.patch.object(execution, "_require_owned_conversation")
    mocker.patch.object(execution, "read_execution", return_value=None)
    local = mocker.patch.object(execution, "run_agent_stream", side_effect=AssertionError("local business preparation"))
    forward = AsyncMock(return_value=result)
    mocker.patch.object(management_dispatch, "management_client", return_value=SimpleNamespace(dispatch_background=forward))
    assert await execution.run_agentos_tracked_background(payload, actor) == result
    owned.assert_called_once_with(42, actor)
    sent, user, tenant = forward.await_args.args
    assert (user, tenant, sent.run_id, sent.request) == (actor.user_id, actor.tenant_id, payload.run_id, payload.request)
    assert sent.preparation == "management"
    local.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,status", [(RuntimeServiceTimeoutError, 504), (RuntimeServiceUnavailableError, 503)])
async def test_management_handoff_failure_cannot_start_a_local_background_worker(mocker, failure, status):
    async def inline(_task, function, *args, **kwargs):
        return function(*args)

    mocker.patch.object(execution, "run_blocking", side_effect=inline)
    mocker.patch.object(execution, "_require_owned_conversation")
    forward = mocker.patch.object(execution, "dispatch_signed_background", new=AsyncMock(side_effect=failure("unavailable")))
    local = mocker.patch.object(execution, "run_agent_stream", side_effect=AssertionError("local fallback"))
    with pytest.raises(HTTPException) as rejected:
        await execution.run_agentos_tracked_background(
            BackgroundRun(run_id="a" * 32, request={"query": "hello", "conversation_id": 42}),
            ServicePrincipal("actor", "tenant"),
        )
    assert rejected.value.status_code == status
    forward.assert_awaited_once()
    local.assert_not_called()
