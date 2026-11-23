# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Verify Workbench debug grants follow the signed run's lifetime."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from redis.exceptions import ConnectionError

from contracts.agent import WorkbenchSessionConfig
from contracts.agentos import ToolBinding, WorkbenchDebugSkillLookup, WorkbenchSkillMounts
from infrastructure.agentos_identity import ServicePrincipal
from management.services.agent import runtime_client

RUN_ID = "a" * 32


@pytest.mark.parametrize("outcome", ["lookup-failure", "runtime-failure", "non-200", "successful", "image", "cleanup-failure"])
async def test_workbench_debug_grant_is_revoked_unless_the_browser_still_needs_images(mocker, outcome):
    async def inline(_label, fn, *args, lane, owner):
        assert (lane, owner) == ("control-io", "management")
        return fn(*args)

    mocker.patch.object(runtime_client, "run_blocking", side_effect=inline)
    open_grant = mocker.patch.object(runtime_client, "open_workbench_debug_grant")
    close_grant = mocker.patch.object(runtime_client, "close_workbench_debug_grant")
    config = WorkbenchSessionConfig(mode="generic_chat", skill_mounts=[{"skill_id": 45, "config_values": {"size": "small"}}])
    resource = SimpleNamespace(agent_id=7, version_no=2, workbench_skill_refs=[{"skill_id": 45}], tools=[])
    if outcome in {"image", "non-200"}:
        resource.tools = [ToolBinding(tool_id="ind_aidp_search", version="4")]
    payload = SimpleNamespace(run_id=RUN_ID, resource=resource)
    prepared = SimpleNamespace(payload=payload, workbench=config)
    response = SimpleNamespace(status_code=503 if outcome == "non-200" else 200)
    client = SimpleNamespace(run_ephemeral=AsyncMock(return_value=response))
    if outcome == "lookup-failure":
        open_grant.side_effect = ConnectionError
        with pytest.raises(HTTPException) as denied:
            await runtime_client._run_prepared_debug(client, prepared, "actor", "tenant")
        assert denied.value.status_code == 503
        assert denied.value.detail == {"code": "AGENTOS_WORKBENCH_SCOPE_UNAVAILABLE"}
        client.run_ephemeral.assert_not_awaited()
    elif outcome == "runtime-failure":
        client.run_ephemeral.side_effect = RuntimeError("runtime unavailable")
        with pytest.raises(RuntimeError, match="runtime unavailable"):
            await runtime_client._run_prepared_debug(client, prepared, "actor", "tenant")
    else:
        if outcome == "cleanup-failure":
            close_grant.side_effect = ConnectionError
        assert await runtime_client._run_prepared_debug(client, prepared, "actor", "tenant") is response

    open_grant.assert_called_once_with(
        WorkbenchDebugSkillLookup(run_id=RUN_ID, agent_id=7, agent_version=2), ServicePrincipal("actor", "tenant"),
        WorkbenchSkillMounts(mounts=[{"skill_id": 45, "config_values": {"size": "small"}}]),
    )
    if outcome in {"image", "lookup-failure"}:
        close_grant.assert_not_called()
    else:
        close_grant.assert_called_once_with(RUN_ID)
