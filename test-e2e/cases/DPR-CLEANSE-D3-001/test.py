# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""DPR-CLEANSE-D3-001 owns the real durable-job/broker integration probe."""

import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.mark.stage("D3")
@pytest.mark.case_id("DPR-CLEANSE-D3-001")
def test_durable_cleanse_dispatch(record_property):
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
            ["docker", "ps", "-aq", "--filter", f"label=nexent.test_run={run_id}"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        assert remaining.returncode == 0, remaining.stderr
        for container in remaining.stdout.splitlines():
            subprocess.run(
                ["docker", "rm", "-f", "-v", container],
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
            )
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads(result.stdout.splitlines()[-1])
    for key in (
        "admission_replay",
        "ownership",
        "redis_dispatch",
        "duplicate_executes_once",
        "lease_takeover_fenced",
        "unknown_outcome_quarantined",
        "utc_audit_with_non_utc_session",
    ):
        assert evidence[key] is True, key
    record_property("cleanse_job_probe", json.dumps(evidence, sort_keys=True))
