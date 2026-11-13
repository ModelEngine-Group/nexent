# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Verify the signed, revocable NL2Agent tool callback boundary."""

from contextlib import nullcontext

import httpx
import pytest
from fastapi import FastAPI

from contracts.agentos import ManagementOperation, NL2AgentToolCall
from contracts.constants import environment
from infrastructure.agentos_identity import ServicePrincipal, sign_call
from management.api.agent import nl2agent_callback as api
from management.services.agent import nl2agent_callback as service
from management.services.agent import nl2agent
from management.services.agent import nl2agent_tools as tools

_ACTOR = ServicePrincipal("user-a", "tenant-a")
_RUN_ID = "a" * 32
_OPERATION = ManagementOperation.NL2AGENT_TOOL


class _Redis:
    def __init__(self):
        self.entries = {}

    def set(self, key, value, *, ex, nx):
        assert ex > 0 and nx
        if key in self.entries:
            return None
        self.entries[key] = value
        return True

    def get(self, key):
        return self.entries.get(key)

    def delete(self, key):
        return self.entries.pop(key, None) is not None


@pytest.fixture
def grants(mocker):
    redis = _Redis()
    mocker.patch.object(service, "get_redis_client", return_value=redis)
    mocker.patch.object(service, "get_db_session", return_value=nullcontext(object()))
    membership = mocker.patch.object(service, "tenant_membership_matches", return_value=True)
    mocker.patch.object(environment, "JWT_SECRET", "fixture-nl2agent-agentos-key")
    service.open_nl2agent_tool_grant(_RUN_ID, 7, _ACTOR, False)
    return membership


@pytest.mark.asyncio
async def test_signed_scope_rejects_unowned_closed_or_tampered_grants(grants, mocker):
    perform = mocker.patch.object(tools, "search_installed_resources", return_value={"status": "success"})
    app = FastAPI()
    app.include_router(api.router)

    async def inline(_name, function, *args, **kwargs):
        return function(*args)

    mocker.patch.object(service, "run_blocking", side_effect=inline)
    call = NL2AgentToolCall(run_id=_RUN_ID, agent_id=7, tool="search_installed_resources", arguments={"requirements": []})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://management") as client:
        async def send(payload=call, principal=_ACTOR, *, signature=True, raw=None):
            body = payload.model_dump_json().encode()
            headers = {"Authorization": "Bearer " + sign_call(_OPERATION, body, principal)} if signature else {}
            return await client.post(_OPERATION.value, content=raw if raw is not None else body, headers=headers)

        assert (await send(signature=False)).status_code == 401
        assert (await send(raw=b"{}")).status_code == 401
        assert (await send(principal=ServicePrincipal("other-user", _ACTOR.tenant_id))).status_code == 404
        assert (await send(principal=ServicePrincipal(_ACTOR.user_id, "other-tenant"))).status_code == 404
        assert (await send(call.model_copy(update={"agent_id": 8}))).status_code == 404
        assert (await send(call.model_copy(update={"arguments": {"requirements": [], "tenant_id": "other"}}))).status_code == 422
        perform.assert_not_called()
        grants.return_value = False
        assert (await send()).status_code == 404
        perform.assert_not_called()
        grants.return_value = True
        assert (await send()).json() == {"status": "success"}
        perform.assert_awaited_once_with(agent_id=7, requirements=[])
        service.close_nl2agent_tool_grant(_RUN_ID)
        assert (await send()).status_code == 404
        perform.assert_awaited_once()


@pytest.mark.asyncio
async def test_draft_tool_uses_grant_actor_and_preserves_policy_guard(grants, mocker):
    async def inline(_name, function, *args, **kwargs):
        return function(*args)

    mocker.patch.object(service, "run_blocking", side_effect=inline)
    mocker.patch.object(tools, "get_http_request", side_effect=AssertionError("public user token is not used"))
    save = mocker.patch.object(nl2agent, "save_agent_draft_fields_impl", return_value={
        "status": "success", "agent_id": 7, "created": False, "updated_fields": ["description"],
    })
    call = NL2AgentToolCall(
        run_id=_RUN_ID, agent_id=7, tool="save_agent_draft_fields", arguments={"fields": {"description": "updated"}},
    )
    assert '"status":"success"' in await service.execute_nl2agent_tool(call, _ACTOR)
    assert save.call_args.kwargs["tenant_id"] == _ACTOR.tenant_id
    assert save.call_args.kwargs["user_id"] == _ACTOR.user_id
    save.reset_mock()

    other = "b" * 32
    service.open_nl2agent_tool_grant(other, 7, _ACTOR, True)
    blocked = await service.execute_nl2agent_tool(call.model_copy(update={
        "run_id": other, "arguments": {"fields": {"enable_protocol_repair_retry": True}},
    }), _ACTOR)
    assert '"code":"policy_clarification_required"' in blocked
    save.assert_not_called()
