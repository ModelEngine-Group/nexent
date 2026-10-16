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
@pytest.mark.case_id("API-088")
@pytest.mark.asyncio
async def test_mcp_port_check_suggest_and_no_store_cache_contract(tenant_a_admin) -> None:
    async with client("config", token=tenant_a_admin.access_token) as api:
        checked = await api.get("/mcp/port/check", params={"port": 9})
        suggested = await api.get("/mcp/port/suggest")
        invalid = await api.get("/mcp/port/check", params={"port": 70000})
        invalid_low = await api.get("/mcp/port/check", params={"port": 0})
    assert_status(checked, 200)
    assert_status(suggested, 200)
    assert_status(invalid, 422)
    assert_status(invalid_low, 422)
    assert checked.json()["status"] == "success"
    assert isinstance(checked.json()["data"]["available"], bool)
    assert suggested.json()["status"] == "success"
    suggested_port = suggested.json()["data"]["port"]
    assert isinstance(suggested_port, int) and not isinstance(suggested_port, bool)
    assert 1 <= suggested_port <= 65535
    assert "no-store" in checked.headers.get("cache-control", "").lower()
    assert checked.headers.get("pragma", "").lower() == "no-cache"
    assert checked.headers.get("expires") == "0"










