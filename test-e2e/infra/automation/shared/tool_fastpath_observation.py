# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read-only deployed-source, sandbox-event and trace observations."""

import asyncio
import hashlib
import json
import subprocess
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import httpx

from shared.asset_registry import AssetDependencyError
from shared.config import load_secret_env, repo_root


SOURCES = (
    "core/agents/cores/smolagents/agent.py", "core/agents/cores/smolagents/tool_fastpath.py",
    "core/agents/resources/workspace.py", "core/agents/sandbox/__init__.py",
    "core/agents/sandbox/config.py", "core/agents/sandbox/execution.py",
    "core/agents/sandbox/compatibility.py", "core/agents/sandbox/tls.py",
)


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
    return inspect_deployment(cfg["runtime_container"], workspace_mount_id=cfg["workspace_mount_id"])[0]


def inspect_deployment(runtime_container, *, workspace_mount_id=None):
    record = json.loads(docker_command("inspect", runtime_container))[0]
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
        "from nexent.core.agents.resources.workspace import SandboxWorkspace; "
        "root=Path(nexent.__file__).parent; "
        f"sources={{p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in {SOURCES!r}}}; "
        "mapping=SandboxWorkspace(Path(AGENT_WORKSPACE_ROOT),NEXENT_SANDBOX_CONTAINER_WORKSPACE_ROOT); "
        "print(json.dumps({'sources':sources,'mount_id':mapping.mount_id}))"
    )
    observed = json.loads(
        docker_command("exec", runtime_container, "/opt/backend/.venv/bin/python", "-c", script)
    )
    expected = {path: hashlib.sha256((repo_root() / "sdk/nexent" / path).read_bytes()).hexdigest() for path in SOURCES}
    assert observed["sources"] == expected, "The running SDK differs from the worktree under test"
    mount_id = observed["mount_id"]
    if workspace_mount_id is not None:
        assert mount_id == workspace_mount_id, "Docker observation scope differs from runtime mapping"
    filters = (
        "--filter",
        "label=com.nexent.sandbox=session",
        "--filter",
        "label=com.nexent.workspace=" + mount_id,
    )
    assert not docker_command("ps", *filters, "--format", "{{.ID}}").strip(), "Fixture sandbox scope must be idle"
    return expected, mount_id


@contextmanager
def capture_sandbox_events(cfg, records):
    """Capture scoped lifecycle events in real time before Docker's history rotates."""
    command = [
        "docker", "events",
        "--since",
        str(time.time()),
        "--filter",
        "type=container",
        "--filter",
        "label=com.nexent.sandbox=session",
        "--filter",
        "label=com.nexent.workspace=" + cfg["workspace_mount_id"],
        "--filter", "event=create",
        "--filter", "event=destroy",
        "--format",
        "{{json .}}",
    ]
    with tempfile.TemporaryFile() as output:
        try:
            process = subprocess.Popen(command, stdout=output, stderr=subprocess.DEVNULL)
        except OSError as error:
            raise AssetDependencyError("deployment", "tfp_docker", detail="Docker event capture could not start") from error
        try:
            yield
        finally:
            if process.poll() is not None:
                raise AssertionError("Docker event capture exited before the scenario ended")
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            output.seek(0)
            for line in output:
                event = json.loads(line)
                actor = event["Actor"]
                assert actor["Attributes"].get("com.nexent.workspace") == cfg["workspace_mount_id"]
                action = event.get("Action", event.get("status"))
                assert action in {"create", "destroy"}
                records.append({"action": action, "id": actor["ID"]})


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
    session = str(conversation_id)
    previous_ids = None
    async with httpx.AsyncClient(
        base_url=settings["url"].rstrip("/"), auth=credentials, timeout=15, trust_env=False
    ) as api:
        while time.monotonic() < deadline:
            traces = await numbered_pages(api, "/api/public/traces", {"sessionId": session}, deadline, sparse=True)
            observations = []
            if traces is not None:
                assert all(str(row.get("sessionId")) == session for row in traces), "Unrelated Agent trace"
                for row in traces:
                    trace_id = row["id"]
                    items = await numbered_pages(api, "/api/public/observations", {"traceId": trace_id}, deadline)
                    if items is None:
                        observations = []
                        break
                    assert all(item.get("traceId") == trace_id for item in items), "Unrelated Agent observation"
                    # The trace summary can be an HTTP span without the Agent's answer.
                    if any(completed_agent(item, final_marker) for item in items):
                        roots = [item for item in items if not item.get("parentObservationId")]
                        if not roots or any(not root.get("endTime") for root in roots):
                            observations = []
                            break
                        observations.extend(items)
            ids = {item["id"] for item in observations} or None
            warmups = [item for item in observations if item.get("name") == "agent.sandbox.warmup"]
            if ids and (expected_warmups is None or len(warmups) >= expected_warmups):
                # Negative proof needs a settled observation tree as child spans may arrive late.
                if expected_warmups != 0 or ids == previous_ids:
                    return observations
            previous_ids = ids
            await asyncio.sleep(1)
    raise AssertionError("Complete Agent observations were not available before the deadline")


