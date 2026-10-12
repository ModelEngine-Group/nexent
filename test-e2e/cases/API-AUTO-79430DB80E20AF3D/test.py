"""D2 agent version and repository state-machine contracts."""

from __future__ import annotations
from shared.resource_ids import absent_numeric_id

import uuid

import pytest

from shared.http import assert_status, client
from shared.asset_registry import register_asset, mark_asset_state


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
    agent_id = int(configured.json()["agent_id"])
    register_asset('owned_agents', str(agent_id), agent_id,
                   owner_case_id='API-AUTO-79430DB80E20AF3D', cleanup={
                       'service': 'config', 'identity': identity.id, 'method': 'DELETE',
                       'path': '/agent', 'json': {'agent_id': agent_id}, 'allowed_statuses': [200, 404],
                   })
    return agent_id


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
    assert_status(response, (200, 404))
    mark_asset_state('owned_agents', str(agent_id), 'DELETED')














@STAGE
@pytest.mark.case_id("API-AUTO-79430DB80E20AF3D")
@pytest.mark.asyncio
async def test_agent_repository_detail_projects_snapshot_card_and_download_fields(tenant_a_dev) -> None:
    agent_id = await _draft(tenant_a_dev)
    try:
        version_no = await _publish(tenant_a_dev, agent_id, "repository-detail")
        async with client("config", token=tenant_a_dev.access_token) as api:
            uploaded = await api.post(f'/repository/agent/{agent_id}/versions/{version_no}/icon', files={
                'file': ('owned-icon.png', b'\x89PNG\r\n\x1a\n' + b'\x00' * 16, 'image/png'),
            })
            assert_status(uploaded, 200)
            icon_url = uploaded.json()['icon_url']
        async with client("config", token=tenant_a_dev.access_token) as api:
            created = await api.post(
                f"/repository/agent/{agent_id}/versions/{version_no}",
                json={
                    "icon_url": icon_url,
                    "tags": ["automation", "detail"],
                    "content": "D2 repository detail projection",
                },
            )
            assert_status(created, 200)
            repository_id = int(created.json()["agent_repository_id"])
            detail = await api.get(f"/repository/agent/{repository_id}")
        assert_status(detail, 200)
        payload = detail.json()
        assert payload["agent_repository_id"] == repository_id
        assert payload["agent_id"] == agent_id
        assert payload["icon_url"] == icon_url
        assert isinstance(payload["downloads"], int)
        assert payload["downloads"] >= 0
        assert "model_name" in payload
        assert "duty_prompt" in payload
        assert isinstance(payload["tools"], list)
        assert all(isinstance(tool, str) and tool for tool in payload["tools"])
    finally:
        await _delete_agent(tenant_a_dev, agent_id)
