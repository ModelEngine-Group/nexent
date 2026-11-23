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
@pytest.mark.case_id("API-072")
@pytest.mark.asyncio
async def test_agent_repository_listing_create_read_submit_and_withdraw(tenant_a_dev) -> None:
    # Repository publishing is allowed to ADMIN, or to the DEV who owns the
    # agent. Ordinary USER is intentionally forbidden by the service.
    agent_id = await _draft(tenant_a_dev)
    try:
        version_no = await _publish(tenant_a_dev, agent_id, "repository")
        async with client("config", token=tenant_a_dev.access_token) as api:
            created = await api.post(f"/repository/agent/{agent_id}/versions/{version_no}", json={
                "icon": "automation-agent",
                "tags": ["automation", "d2"],
                "content": f"D2 listing {uuid.uuid4().hex[:6]}",
            })
            assert_status(created, 200)
            repository_id = int(created.json()["agent_repository_id"])
            detail = await api.get(f"/repository/agent/{repository_id}")
            assert_status(detail, 200)
            submitted = await api.patch(
                f"/repository/agent/{repository_id}/status", json={"status": "pending_review"}
            )
            assert_status(submitted, 200)
            withdrawn = await api.patch(
                f"/repository/agent/{repository_id}/status", json={"status": "not_shared"}
            )
            assert_status(withdrawn, 200)
    finally:
        await _delete_agent(tenant_a_dev, agent_id)




