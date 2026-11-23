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
@pytest.mark.case_id("API-067")
@pytest.mark.asyncio
async def test_agent_publish_snapshot_current_list_and_detail(tenant_a_user) -> None:
    agent_id = await _draft(tenant_a_user)
    try:
        version_name = f"d2-{uuid.uuid4().hex[:6]}"
        version_no = await _publish(tenant_a_user, agent_id, version_name)
        async with client("config", token=tenant_a_user.access_token) as api:
            current = await api.get(f"/agent/{agent_id}/current_version")
            listed = await api.get(f"/agent/{agent_id}/versions")
            detail = await api.get(f"/agent/{agent_id}/versions/{version_no}/detail")
        for response in (current, listed, detail):
            assert_status(response, 200)
        assert current.json()["version_no"] == version_no
        assert detail.json()["version_no"] == version_no
        assert current.json()["version_name"] == version_name
        assert detail.json()["version"]["version_name"] == version_name
        rows = listed.json()
        if isinstance(rows, dict):
            rows = rows.get("items") or []
        assert any(
            int(row["version_no"]) == version_no and row["version_name"] == version_name
            for row in rows
        )
    finally:
        await _delete_agent(tenant_a_user, agent_id)












