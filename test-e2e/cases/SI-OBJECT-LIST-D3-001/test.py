# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Real scoped object listing with test-owned MinIO and read-only current code."""

import hashlib
import json
import subprocess
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
MINIO_IMAGE = "quay.io/minio/minio:RELEASE.2023-12-20T01-00-02Z"


def docker(*args, timeout=30):
    result = subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout, check=False
    )
    assert result.returncode == 0, result.stderr[-4000:] + result.stdout[-4000:]
    return result.stdout.strip()


@pytest.mark.stage("D3")
@pytest.mark.case_id("SI-OBJECT-LIST-D3-001")
def test_scoped_object_list_protocol(record_property):
    network_id, containers = None, []
    try:
        network_id = docker(
            "network", "create", "--internal", "si-list-" + uuid.uuid4().hex[:12]
        )
        minio = docker(
            "create",
            "--network",
            network_id,
            "--network-alias",
            "store",
            "-e",
            "MINIO_ROOT_USER=fixture-admin",
            "-e",
            "MINIO_ROOT_PASSWORD=fixture-password-12345",
            MINIO_IMAGE,
            "server",
            "/data",
        )
        containers.append(minio)
        docker("start", minio)
        probe = docker(
            "create",
            "--network",
            network_id,
            "--mount",
            f"type=bind,source={ROOT},target=/source,readonly",
            "-e",
            "PYTHONPATH=/source:/source/sdk:/source/backend",
            "--entrypoint",
            "/opt/backend/.venv/bin/python",
            "nexent/nexent-management:latest",
            "/source/test-e2e/cases/SI-OBJECT-LIST-D3-001/probe.py",
        )
        containers.append(probe)
        output = docker("start", "-a", probe, timeout=65)
        assert (
            json.loads(docker("inspect", "--format", "{{json .State}}", probe))[
                "ExitCode"
            ]
            == 0
        )
        result = json.loads(output.splitlines()[-1])
        assert result["keys"] == ["artifacts/a", "artifacts/b", "artifacts/c"]
        assert result["scope_rejections"] == 4
        for name, digest in result["source_hashes"].items():
            assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, (
                name
            )
        record_property("listing_protocol_result", json.dumps(result, sort_keys=True))
    finally:
        # Attempt every owned cleanup even if a preceding removal fails.
        failures = []
        for container in reversed(containers):
            try:
                docker("rm", "-f", "-v", container)
            except (AssertionError, subprocess.TimeoutExpired) as error:
                failures.append(str(error))
        if network_id:
            try:
                docker("network", "rm", network_id)
            except (AssertionError, subprocess.TimeoutExpired) as error:
                failures.append(str(error))
        assert not failures, failures
    remaining = set(docker("ps", "-aq", "--no-trunc").splitlines())
    assert not remaining.intersection(containers)
