# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Own disposable Linux/PG containers and verify the actual root lifecycle."""

import json
import os
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import pytest


def docker(*args, timeout=20):
    return subprocess.check_output(
        ["docker", *args], text=True, timeout=timeout
    ).strip()


@pytest.mark.stage("D3")
@pytest.mark.case_id("DPR-CLEANSE-ROOT-D3-001")
def test_owned_cleanse_root(record_property):
    run_id = uuid4().hex
    root = Path(__file__).resolve().parents[3]
    containers = []
    try:
        image = docker(
            "image",
            "inspect",
            "--format",
            "{{.Id}}",
            os.environ["NEXENT_CLEANSE_TEST_IMAGE"],
        )
        pg = docker(
            "run",
            "-d",
            "--label",
            "nexent.test_run=" + run_id,
            "-e",
            "POSTGRES_PASSWORD=fixture-password",
            "-p",
            "127.0.0.1::5432",
            "postgres:15-alpine",
        )
        containers.append(pg)
        port = json.loads(
            docker("inspect", "--format", "{{json .NetworkSettings.Ports}}", pg)
        )["5432/tcp"][0]["HostPort"]
        deadline = time.monotonic() + 25
        while True:
            ready = subprocess.run(
                ["docker", "exec", pg, "pg_isready", "-U", "postgres"],
                capture_output=True,
                timeout=5,
                check=False,
            )
            if ready.returncode == 0:
                break
            assert time.monotonic() < deadline, (
                "fixture PostgreSQL did not become ready"
            )
            time.sleep(0.1)
        name = "nexent-cleanse-root-" + run_id
        containers.append(name)
        result = subprocess.run(
            [
                "docker",
                "run",
                "--name",
                name,
                "--workdir",
                "/proof",
                "--label",
                "nexent.test_run=" + run_id,
                "--mount",
                f"type=bind,source={root},target=/proof,readonly",
                "-e",
                "PYTHONPATH=/proof:/proof/backend:/proof/sdk",
                "-e",
                "POSTGRES_USER=postgres",
                "-e",
                "NEXENT_POSTGRES_PASSWORD=fixture-password",
                "-e",
                "POSTGRES_HOST=host.docker.internal",
                "-e",
                "POSTGRES_PORT=" + port,
                "-e",
                "POSTGRES_DB=postgres",
                "-e",
                "HF_HUB_OFFLINE=1",
                "--entrypoint",
                "/opt/backend/.venv/bin/python",
                image,
                "/proof/test-e2e/cases/DPR-CLEANSE-ROOT-D3-001/probe.py",
            ],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        evidence = json.loads(result.stdout.splitlines()[-1])
        for key in ("separate_ready", "root_reaped", "failure_unhealthy", "no_restart"):
            assert evidence[key] is True
        record_property(
            "root_lifecycle", json.dumps({**evidence, "dependency_image": image})
        )
    finally:
        for container in reversed(containers):
            docker("rm", "-f", "-v", container)
    assert not docker("ps", "-aq", "--filter", "label=nexent.test_run=" + run_id)
