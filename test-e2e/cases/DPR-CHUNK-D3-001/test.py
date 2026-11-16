# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Actual SDK chunk parity in a disposable offline Linux environment."""

import json
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.mark.stage("D3")
@pytest.mark.case_id("DPR-CHUNK-D3-001")
def test_structural_chunk_parity(record_property):
    root = Path(__file__).resolve().parents[3]
    name = "dpr-chunk-" + uuid4().hex
    args = [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--network",
        "none",
        "-e",
        "NLTK_DATA=/opt/models/nltk_data",
        "-e",
        "PYTHONPATH=/proof:/proof/backend:/proof/sdk",
    ]
    for source, target in (
        (root / "backend/contracts", "/proof/backend/contracts"),
        (root / "backend/management", "/proof/backend/management"),
        (root / "backend/runtime", "/proof/backend/runtime"),
        (root / "infrastructure", "/proof/infrastructure"),
        (root / "sdk", "/proof/sdk"),
        (Path(__file__).parent, "/proof/case"),
    ):
        args.extend(["--mount", f"type=bind,source={source},target={target},readonly"])
    args.extend(
        [
            "--entrypoint",
            "/opt/backend/.venv/bin/python",
            "nexent/nexent-data-process:latest",
            "/proof/case/probe.py",
        ]
    )
    try:
        result = subprocess.run(
            args, text=True, capture_output=True, timeout=100, check=False
        )
    finally:
        subprocess.run(
            ["docker", "rm", "-f", "-v", name],
            capture_output=True,
            timeout=15,
            check=False,
        )
        remaining = subprocess.run(
            ["docker", "ps", "-aq", "--filter", "name=^/" + name + "$"],
            text=True,
            capture_output=True,
            timeout=15,
            check=True,
        )
        assert not remaining.stdout.strip()
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads(result.stdout.splitlines()[-1])
    assert evidence["equivalent_cases"] == 24
    assert evidence["no_parser_or_management_import"] is True
    record_property("structural_chunk_parity", json.dumps(evidence, sort_keys=True))