async def numbered_pages(api, path, params, deadline, *, sparse=False):
    """Read a consistent v1 snapshot, or retry when indexing moved page boundaries."""
    rows, ids = [], set()
    total = None
    limit = 100
    for page in range(1, 101):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        response = await api.get(path, params=dict(params, page=page, limit=limit), timeout=min(15, remaining))
        assert response.status_code == 200, "Langfuse trace or observation query failed"
        body = response.json()
        items = body.get("data")
        meta = body.get("meta", {})
        count = meta.get("totalItems")
        assert isinstance(items, list) and type(count) is int and count >= 0, "Invalid Langfuse pagination metadata"
        page_count = (count + limit - 1) // limit
        assert meta.get("totalPages", page_count) == page_count and meta.get("page", page) == page, (
            "Invalid Langfuse pagination bounds"
        )
        assert all(isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"] for item in items), (
            "Langfuse page has an unidentified item"
        )
        if total is None:
            total = count
        new_ids = {item["id"] for item in items}
        if count != total or len(items) > limit or len(new_ids) != len(items) or ids & new_ids:
            return None
        # The v1 Trace index can count multiple stored versions of one trace while returning one ID.
        # Traverse all advertised pages. Observation lists still require an exact, complete count.
        if len(rows) + len(items) > total or (not sparse and len(items) != min(limit, total - len(rows))):
            return None
        rows.extend(items)
        ids.update(new_ids)
        if page >= page_count:
            return rows
    raise AssertionError("Langfuse numbered pagination exceeded the bounded fixture limit")


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


def completed_agent(row, final_marker):
    return row.get("name") == "agent.run" and row.get("endTime") and output_contains(row.get("output"), final_marker)


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
            completed = [row for row in rows if completed_agent(row, final_marker)]
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


async def verify_trace_access(cfg, *, startup_wait=0):
    settings, credentials = trace_credentials(cfg)
    now = datetime.now(timezone.utc)
    path = "/api/public/traces"
    params = {"limit": 1, "sessionId": "tfp-preflight"}
    if settings.get("api_version", "v1") == "v2":
        path = "/api/public/v2/observations"
        params.update(fields="core", fromStartTime=(now - timedelta(minutes=1)).isoformat(), toStartTime=now.isoformat())
    deadline = time.monotonic() + startup_wait
    async with httpx.AsyncClient(
        base_url=settings["url"].rstrip("/"), auth=credentials, timeout=15, trust_env=False
    ) as api:
        while True:
            try:
                response = await api.get(path, params=params)
                if response.status_code == 200:
                    return
                detail = f"Read-only trace preflight failed (HTTP {response.status_code})"
                if response.status_code not in {502, 503, 504}:
                    break
            except httpx.RequestError:
                detail = "Trace API is unreachable"
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(2, remaining))
    raise AssetDependencyError("monitoring", "tfp_langfuse", detail=detail)


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
