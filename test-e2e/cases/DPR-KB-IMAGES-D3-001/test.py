# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Execute the SDK consumer and source protocol proof in an isolated process."""

import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.mark.stage("D3")
@pytest.mark.case_id("DPR-KB-IMAGES-D3-001")
def test_knowledge_images(record_property):
    run_id = uuid4().hex
    try:
        result = subprocess.run([sys.executable, str(Path(__file__).with_name("probe.py")), run_id],
                                capture_output=True, text=True, timeout=80, check=False)
    finally:
        matches = subprocess.check_output(["docker", "ps", "-aq", "--filter", "label=nexent.test_run=" + run_id],
                                           text=True, timeout=15)
        for container in matches.splitlines():
            subprocess.run(["docker", "rm", "-f", "-v", container], capture_output=True, timeout=15, check=True)
        assert not subprocess.check_output(["docker", "ps", "-aq", "--filter", "label=nexent.test_run=" + run_id],
                                           text=True, timeout=15).strip()
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads(result.stdout.splitlines()[-1])
    for key in ("sdk_projection", "owner_scope", "http_once", "source_preserved", "workers_reclaimed", "owned_cleanup"):
        assert evidence[key] is True
    record_property("knowledge_images", json.dumps(evidence, sort_keys=True))
