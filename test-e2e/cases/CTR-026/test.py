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
@pytest.mark.case_id("CTR-026")
@pytest.mark.asyncio
async def test_mcp_container_upload_stream_emits_started_and_terminal_events(tenant_a_admin) -> None:
    async with client("config", token=tenant_a_admin.access_token) as api:
        schema = await api.get("/openapi.json")
    assert_status(schema, 200)
    if "/mcp/upload-image/stream" not in schema.json().get("paths", {}):
        raise AssetDependencyError("mcp", "upload_image_route", detail="ENABLE_UPLOAD_IMAGE is disabled on this deployment")
    image_tag = os.getenv("NEXENT_TEST_MCP_IMAGE_TAG", "nexent/nexent-mcp:v2.6.0").strip()
    service_name = f"d2-upload-{uuid.uuid4().hex[:12]}"
    inspected = subprocess.run(
        ["docker", "image", "inspect", image_tag], capture_output=True, timeout=60,
    )
    if inspected.returncode:
        raise AssetDependencyError("mcp", "image_upload", detail=f"local Docker image is unavailable: {image_tag}")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])

    container_id = None
    with tempfile.TemporaryDirectory(prefix="nexent-mcp-upload-") as directory:
        archive = os.path.join(directory, service_name + ".tar")
        saved = subprocess.run(
            ["docker", "save", "--output", archive, image_tag],
            capture_output=True, timeout=180,
        )
        if saved.returncode:
            raise AssetDependencyError("mcp", "image_upload", detail="docker save failed for the owned test archive")
        try:
            with open(archive, "rb") as stream:
                files = {"file": (service_name + ".tar", stream, "application/x-tar")}
                data = {"service_name": service_name, "port": str(port), "env_vars": "{}"}
                async with client("config", token=tenant_a_admin.access_token, timeout=MODEL_TIMEOUT) as api:
                    response = await api.post("/mcp/upload-image/stream", files=files, data=data)
            assert_status(response, 200)
            events = []
            for line in response.text.splitlines():
                if line.startswith("data:"):
                    events.append(json.loads(line[5:].strip()))
            statuses = [event.get("status") for event in events]
            started = next((event for event in events if event.get("status") == "container_started"), None)
            assert started and ("success" in statuses or "error" in statuses), statuses
            container_id = str((started.get("data") or {}).get("container_id") or "")
            assert container_id, "container_started must carry the owned container ID"
            register_asset(
                "owned_mcp_containers", container_id, container_id, owner_case_id="CTR-026",
                cleanup={"service": "config", "identity": tenant_a_admin.id, "method": "DELETE",
                         "path": f"/mcp/container/{container_id}", "allowed_statuses": [200, 404]},
            )
            if "success" in statuses:
                success = next(event for event in events if event.get("status") == "success")
                assert (success.get("data") or {}).get("service_name") == service_name
        finally:
            if container_id:
                async with client("config", token=tenant_a_admin.access_token, timeout=MODEL_TIMEOUT) as api:
                    deleted = await api.delete(f"/mcp/container/{container_id}")
                assert_status(deleted, (200, 404))
                mark_asset_state("owned_mcp_containers", container_id, "DELETED")








