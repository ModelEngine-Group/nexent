# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Verify the scope and transport for Workbench Skill mount overrides."""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from contracts.agentos import ManagementOperation, WorkbenchDebugSkillLookup, WorkbenchSkillLookup, WorkbenchSkillMounts
from infrastructure.agentos_identity import ServicePrincipal, sign_call, verify_call
from management.api.agent import workbench_callback
from management.db.conversation import prepared_turn
from management.services.agent import workbench_debug_grant
from runtime.agentos import prepared_workbench

_ACTOR = ServicePrincipal("workbench-user", "workbench-tenant")
_LOOKUP = {"conversation_id": 9, "run_id": "a" * 32, "agent_id": 7, "agent_version": 2, "workbench_version": 3}
_CONFIG = {"mode": "generic_chat", "skill_mounts": [{"skill_id": 45, "config_values": {"setting": "override"}}]}


@pytest.mark.parametrize(("status", "current", "changes", "found"), [
    ("dispatching", 2, {}, True),
    ("admitted", 3, {}, True),
    ("dispatching", 3, {"new_conversation": True}, True),
    ("dispatching", 4, {}, False),
    ("admitted", 4, {}, False),
    ("admitted", 3, {"workbench_skill_root": {"agent_id": 7, "version_no": 1}}, False),
    ("closed", 3, {}, False),
])
def test_read_only_mounts_from_the_exact_open_turn(mocker, status, current, changes, found):
    session = MagicMock()
    lookup = WorkbenchSkillLookup(**_LOOKUP)
    state = {
        "workbench_skill_root": {"agent_id": 7, "version_no": 2},
        "workbench_update": {"config": _CONFIG, "version": 3, "expected_version": 2},
        **changes,
    }
    session.execute.return_value.one_or_none.return_value = SimpleNamespace(
        status=status, prepared_user_turn=state, workbench_config=_CONFIG, workbench_config_version=current,
    )
    mocker.patch.object(prepared_turn, "get_db_session", return_value=nullcontext(session))
    membership = mocker.patch.object(prepared_turn, "tenant_membership_matches", return_value=True)
    result = prepared_turn.read_workbench_skill_mounts(lookup, _ACTOR.user_id, _ACTOR.tenant_id)
    membership.assert_called_once_with(session, _ACTOR.user_id, _ACTOR.tenant_id)
    bindings = session.execute.call_args.args[0].compile().params.values()
    assert {_ACTOR.user_id, _ACTOR.tenant_id, lookup.run_id, lookup.conversation_id}.issubset(bindings)
    if found:
        assert result.model_dump() == {"mounts": _CONFIG["skill_mounts"]}
    else:
        assert result is None


def test_revoked_membership_cannot_query_workbench_state(mocker):
    session = MagicMock()
    mocker.patch.object(prepared_turn, "get_db_session", return_value=nullcontext(session))
    mocker.patch.object(prepared_turn, "tenant_membership_matches", return_value=False)
    assert prepared_turn.read_workbench_skill_mounts(
        WorkbenchSkillLookup(**_LOOKUP), _ACTOR.user_id, _ACTOR.tenant_id,
    ) is None
    session.execute.assert_not_called()


@pytest.mark.parametrize(("status", "payload", "expected"), [
    (200, {"mounts": _CONFIG["skill_mounts"]}, None),
    (404, {}, 404),
    (503, {}, 503),
    (200, {"mounts": [], "unexpected": "not a mount"}, 503),
    (200, {"mounts": _CONFIG["skill_mounts"] * 2}, 503),
])
@pytest.mark.parametrize("debug", [False, True])
def test_runtime_fetches_only_signed_scoped_mounts(mocker, status, payload, expected, debug):
    lookup = (
        WorkbenchDebugSkillLookup(run_id=_LOOKUP["run_id"], agent_id=7, agent_version=2)
        if debug else WorkbenchSkillLookup(**_LOOKUP)
    )
    mocker.patch.object(prepared_workbench.environment, "JWT_SECRET", "temporary-workbench-test-secret")
    mocker.patch.object(prepared_workbench.environment, "MANAGEMENT_AGENTOS_URL", "http://management")
    operation = (
        ManagementOperation.WORKBENCH_DEBUG_SKILL_MOUNTS if debug else ManagementOperation.WORKBENCH_SKILL_MOUNTS
    )
    connection = MagicMock()

    def post(url, *, content, headers):
        assert url == f"http://management/api{operation.value}"
        assert lookup == type(lookup).model_validate_json(content)
        assert verify_call(headers["Authorization"].removeprefix("Bearer "), operation, content) == _ACTOR
        return httpx.Response(status, json=payload, request=httpx.Request("POST", url))

    connection.post.side_effect = post
    client = mocker.patch.object(prepared_workbench.httpx, "Client", return_value=nullcontext(connection))
    if expected is None:
        assert prepared_workbench.fetch_workbench_skill_mounts(lookup, _ACTOR) == {45: {"setting": "override"}}
    else:
        with pytest.raises(HTTPException) as exc:
            prepared_workbench.fetch_workbench_skill_mounts(lookup, _ACTOR)
        assert exc.value.status_code == expected
    assert client.call_args.kwargs["follow_redirects"] is False
    connection.post.assert_called_once()


