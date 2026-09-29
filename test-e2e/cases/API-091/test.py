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


async def _create_record(identity, *, live: bool = False) -> dict:
    payload = {
        "name": f"d2-mcp-{uuid.uuid4().hex[:10]}",
        "server_url": _controlled_mcp_url() if live else "http://127.0.0.1:9/mcp",
        "description": "D2 isolated MCP",
        "source": "local",
        "tags": ["automation"],
        "enabled": False,
        "ingroup_permission": "PRIVATE",
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
            return item
    raise AssertionError(f"created MCP record {payload['name']!r} was not returned by /mcp/list")


async def _delete_record(identity, mcp_id: int) -> None:
    async with client("config", token=identity.access_token) as api:
        response = await api.delete(f"/mcp/{mcp_id}")
    assert_status(response, (200, 404))




























@STAGE
@pytest.mark.case_id("API-091")
@pytest.mark.asyncio
async def test_mcp_repository_rejects_missing_record_invalid_status_and_anonymous_mine(tenant_a_user) -> None:
    async with client("config", token=tenant_a_user.access_token) as api:
        missing = await api.post("/mcp-tools/community", json={"mcp_id": absent_numeric_id(__name__)})
        invalid = await api.patch(
            f"/mcp-tools/community/{absent_numeric_id(__name__)}/status", json={"status": "invented"}
        )
    async with client("config") as anonymous:
        unauthenticated = await anonymous.get("/mcp-tools/community/mine")
    assert_status(missing, 404)
    assert_status(invalid, (400, 404))
    assert_status(unauthenticated, 401)
