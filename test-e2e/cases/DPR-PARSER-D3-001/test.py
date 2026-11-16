# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Run current parsing source with cached Linux dependencies and no network."""

import json
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.mark.stage("D3")
@pytest.mark.case_id("DPR-PARSER-D3-001")
def test_process_owned_parser(record_property):
    root = Path(__file__).resolve().parents[3]
    image = "nexent/nexent-data-process:latest"
    image_id = subprocess.check_output(
        ["docker", "image", "inspect", "--format", "{{.Id}}", image],
        text=True,
        timeout=15,
    ).strip()
    name = "nexent-parser-proof-" + uuid4().hex
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
        (root / "infrastructure", "/proof/infrastructure"),
        (root / "sdk", "/proof/sdk"),
        (Path(__file__).parent, "/proof/case"),
    ):
        args.extend(["--mount", f"type=bind,source={source},target={target},readonly"])
    args.extend(
        [
            "--entrypoint",
            "/opt/backend/.venv/bin/python",
            image,
            "/proof/case/probe.py",
        ]
    )
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=100, check=False
        )
    finally:
        subprocess.run(
            ["docker", "rm", "-f", "-v", name],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        remaining = subprocess.run(
            ["docker", "ps", "-aq", "--filter", "name=^/" + name + "$"],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        assert not remaining.stdout.strip(), "owned parser container remains"
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads(result.stdout.splitlines()[-1])
    evidence["dependency_image_id"] = image_id
    for key in (
        "fork_rejected",
        "parent_lazy",
        "sdk_text_and_spreadsheet",
        "core_reused",
        "forbidden_imports_unused",
        "isolated_failures_reclaimed",
        "isolated_parser_rebuilt",
    ):
        assert evidence[key] is True, key
    record_property("parser_probe", json.dumps(evidence, sort_keys=True))
