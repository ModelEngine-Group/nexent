# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read-only deployed-source, sandbox-event and trace observations."""

import asyncio
import hashlib
import json
import subprocess
import time
from datetime import datetime, timedelta, timezone

import httpx

from shared.asset_registry import AssetDependencyError
from shared.config import load_secret_env, repo_root


SOURCES = ("core/agents/nexent_agent.py", "core/agents/tool_fastpath.py", "core/agents/sandbox.py")


def docker_command(*arguments):
    try:
        result = subprocess.run(["docker", *arguments], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise AssetDependencyError(
            "deployment", "tfp_docker", detail="Read-only Docker observation unavailable"
        ) from error
    if result.returncode:
        raise AssetDependencyError("deployment", "tfp_docker", detail="Read-only Docker operation failed")
    return result.stdout


def verify_deployment(cfg):
    record = json.loads(docker_command("inspect", cfg["runtime_container"]))[0]
    assert record["State"]["Running"], "The declared disposable runtime must be running"
    deployed = dict(value.split("=", 1) for value in record["Config"].get("Env", []) if "=" in value)
    assert deployed.get("NEXENT_SANDBOX_DEFAULT_LEVEL") == "docker"
    assert deployed.get("NEXENT_SANDBOX_DEFAULT_SCOPE") == "session"
    assert deployed.get("NEXENT_SANDBOX_WORKSPACE_MODE") == "bind"
    assert deployed.get("NEXENT_TOOL_FASTPATH_ENABLED", "true").lower() == "true"
    if "NEXENT_TOOL_FASTPATH_ALLOWED_TOOLS" in deployed:
        assert "ReadSkillConfigTool" in deployed["NEXENT_TOOL_FASTPATH_ALLOWED_TOOLS"].split(",")
    script = (
        "import hashlib,json; from pathlib import Path; import nexent; "
        "from consts.const import AGENT_WORKSPACE_ROOT,NEXENT_SANDBOX_CONTAINER_WORKSPACE_ROOT; "
        "from nexent.core.agents.sandbox_workspace import SandboxWorkspace; "
        "root=Path(nexent.__file__).parent; "
        f"sources={{p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in {SOURCES!r}}}; "
        "mapping=SandboxWorkspace(Path(AGENT_WORKSPACE_ROOT),NEXENT_SANDBOX_CONTAINER_WORKSPACE_ROOT); "
        "print(json.dumps({'sources':sources,'mount_id':mapping.mount_id}))"
    )
    observed = json.loads(
        docker_command("exec", cfg["runtime_container"], "/opt/backend/.venv/bin/python", "-c", script)
    )
    expected = {path: hashlib.sha256((repo_root() / "sdk/nexent" / path).read_bytes()).hexdigest() for path in SOURCES}
    assert observed["sources"] == expected, "The running SDK differs from the worktree under test"
    assert observed["mount_id"] == cfg["workspace_mount_id"], "Docker observation scope differs from runtime mapping"
    filters = (
        "--filter",
        "label=com.nexent.sandbox=session",
        "--filter",
        "label=com.nexent.workspace=" + cfg["workspace_mount_id"],
    )
    assert not docker_command("ps", *filters, "--format", "{{.ID}}").strip(), "Fixture sandbox scope must be idle"
    return expected


def sandbox_events(cfg, started):
    ended = time.time()
    raw = docker_command(
        "events",
        "--since",
        str(started),
        "--until",
        str(ended),
        "--filter",
        "type=container",
        "--filter",
        "label=com.nexent.sandbox=session",
        "--filter",
        "label=com.nexent.workspace=" + cfg["workspace_mount_id"],
        "--format",
        "{{json .}}",
    )
    records = [json.loads(line) for line in raw.splitlines() if line.strip()]
    for record in records:
        assert record["Actor"]["Attributes"].get("com.nexent.workspace") == cfg["workspace_mount_id"]
    return [
        {"action": record.get("Action", record.get("status")), "id": record["Actor"]["ID"]}
        for record in records
        if record.get("Action", record.get("status")) in {"create", "destroy"}
    ]


def verify_sandbox_events(records, promoted):
    created = [record["id"] for record in records if record["action"] == "create"]
    destroyed = [record["id"] for record in records if record["action"] == "destroy"]
    assert len(created) == int(promoted), "Unexpected sandbox activation count"
    assert len(set(created)) == len(created), "A sandbox acquisition was duplicated"
    assert sorted(created) == sorted(destroyed), "An owned session sandbox was not reclaimed"


async def trace_observations(cfg, conversation_id, final_marker, *, expected_warmups=None):
    settings, credentials = trace_credentials(cfg)
    if settings.get("api_version", "v1") == "v2":
        return await trace_observations_v2(settings, credentials, conversation_id, final_marker,
                                         expected_warmups=expected_warmups)
    deadline = time.monotonic() + 60
    async with httpx.AsyncClient(
        base_url=settings["url"].rstrip("/"), auth=credentials, timeout=15, trust_env=False
    ) as api:
        while time.monotonic() < deadline:
            response = await api.get("/api/public/traces", params={"sessionId": str(conversation_id), "limit": 100})
            assert response.status_code == 200, "Langfuse trace query failed"
            body = response.json()
            rows = complete_page(body)
            assert all(str(row.get("sessionId")) == str(conversation_id) for row in rows)
            completed = [row for row in rows if output_contains(row.get("output"), final_marker)]
            if completed:
                observations = []
                for row in rows:
                    response = await api.get("/api/public/observations", params={"traceId": row["id"], "limit": 100})
                    assert response.status_code == 200, "Langfuse observation query failed"
                    body = response.json()
                    page = complete_page(body)
                    assert all(item.get("traceId") == row["id"] for item in page)
                    observations.extend(page)
                assert observations, "Empty telemetry cannot prove absence of warm-up"
                return observations
            await asyncio.sleep(0.5)
    raise AssertionError("Completed Agent trace was not exported before the deadline")


async def observation_pages(api, params):
    """Read every cursor page; incomplete or cyclic pagination cannot prove absence."""
    rows, cursors, ids = [], set(), set()
    params = dict(params, limit=100, fields="core,basic,io,metadata")
    for _ in range(100):
        response = await api.get("/api/public/v2/observations", params=params)
        assert response.status_code == 200, "Langfuse observation query failed"
        body = response.json()
        page = body.get("data")
        assert isinstance(page, list) and isinstance(body.get("meta"), dict), "Invalid observation page"
        for item in page:
            assert item.get("id") and item["id"] not in ids, "Duplicate observation across cursor pages"
            ids.add(item["id"])
            rows.append(item)
        cursor = body["meta"].get("cursor")
        if not cursor:
            return rows
        assert cursor not in cursors, "Observation pagination cursor repeated"
        cursors.add(cursor)
        params["cursor"] = cursor
    raise AssertionError("Observation pagination exceeded the bounded fixture limit")


def output_contains(output, marker):
    """Compare text before JSON escaping so multiline artifact answers match."""
    if isinstance(output, str):
        return marker in output
    if isinstance(output, dict):
        return any(output_contains(value, marker) for value in output.values())
    if isinstance(output, list):
        return any(output_contains(value, marker) for value in output)
    return False


async def trace_observations_v2(settings, credentials, conversation_id, final_marker, *, expected_warmups=None):
    since = datetime.now(timezone.utc) - timedelta(minutes=15)
    deadline = time.monotonic() + 60
    async with httpx.AsyncClient(
        base_url=settings["url"].rstrip("/"), auth=credentials, timeout=15, trust_env=False
    ) as api:
        while time.monotonic() < deadline:
            window = {"fromStartTime": since.isoformat(), "toStartTime": datetime.now(timezone.utc).isoformat()}
            rows = await observation_pages(api, dict(window, sessionId=str(conversation_id)))
            assert all(str(row.get("sessionId")) == str(conversation_id) for row in rows)
            completed = [row for row in rows if row.get("name") == "agent.run" and row.get("endTime")
                         and output_contains(row.get("output"), final_marker)]
            if completed:
                observations = []
                for trace_id in sorted({row["traceId"] for row in completed}):
                    page = await observation_pages(api, dict(window, traceId=trace_id))
                    assert all(row.get("traceId") == trace_id for row in page)
                    # The HTTP root has no session ID. Fetch the whole trace and
                    # wait for its completed root before counting warm-ups.
                    roots = [row for row in page if not row.get("parentObservationId") and row.get("endTime")]
                    if not roots:
                        break
                    observations.extend(page)
                else:
                    assert observations, "Empty telemetry cannot prove absence of warm-up"
                    warmups = [row for row in observations if row.get("name") == "agent.sandbox.warmup"]
                    # Cloud indexes spans independently; a completed root can
                    # become visible before its children. Never accept a missing
                    # expected span, or suppress extra spans, at this boundary.
                    if expected_warmups is None or len(warmups) >= expected_warmups:
                        return observations
            await asyncio.sleep(1)
    raise AssertionError("Completed Agent observations were not exported before the deadline")


def complete_page(body):
    rows = body.get("data")
    total = body.get("meta", {}).get("totalItems")
    assert isinstance(rows, list) and type(total) is int and total == len(rows) and total <= 100, (
        "Trace pagination is incomplete"
    )
    return rows


def trace_credentials(cfg):
    settings = cfg["langfuse"]
    try:
        secrets = load_secret_env()
    except FileNotFoundError as error:
        raise AssetDependencyError("monitoring", "tfp_langfuse", detail="Private trace key file is missing") from error
    public = secrets.get(settings["public_key_env"])
    private = secrets.get(settings["secret_key_env"])
    if not public or not private:
        raise AssetDependencyError("monitoring", "tfp_langfuse", detail="Read-only trace credentials are required")
    return settings, (public, private)


async def verify_trace_access(cfg):
    settings, credentials = trace_credentials(cfg)
    try:
        async with httpx.AsyncClient(
            base_url=settings["url"].rstrip("/"), auth=credentials, timeout=15, trust_env=False
        ) as api:
            if settings.get("api_version", "v1") == "v2":
                now = datetime.now(timezone.utc)
                response = await api.get("/api/public/v2/observations", params={
                    "limit": 1, "sessionId": "tfp-preflight", "fields": "core",
                    "fromStartTime": (now - timedelta(minutes=1)).isoformat(), "toStartTime": now.isoformat(),
                })
            else:
                response = await api.get("/api/public/traces", params={"limit": 1, "sessionId": "tfp-preflight"})
    except httpx.RequestError as error:
        raise AssetDependencyError("monitoring", "tfp_langfuse", detail="Trace API is unreachable") from error
    if response.status_code != 200:
        raise AssetDependencyError("monitoring", "tfp_langfuse", detail=f"Read-only trace preflight failed (HTTP {response.status_code})")


def backend_values(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"sandbox.backend", "attributes.sandbox.backend"}:
                yield child
            else:
                yield from backend_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from backend_values(child)


def verify_warmups(observations, promoted):
    assert observations, "Empty telemetry cannot prove absence of warm-up"
    warmups = [item for item in observations if item.get("name") == "agent.sandbox.warmup"]
    assert len(warmups) == int(promoted), "Unexpected warm-up count"
    for item in warmups:
        assert item.get("endTime"), "Warm-up did not complete"
        assert item.get("level") != "ERROR", "Warm-up failed"
        assert list(backend_values(item.get("metadata") or {})) == ["docker"], (
            "Local fallback is not Docker acceptance"
        )
