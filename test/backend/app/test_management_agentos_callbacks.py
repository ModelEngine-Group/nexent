# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Verify owned automation and Memory callbacks across the signed Management routes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from contracts.agentos import AgentMemoryStored, AgentRunReference, ManagementOperation
from contracts.constants import environment
from contracts.errors.exceptions import RuntimeUpstreamError
from infrastructure.agentos_identity import ServicePrincipal, sign_call
from management.api.automation import agentos_callback as automation_route
from management.api.memory import agentos_callback as memory_route
from management.services.automation import agentos_callback as automation
from management.services.memory import agentos_callback as memory

ACTOR = ServicePrincipal("actor", "tenant")
REFERENCE = AgentRunReference(conversation_id=42, run_id="a" * 32)
NOTICE = AgentMemoryStored(conversation_id=42, agent_id=7, memory_id=61)


@pytest.fixture
async def http(mocker):
    mocker.patch.object(environment, "JWT_SECRET", "temporary-agentos-callback-test-key")
    app = FastAPI()
    app.include_router(automation_route.router)
    app.include_router(memory_route.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://management") as client:
        yield client


async def post_callback(http, operation, payload):
    body = payload.model_dump_json().encode()
    token = sign_call(operation, body, ACTOR)
    return await http.post(operation.value, content=body, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture
def automation_dependencies(mocker):
    async def inline(_task, callback, *args, **options):
        assert options == {"lane": "control-io", "owner": "management"}
        return callback(*args)

    mocker.patch.object(automation, "run_blocking", side_effect=inline)
    pending = SimpleNamespace(reference=REFERENCE, user_id=ACTOR.user_id, tenant_id=ACTOR.tenant_id, assistant_message_id=None)
    confirmed = SimpleNamespace(**{**vars(pending), "assistant_message_id": 61})
    turn_read = mocker.patch.object(automation.store, "automation_turn", return_value=pending)
    confirm = mocker.patch.object(automation.store, "confirm_turn", return_value=confirmed)
    source = mocker.patch.object(automation.store, "automation_source", return_value=None)
    inspect = AsyncMock(return_value=SimpleNamespace(
        run_id=REFERENCE.run_id, conversation_id=42, status="running", cancellation_requested=False,
    ))
    mocker.patch.object(automation, "_agentos_client", return_value=SimpleNamespace(inspect_run=inspect))
    create = mocker.patch.object(automation.agent_loop_automation_tool_adapter, "create_proposal", return_value={"id": 5})
    return SimpleNamespace(pending=pending, confirmed=confirmed, read=turn_read, confirm=confirm,
                           source=source, inspect=inspect, create=create)


@pytest.mark.parametrize("mode,status", [
    ("missing", 404), ("missing-runtime", 404), ("cancelled", 404), ("changed-scope", 404),
    ("staging-conflict", 404), ("no-context", 404), ("unavailable", 503),
])
async def test_automation_callback_never_proposes_for_an_unverified_turn(http, automation_dependencies, mode, status):
    data = automation_dependencies
    if mode == "missing":
        data.read.return_value = None
    elif mode == "missing-runtime":
        data.inspect.side_effect = RuntimeUpstreamError(404, b"", {})
    elif mode == "cancelled":
        data.inspect.return_value.cancellation_requested = True
    elif mode == "changed-scope":
        data.inspect.return_value.conversation_id = 43
    elif mode == "staging-conflict":
        data.confirm.side_effect = automation.store.PreparedTurnConflict
    elif mode == "unavailable":
        data.inspect.side_effect = RuntimeUpstreamError(503, b"", {})
    response = await post_callback(http, ManagementOperation.AUTOMATION_PROPOSAL, REFERENCE)
    assert response.status_code == status
    assert response.json()["detail"]["code"] == (
        "AGENTOS_RUN_NOT_FOUND" if status == 404 else "AGENTOS_AUTOMATION_UNAVAILABLE"
    )
    data.read.assert_called_once_with(REFERENCE, ACTOR.user_id, ACTOR.tenant_id)
    if mode in {"no-context", "staging-conflict"}:
        data.confirm.assert_called_once_with(data.pending)
    else:
        data.confirm.assert_not_called()
    if mode == "no-context":
        data.source.assert_called_once_with(data.confirmed)
    else:
        data.source.assert_not_called()
    data.create.assert_not_awaited()


@pytest.mark.parametrize("confirmed", [False, True])
async def test_automation_callback_uses_the_confirmation_bound_original_prompt(http, automation_dependencies, confirmed):
    data = automation_dependencies
    if confirmed:
        data.read.return_value = data.confirmed
    data.source.return_value = {"agent_id": 7, "source_message_id": 23, "user_message": "original instruction"}
    response = await post_callback(http, ManagementOperation.AUTOMATION_PROPOSAL, REFERENCE)
    assert (response.status_code, response.json()) == (200, {"id": 5})
    if confirmed:
        data.confirm.assert_not_called()
    else:
        data.confirm.assert_called_once_with(data.pending)
    data.source.assert_called_once_with(data.confirmed)
    context, extra = data.create.await_args.args
    assert extra == ""
    assert (context.tenant_id, context.user_id, context.conversation_id, context.agent_id) == ("tenant", "actor", 42, 7)
    assert (context.source_message_id, context.user_message) == (23, "original instruction")


@pytest.mark.parametrize("owned", [False, True])
async def test_memory_callback_only_fans_out_the_owned_record(http, mocker, owned):
    async def inline(_task, callback, *args, **options):
        return callback(*args)

    mocker.patch.object(memory, "run_blocking", side_effect=inline)
    scope = mocker.patch.object(memory, "conversation_belongs_to", return_value=True)
    record = {
        "tenant_id": ACTOR.tenant_id if owned else "other", "user_id": ACTOR.user_id,
        "agent_id": "7", "layer": "agent", "memory_type": "short_term", "status": "active",
    }
    read = mocker.patch.object(memory, "get_memory_record", return_value=record)
    fanout = mocker.patch.object(memory, "_fanout_external_ingest")

    response = await post_callback(http, ManagementOperation.MEMORY_STORED, NOTICE)

    scope.assert_called_once_with(42, user_id=ACTOR.user_id, tenant_id=ACTOR.tenant_id)
    read.assert_called_once_with(61, ACTOR.tenant_id)
    if owned:
        assert (response.status_code, response.content) == (204, b"")
        fanout.assert_awaited_once_with({**record, "conversation_id": "42"}, {"memory_id": 61})
    else:
        assert response.status_code == 404
        assert response.json()["detail"] == {"code": "MEMORY_SCOPE_NOT_FOUND"}
        fanout.assert_not_awaited()