def test_debug_grant_is_bound_to_run_actor_and_root_revision(mocker):
    store = MagicMock()
    mocker.patch.object(workbench_debug_grant, "get_redis_client", return_value=store)
    session = MagicMock()
    mocker.patch.object(workbench_debug_grant, "get_db_session", return_value=nullcontext(session))
    membership = mocker.patch.object(workbench_debug_grant, "tenant_membership_matches", return_value=True)
    scope = WorkbenchDebugSkillLookup(run_id="a" * 32, agent_id=7, agent_version=2)
    mounts = WorkbenchSkillMounts(mounts=_CONFIG["skill_mounts"])

    workbench_debug_grant.open_workbench_debug_grant(scope, _ACTOR, mounts)
    key, data = store.set.call_args.args
    assert key.endswith(scope.run_id)
    assert store.set.call_args.kwargs["nx"] is True
    assert store.set.call_args.kwargs["ex"] > 0
    store.get.return_value = data
    assert workbench_debug_grant.read_workbench_debug_grant(scope, _ACTOR) == mounts
    assert workbench_debug_grant.read_workbench_debug_grant(scope, ServicePrincipal("other", _ACTOR.tenant_id)) is None
    assert workbench_debug_grant.read_workbench_debug_grant(scope, ServicePrincipal(_ACTOR.user_id, "other")) is None
    assert workbench_debug_grant.read_workbench_debug_grant(scope.model_copy(update={"agent_version": 3}), _ACTOR) is None
    membership.assert_called_once_with(session, _ACTOR.user_id, _ACTOR.tenant_id)
    membership.return_value = False
    assert workbench_debug_grant.read_workbench_debug_grant(scope, _ACTOR) is None

    workbench_debug_grant.close_workbench_debug_grant(scope.run_id)
    store.delete.assert_called_once_with(key)


@pytest.mark.asyncio
async def test_debug_mount_callback_requires_signed_lookup(mocker):
    mocker.patch.object(prepared_workbench.environment, "JWT_SECRET", "temporary-workbench-test-secret")
    scope = WorkbenchDebugSkillLookup(run_id="a" * 32, agent_id=7, agent_version=2)
    mounts = WorkbenchSkillMounts(mounts=_CONFIG["skill_mounts"])
    read = mocker.patch.object(workbench_callback, "run_blocking", return_value=mounts)
    operation = ManagementOperation.WORKBENCH_DEBUG_SKILL_MOUNTS
    body = scope.model_dump_json().encode()
    app = FastAPI()
    app.include_router(workbench_callback.router)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://management") as client:
        unsigned = await client.post(operation.value, content=body)
        assert unsigned.status_code == 401
        read.assert_not_called()
        token = sign_call(operation, body, _ACTOR)
        signed = await client.post(operation.value, content=body, headers={"Authorization": f"Bearer {token}"})

    assert signed.status_code == 200
    assert signed.headers["Cache-Control"] == "no-store"
    assert signed.json() == mounts.model_dump()
    read.assert_awaited_once_with(
        "agentos-workbench-debug-mounts", workbench_debug_grant.read_workbench_debug_grant,
        scope, _ACTOR, lane="control-io", owner="management",
    )
