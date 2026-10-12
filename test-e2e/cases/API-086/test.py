"""D2 Remote MCP contracts using an optional controlled local MCP endpoint."""

from __future__ import annotations
from shared.resource_ids import absent_numeric_id

import os
import json
import socket
import subprocess
import tempfile
import uuid

import pytest

from shared.http import assert_status, client
from shared.http import MODEL_TIMEOUT
from shared.asset_registry import AssetDependencyError, register_asset, mark_asset_state


STAGE = pytest.mark.stage("D2")


def _field_values(value, field_name: str) -> list:
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == field_name:
                found.append(child)
            found.extend(_field_values(child, field_name))
    elif isinstance(value, list):
        for child in value:
            found.extend(_field_values(child, field_name))
    return found


def _controlled_mcp_url() -> str:
    value = os.getenv("NEXENT_TEST_MCP_URL", "").strip()
    if not value:
        pytest.skip("set NEXENT_TEST_MCP_URL to the controlled test MCP endpoint")
    return value


async def _create_record(identity, *, live: bool = False, group_id=None) -> dict:
    payload = {
        "name": f"d2-mcp-{uuid.uuid4().hex[:10]}",
        "server_url": _controlled_mcp_url() if live else "http://127.0.0.1:9/mcp",
        "description": "D2 isolated MCP",
        "source": "local",
        "tags": ["automation"],
        "enabled": False,
        "ingroup_permission": "PRIVATE",
        "group_ids": str(group_id) if group_id is not None else None,
        "shared_fields": {"server_url": False, "authorization_token": False},
        "skip_health_check": not live,
    }
    async with client("config", token=identity.access_token) as api:
        response = await api.post("/mcp/add", json=payload)
        assert_status(response, 200)
        listed = await api.get("/mcp/list")
    assert_status(listed, 200)
    for item in listed.json()["remote_mcp_server_list"]:
        if item.get("remote_mcp_server_name") == payload["name"] or item.get("name") == payload["name"]:
            item.setdefault("name", payload["name"])
            mcp_id = int(item['mcp_id'])
            register_asset('owned_mcp', str(mcp_id), mcp_id, owner_case_id='API-086', cleanup={
                'service': 'config', 'identity': identity.id, 'method': 'DELETE',
                'path': f'/mcp/{mcp_id}', 'allowed_statuses': [200, 404],
            })
            return item
    raise AssertionError(f"created MCP record {payload['name']!r} was not returned by /mcp/list")


async def _delete_record(identity, mcp_id: int) -> None:
    async with client("config", token=identity.access_token) as api:
        response = await api.delete(f"/mcp/{mcp_id}")
    assert_status(response, (200, 404))
    mark_asset_state('owned_mcp', str(mcp_id), 'DELETED')


@STAGE
@pytest.mark.case_id("API-086")
@pytest.mark.asyncio
async def test_remote_mcp_crud_visibility_and_secret_field_masking(tenant_a_admin, tenant_a_user) -> None:
    async with client('config', token=tenant_a_admin.access_token) as api:
        created_group = await api.post('/groups', json={
            'tenant_id': tenant_a_admin.tenant_id,
            'group_name': f'owned-mcp-{uuid.uuid4().hex[:10]}',
            'group_description': 'Owned private MCP visibility fixture',
        })
    assert_status(created_group, 201)
    group_id = int(created_group.json()['data']['group_id'])
    register_asset('owned_groups', str(group_id), group_id, owner_case_id='API-086', cleanup={
        'service': 'config', 'identity': tenant_a_admin.id, 'method': 'DELETE',
        'path': f'/groups/{group_id}', 'allowed_statuses': [200, 404],
    })
    mcp_id = None
    try:
        record = await _create_record(tenant_a_admin, group_id=group_id)
        mcp_id = int(record['mcp_id'])
        async with client("config", token=tenant_a_admin.access_token) as api:
            fetched = await api.get(f"/mcp/record/{mcp_id}")
            assert_status(fetched, 200)
            updated = await api.put("/mcp/update", json={
                "mcp_id": mcp_id,
                "name": record["name"],
                "description": "updated by D2",
                "server_url": "http://127.0.0.1:9/mcp",
                "tags": ["automation", "updated"],
                "ingroup_permission": "PRIVATE",
                "group_ids": str(group_id),
                "shared_fields": {"server_url": False, "authorization_token": False},
            })
            assert_status(updated, 200)
            listed = await api.get("/mcp/list")
            assert_status(listed, 200)
        # A null/empty/masked field does not expose a secret.  Only a concrete
        # token value is a leak.
        assert all(value in (None, "", "***") for value in _field_values(fetched.json(), "authorization_token"))
        async with client("config", token=tenant_a_user.access_token) as user:
            user_list = await user.get('/mcp/list')
            assert_status(user_list, 200)
            assert all(int(item['mcp_id']) != mcp_id for item in user_list.json()['remote_mcp_server_list'])
            hidden = await user.get(f"/mcp/record/{mcp_id}")
        assert hidden.status_code in {403, 404}
    finally:
        # Delete owned dependents before their group; never sweep by name prefix.
        try:
            if mcp_id is not None:
                await _delete_record(tenant_a_admin, mcp_id)
        finally:
            async with client('config', token=tenant_a_admin.access_token) as api:
                deleted_group = await api.delete(f'/groups/{group_id}')
            assert_status(deleted_group, (200, 404))
            mark_asset_state('owned_groups', str(group_id), 'DELETED')


























