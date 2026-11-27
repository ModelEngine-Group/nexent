# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Drive owned D3 release phases across a disposable, data-preserving Core switch."""

import asyncio
import json
import os
import subprocess
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from uuid import uuid4

import pytest

from shared.auth import sign_in
from shared.http import assert_status, client

pytestmark = [pytest.mark.case_id("JIUWEN-RELEASE-D3-001"), pytest.mark.stage("D3")]
CORES = ("smolagents", "jiuwen", "smolagents")


async def deployment_identity():
    actor = await sign_in("tenant_a_admin")
    async with client("config", token=actor.access_token) as api:
        response = await api.get("/tenant_config/deployment_version")
    assert_status(response, 200)
    core = response.json().get("agent_core")
    assert core in CORES
    return actor, core


def private_driver():
    path = os.environ.get("NEXENT_E2E_CORE_SWITCH_CONFIG")
    if not path or not Path(path).is_file():
        pytest.skip("Set NEXENT_E2E_CORE_SWITCH_CONFIG for an isolated Core-switch deployment")
    driver = json.loads(Path(path).read_text(encoding="utf-8"))
    base = urlsplit(driver["base_url"])
    configured = urlsplit(os.environ["NEXENT_BASE_URL"])
    argv = driver["argv"]
    container = driver["fixture_container"]
    directory = PurePosixPath(driver["fixture_directory"])
    if (base.hostname not in {"localhost", "127.0.0.1"} or (base.scheme, base.netloc) !=
            (configured.scheme, configured.netloc) or not isinstance(argv, list) or not argv
            or not all(isinstance(arg, str) and arg for arg in argv)
            or container == "nexent-config" or not directory.is_absolute() or ".." in directory.parts):
        pytest.skip("Configure a driver with the isolated base URL and persistent fixture directory")
    return argv, container, directory


def test_deployed_real_smoke():
    keys = ("NEXENT_REAL_NATIVE_MODEL_ID", "NEXENT_REAL_TEXT_MODEL_ID", "NEXENT_REAL_TENANT_ID")
    values = [os.environ.get(key) for key in keys]
    missing = [key for key, value in zip(keys, values) if not value]
    if missing:
        pytest.skip("Missing authorized release fixture bindings: " + ", ".join(missing))
    argv, container, directory = private_driver()
    actor, original_core = asyncio.run(deployment_identity())
    assert actor.tenant_id == values[2], "Configured model outlets and test actor must share the test tenant"

    def select(core):
        _, current = asyncio.run(deployment_identity())
        if current != core:
            result = subprocess.run([*argv, core], capture_output=True, timeout=180, check=False)
            assert result.returncode == 0, "Isolated Core switch failed. Inspect its machine-local deployment log"
            _, current = asyncio.run(deployment_identity())
            assert current == core, "Running Core differs from the requested deployment mode"

    here = Path(__file__).resolve().parent
    target = directory / ("m6-" + uuid4().hex)
    script = target.with_suffix(".py").as_posix()
    provider = (directory / (target.name + "-provider.py")).as_posix()
    checkpoint = target.with_suffix(".json").as_posix()
    progress = target.with_suffix(".progress.json").as_posix()
    def phase(name):
        result = subprocess.run(
            ["docker", "exec", "-e", "PYTHONPATH=/opt:/opt/backend", "-w", "/opt/backend",
             container, "python", script, *values, name, actor.user_id, checkpoint, provider],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1150,
        )
        safe = [line for line in result.stdout.splitlines()
                if line.startswith(("SMOKE_RESULT=", "SMOKE_FAILURE=", "SMOKE_PARTIAL="))]
        print("\n".join(safe))
        assert result.returncode == 0, f"Deployed release phase {name} failed"
        return json.loads(next(line.split("=", 1)[1] for line in safe if line.startswith("SMOKE_RESULT=")))

    outcomes = []
    copied_paths = []
    cleanup_pending = False
    try:
        for source, destination in (
            (here / "deployed_smoke.py", script),
            (here.parents[2] / "test-e2e/infra/automation/jiuwen_resource_provider.py", provider),
        ):
            copied_paths.append(destination)
            subprocess.run(["docker", "cp", str(source), f"{container}:{destination}"],
                           check=True, capture_output=True)
        select(CORES[0])
        cleanup_pending = True
        phase("prepare")
        for index, core in enumerate(CORES):
            select(core)
            outcomes.append(phase(str(index))["deployed_http_history"])
        assert tuple(item["core"] for item in outcomes) == CORES
        phase("cleanup")
        cleanup_pending = False
        select("jiuwen")
        payload = phase("sdk")
        for name in ("native_resources", "text_resources", "collaboration_jiuwen",
                     "collaboration_smolagents", "collaboration_a2a"):
            assert payload[name]["completed"]
    finally:
        try:
            if cleanup_pending:
                phase("cleanup")
                cleanup_pending = False
        finally:
            try:
                select(original_core)
            finally:
                if copied_paths and not cleanup_pending:
                    subprocess.run(["docker", "exec", container, "rm", "-f", "--",
                                    *copied_paths, checkpoint, progress], check=True, capture_output=True)
