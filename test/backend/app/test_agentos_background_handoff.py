# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management forwards scoped background work through the prepared AgentOS path."""

from unittest.mock import AsyncMock

import pytest

from contracts.agent import AgentRequest
from contracts.agentos import AgentRunLookup, TrackedBackgroundResult
from contracts.errors.exceptions import RuntimeServiceTimeoutError, RuntimeServiceUnavailableError
from infrastructure.agentos_identity import ServicePrincipal
from management.db.automation import repository
from management.services.agent import background, runtime_client


ACTOR = ServicePrincipal("actor", "tenant")
RUN_ID = "a" * 32
REQUEST = AgentRequest(query="hello", conversation_id=42, agent_id=7, model_id=11)


@pytest.mark.asyncio
async def test_background_dispatch_keeps_actor_request_and_run_id(mocker):
    result = TrackedBackgroundResult(run_id=RUN_ID, conversation_id=42, assistant_message_id=61, chunks=3)
    dispatch = mocker.patch.object(background, "dispatch_background", return_value=result)
    transport = mocker.patch.object(runtime_client, "_agentos_client").return_value

    assert await runtime_client.forward_tracked_background(REQUEST, RUN_ID, ACTOR.user_id, ACTOR.tenant_id) == result

    dispatch.assert_awaited_once()
    request, actor = dispatch.await_args.args
    assert actor == ACTOR
    assert request.run_id == RUN_ID and request.request == REQUEST.model_dump(mode="json")
    assert transport.mock_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeServiceTimeoutError, RuntimeServiceUnavailableError])
async def test_transport_failure_checks_the_same_scope_without_redispatch(mocker, failure):
    error = failure("controlled transport failure")
    dispatch = mocker.patch.object(background, "dispatch_background", side_effect=error)
    model = mocker.patch.object(repository, "get_run_by_runtime_id", return_value=None)
    transport = mocker.patch.object(runtime_client, "_agentos_client").return_value
    transport.inspect_run = AsyncMock(return_value=None)

    with pytest.raises(failure) as caught:
        await runtime_client.forward_tracked_background(REQUEST, RUN_ID, ACTOR.user_id, ACTOR.tenant_id)

    assert caught.value is error
    dispatch.assert_awaited_once()
    model.assert_called_once_with(RUN_ID, "tenant", "actor", conversation_id=42)
    transport.inspect_run.assert_awaited_once_with(AgentRunLookup(run_id=RUN_ID, conversation_id=42), "actor", "tenant")
