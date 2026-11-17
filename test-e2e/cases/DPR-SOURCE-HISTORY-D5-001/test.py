# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Own all resources for image-packaged PostgreSQL source-reference verification."""

import hashlib
import json
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import pytest


def docker(*args, **kwargs):
    return subprocess.run(
        ["docker", *args],
        text=True,
        capture_output=True,
        timeout=30,
        check=True,
        **kwargs,
    ).stdout.strip()


@pytest.mark.case_id("DPR-SOURCE-HISTORY-D5-001")
@pytest.mark.stage("D5")
def test_knowledge_source_history(record_property):
    run_id = uuid4().hex
    pg_name, probe_name = "nexent-source-pg-" + run_id, "nexent-source-image-" + run_id
    root = Path(__file__).resolve().parents[3]
    image = docker(
        "image", "inspect", "--format", "{{.Id}}", "nexent/nexent-management:latest"
    )
    try:
        docker(
            "run",
            "-d",
            "--name",
            pg_name,
            "--label",
            "nexent.test_run=" + run_id,
            "-e",
            "POSTGRES_USER=fixture-user",
            "-e",
            "POSTGRES_PASSWORD=fixture-password",
            "-e",
            "POSTGRES_DB=source_reference",
            "postgres:15-alpine",
        )
        deadline = time.monotonic() + 25
        while True:
            ready = subprocess.run(
                [
                    "docker",
                    "exec",
                    pg_name,
                    "pg_isready",
                    "-U",
                    "fixture-user",
                    "-d",
                    "source_reference",
                ],
                text=True,
                capture_output=True,
                timeout=5,
            )
            if ready.returncode == 0:
                break
            assert time.monotonic() < deadline, (
                "Owned PostgreSQL startup exceeded deadline"
            )
            time.sleep(0.1)
        result = subprocess.run(
            [
                "docker",
                "run",
                "-i",
                "--name",
                probe_name,
                "--label",
                "nexent.test_run=" + run_id,
                "--network",
                "container:" + pg_name,
                "--entrypoint",
                "/opt/backend/.venv/bin/python",
                "-e",
                "POSTGRES_HOST=127.0.0.1",
                "-e",
                "POSTGRES_PORT=5432",
                "-e",
                "POSTGRES_USER=fixture-user",
                "-e",
                "NEXENT_POSTGRES_PASSWORD=fixture-password",
                "-e",
                "POSTGRES_DB=source_reference",
                "nexent/nexent-management:latest",
                "-",
            ],
            input=Path(__file__).with_name("probe.py").read_text(encoding="utf-8"),
            text=True,
            capture_output=True,
            timeout=90,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        evidence = json.loads(result.stdout.splitlines()[-1])
        assert all(
            evidence[key] is True
            for key in ("migration", "typed_roundtrip", "owner_guard", "rollback")
        )
        migration = (
            root / "deploy/sql/migrations/v2.9.0_018_knowledge_source_reference.sql"
        )
        assert (
            evidence["migration_sha256"]
            == hashlib.sha256(migration.read_bytes()).hexdigest()
        )
        for name, actual in evidence["source_hashes"].items():
            assert (
                actual
                == hashlib.sha256(
                    (root / "backend" / (name.replace(".", "/") + ".py")).read_bytes()
                ).hexdigest()
            ), name
    finally:
        owned = docker("ps", "-aq", "--filter", "label=nexent.test_run=" + run_id)
        for identity in owned.splitlines():
            docker("rm", "-f", "-v", identity)
        assert not docker("ps", "-aq", "--filter", "label=nexent.test_run=" + run_id)
    record_property(
        "source_history", json.dumps({"image_id": image, **evidence}, sort_keys=True)
    )
