# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Verify the scope and transport for Workbench Skill mount overrides."""

from contextlib import nullcontext
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from contracts.agentos import ManagementOperation, WorkbenchSkillLookup
from infrastructure.agentos_identity import ServicePrincipal, verify_call
from management.db.conversation import prepared_turn
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
    session = mocker.MagicMock()
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
    session = mocker.MagicMock()
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
def test_runtime_fetches_only_signed_scoped_mounts(mocker, status, payload, expected):
    lookup = WorkbenchSkillLookup(**_LOOKUP)
    mocker.patch.object(prepared_workbench.environment, "JWT_SECRET", "temporary-workbench-test-secret")
    mocker.patch.object(prepared_workbench.environment, "MANAGEMENT_AGENTOS_URL", "http://management")
    operation = ManagementOperation.WORKBENCH_SKILL_MOUNTS
    connection = mocker.MagicMock()

    def post(url, *, content, headers):
        assert url == f"http://management/api{operation.value}"
        assert lookup == WorkbenchSkillLookup.model_validate_json(content)
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
