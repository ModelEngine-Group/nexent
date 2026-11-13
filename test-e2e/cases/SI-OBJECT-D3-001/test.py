# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""SI-OBJECT-D3-001: real image/MinIO/LibreOffice collaboration, isolated from deployments."""

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
@pytest.mark.case_id("SI-OBJECT-D3-001")
def test_management_office_object_protocol(record_property):
    suffix = uuid.uuid4().hex[:12]
    network_id = None
    container_ids = []
    try:
        network_id = docker("network", "create", "--internal", "si-object-" + suffix)
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
        container_ids.append(minio)
        docker("start", minio)
        probe = docker(
            "create",
            "--network",
            network_id,
            "--mount",
            f"type=bind,source={Path(__file__).parent},target=/verification,readonly",
            "-e",
            "MINIO_ENDPOINT=http://store:9000",
            "-e",
            "MINIO_ACCESS_KEY=fixture-admin",
            "-e",
            "MINIO_SECRET_KEY=fixture-password-12345",
            "-e",
            "MINIO_DEFAULT_BUCKET=si-object-probe",
            "-e",
            "LIBREOFFICE_PROFILE_DIR=/tmp/office-profiles",
            "--entrypoint",
            "/opt/backend/.venv/bin/python",
            "nexent/nexent-management:latest",
            "/verification/probe.py",
        )
        container_ids.append(probe)
        output = docker("start", "-a", probe, timeout=160)
        state = json.loads(docker("inspect", "--format", "{{json .State}}", probe))
        assert state["ExitCode"] == 0
        result = json.loads(output.splitlines()[-1])
        record_property("object_protocol_result", json.dumps(result, sort_keys=True))
        assert result["pdf_bytes"] > 100 and result["stuck"] == []
        assert result["keys"] == ["docs/source.docx", "preview/final.pdf"]
        for file in (
            "infrastructure/object_storage/port.py",
            "backend/management/services/file/office_preview.py",
            "backend/management/thread_management.py",
            "infrastructure/file_processing/conversion.py",
            "infrastructure/file_processing/process.py",
        ):
            path = ROOT / file
            assert (
                result["source_hashes"][path.name]
                == hashlib.sha256(path.read_bytes()).hexdigest()
            ), file
    finally:
        for container_id in reversed(container_ids):
            docker("rm", "-f", "-v", container_id)
        if network_id:
            docker("network", "rm", network_id)
    remaining = set(docker("ps", "-aq", "--no-trunc").splitlines())
    assert not remaining.intersection(container_ids)
