"""D2 agent version and repository state-machine contracts."""

from __future__ import annotations
from shared.resource_ids import absent_numeric_id

import uuid

import pytest

from shared.http import assert_status, client


STAGE = pytest.mark.stage("D2")


async def _draft(identity) -> int:
    unique = f"d2_agent_{uuid.uuid4().hex[:8]}"
    async with client("config", token=identity.access_token) as api:
        configured = await api.post("/agent/update", json={
            "name": unique,
            "display_name": unique,
            "description": "D2 isolated repository contract agent",
            "business_description": "Validate version and repository state transitions",
            "max_steps": 5,
            "provide_run_summary": False,
            "model_ids": [],
            "enabled_tool_ids": [],
            "enabled_skill_ids": [],
            "version_no": 0,
        })
    assert_status(configured, 200)
    return int(configured.json()["agent_id"])


async def _publish(identity, agent_id: int, label: str) -> int:
    async with client("config", token=identity.access_token) as api:
        response = await api.post(f"/agent/{agent_id}/publish", json={
            "version_name": label, "release_note": f"automated {label}",
        })
    assert_status(response, 200)
    return int(response.json()["version_no"])


async def _delete_agent(identity, agent_id: int) -> None:
    async with client("config", token=identity.access_token) as api:
        response = await api.request("DELETE", "/agent", json={"agent_id": agent_id})
    assert_status(response, 200)












@STAGE
@pytest.mark.case_id("API-073")
@pytest.mark.asyncio
async def test_agent_repository_rejects_missing_version_invalid_status_and_anonymous_list() -> None:
    from shared.auth import sign_in
    identity = await sign_in("tenant_a_user")
    async with client("config", token=identity.access_token) as api:
        missing = await api.post(f"/repository/agent/{absent_numeric_id(__name__)}/versions/{absent_numeric_id(__name__)}")
        invalid = await api.patch(f"/repository/agent/{absent_numeric_id(__name__)}/status", json={"status": "invented"})
    async with client("config") as anonymous:
        unauthenticated = await anonymous.get("/repository/agent")
    assert_status(missing, 400)
    assert_status(invalid, 400)
    assert_status(unauthenticated, 401)


