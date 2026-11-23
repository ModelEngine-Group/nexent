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
@pytest.mark.case_id("API-069")
@pytest.mark.asyncio
async def test_agent_version_compare_metadata_status_rollback_and_soft_delete(tenant_a_user) -> None:
    agent_id = await _draft(tenant_a_user)
    try:
        first = await _publish(tenant_a_user, agent_id, "baseline")
        second = await _publish(tenant_a_user, agent_id, "candidate")
        async with client("config", token=tenant_a_user.access_token) as api:
            compared = await api.post(f"/agent/{agent_id}/versions/compare", json={
                "version_no_a": first, "version_no_b": second,
            })
            assert_status(compared, 200)
            metadata = await api.put(f"/agent/{agent_id}/versions/{first}", json={
                "version_name": "baseline-updated", "release_note": "D2 metadata",
            })
            assert_status(metadata, 200)
            disabled = await api.patch(
                f"/agent/{agent_id}/versions/{first}/status", json={"status": "DISABLED"}
            )
            assert_status(disabled, 200)
            rolled_back = await api.post(f"/agent/{agent_id}/versions/{first}/rollback")
            assert_status(rolled_back, 200)
            deleted = await api.delete(f"/agent/{agent_id}/versions/{second}")
            assert_status(deleted, 200)
    finally:
        await _delete_agent(tenant_a_user, agent_id)








