# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Own the actual reverse FileCleanse probe and its disposable PostgreSQL."""

import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.mark.stage("D3")
@pytest.mark.case_id("DPR-FILE-CLEANSE-D3-001")
def test_reverse_file_cleanse(record_property):
    run_id = uuid4().hex
    try:
        result = subprocess.run([sys.executable, str(Path(__file__).with_name("probe.py")), run_id],
                                capture_output=True, text=True, timeout=80, check=False)
    finally:
        remaining = subprocess.check_output(["docker", "ps", "-aq", "--filter", "label=nexent.test_run=" + run_id],
                                            text=True, timeout=15)
        for container in remaining.splitlines():
            subprocess.run(["docker", "rm", "-f", "-v", container], capture_output=True, timeout=15, check=True)
        assert not subprocess.check_output(["docker", "ps", "-aq", "--filter", "label=nexent.test_run=" + run_id],
                                            text=True, timeout=15).strip()
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads(result.stdout.splitlines()[-1])
    for key in ("scoped_admission", "identity_denial", "idempotent_cancel", "live_revocation",
                "source_pinned", "owned_cleanup"):
        assert evidence[key] is True
    assert evidence["pg_rows"] == 1
    record_property("file_cleanse_probe", json.dumps(evidence, sort_keys=True))
