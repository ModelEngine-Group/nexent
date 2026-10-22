# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read-only deployed-source, sandbox-event and trace observations."""

import asyncio
import hashlib
import json
import subprocess
import time

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
        "from contracts.constants.environment import AGENT_WORKSPACE_ROOT,NEXENT_SANDBOX_CONTAINER_WORKSPACE_ROOT; "
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


async def trace_observations(cfg, conversation_id, final_marker):
    settings, credentials = trace_credentials(cfg)
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
            completed = [row for row in rows if final_marker in json.dumps(row.get("output"))]
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
            response = await api.get("/api/public/traces", params={"limit": 1, "sessionId": "tfp-preflight"})
    except httpx.RequestError as error:
        raise AssetDependencyError("monitoring", "tfp_langfuse", detail="Trace API is unreachable") from error
    if response.status_code != 200:
        raise AssetDependencyError("monitoring", "tfp_langfuse", detail="Read-only trace preflight failed")


def backend_values(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "sandbox.backend":
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
