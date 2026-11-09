# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Verify deployed image/source identity, configuration, mounts and health."""

import hashlib
import json
import os
from pathlib import Path

import docker
import httpx
import pytest
from shared.case_evidence import write_case_evidence

CASE_ID = "AGENT-NATIVE-D5-001"


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage("D5")
def test_branch_built_runtime_identity_and_health():
    client = docker.from_env()
    expected = json.loads(os.environ["NEXENT_NATIVE_EXPECTED_IMAGES"])
    identities = {}
    for name in (
        "nexent-runtime",
        "nexent-config",
        "nexent-northbound",
        "nexent-mcp",
        "nexent-web",
    ):
        container = client.containers.get(name)
        assert container.status == "running"
        target = expected["web" if name == "nexent-web" else "main"]
        assert container.image.id == target
        identities[name] = {
            "container_id": container.id,
            "image_id": container.image.id,
        }
    runtime = client.containers.get("nexent-runtime")
    environment = dict(item.split("=", 1) for item in runtime.attrs["Config"]["Env"])
    assert environment["NEXENT_AGENT_RUNTIME"] == "toolcalling"
    assert environment["ENABLE_TELEMETRY"] == "true"
    assert not any(
        mount["Destination"] in {"/opt/sdk", "/opt/backend", "/task"}
        for mount in runtime.attrs["Mounts"]
    )
    command = [
        "/opt/backend/.venv/bin/python",
        "-c",
        (
            "import hashlib,inspect,json; from nexent.core.agents.native_runtime import NativeToolCallingAgent; "
            "from contracts.constants.environment import NEXENT_AGENT_RUNTIME; "
            "print(json.dumps({'runtime':NEXENT_AGENT_RUNTIME,'sha256':hashlib.sha256("
            "open(inspect.getfile(NativeToolCallingAgent),'rb').read()).hexdigest()}))"
        ),
    ]
    result = runtime.exec_run(command, workdir="/opt/backend")
    assert result.exit_code == 0
    source = json.loads(result.output)
    expected_source = hashlib.sha256(
        (
            Path(os.environ["NEXENT_REPO"]) / "sdk/nexent/core/agents/native_runtime.py"
        ).read_bytes()
    ).hexdigest()
    assert source == {"runtime": "toolcalling", "sha256": expected_source}
    assert (
        httpx.get(
            os.environ["NEXENT_BASE_URL"], timeout=30, follow_redirects=True
        ).status_code
        == 200
    )
    assert (
        httpx.get(
            os.environ["NEXENT_CONFIG_URL"] + "/user/service_health", timeout=30
        ).status_code
        == 200
    )
    sandbox = client.containers.get("nexent-runtime-sandbox")
    assert sandbox.image.id == expected["sandbox"]
    write_case_evidence(
        "deployed-identity",
        {
            "containers": identities,
            "runtime_source": source,
            "sandbox_image_id": sandbox.image.id,
            "runtime_source_mount_absent": True,
            "application_and_auth_health": True,
        },
    )
    client.close()
