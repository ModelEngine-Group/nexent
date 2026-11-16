# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Own the multi-store worker probe and reclaim its resources even on failure."""

import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.mark.stage("D3")
@pytest.mark.case_id("DPR-KB-WORKER-D3-001")
def test_runtime_knowledge_upload(record_property):
    run_id = uuid4().hex
    try:
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("probe.py")), run_id],
            capture_output=True,
            text=True,
            timeout=150,
            check=False,
        )
    finally:
        remaining = subprocess.run(
            ["docker", "ps", "-aq", "--filter", "label=nexent.test_run=" + run_id],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        for container in remaining.stdout.splitlines():
            subprocess.run(
                ["docker", "rm", "-f", "-v", container],
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
            )
        assert not subprocess.check_output(
            ["docker", "ps", "-aq", "--filter", "label=nexent.test_run=" + run_id],
            text=True,
            timeout=15,
        ).strip()
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads(result.stdout.splitlines()[-1])
    for name in (
        "pinned_objects",
        "visible_generation",
        "duplicate_no_invoke",
        "legacy_preserved",
        "revocation_before_write",
        "owned_cleanup",
    ):
        assert evidence[name] is True, name
    record_property("knowledge_worker_probe", json.dumps(evidence, sort_keys=True))
