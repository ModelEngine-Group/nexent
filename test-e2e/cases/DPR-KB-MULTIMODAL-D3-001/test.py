# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Own the mixed embedding protocol proof and exact disposable resources."""

import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.mark.stage("D3")
@pytest.mark.case_id("DPR-KB-MULTIMODAL-D3-001")
def test_multimodal_ingestion(record_property):
    run_id = uuid4().hex
    try:
        result = subprocess.run([sys.executable, str(Path(__file__).with_name("probe.py")), run_id],
                                capture_output=True, text=True, timeout=130, check=False)
    finally:
        remaining = subprocess.check_output(["docker", "ps", "-aq", "--filter", "label=nexent.test_run=" + run_id], text=True, timeout=15)
        for container in remaining.splitlines():
            subprocess.run(["docker", "rm", "-f", "-v", container], capture_output=True, timeout=15, check=True)
        assert not subprocess.check_output(["docker", "ps", "-aq", "--filter", "label=nexent.test_run=" + run_id], text=True, timeout=15).strip()
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads(result.stdout.splitlines()[-1])
    assert evidence["provider_types"] == ["text", "image"]
    assert evidence["physical_vectors"] == 2
    assert evidence["typed_image_ref"] and evidence["denied_no_side_effects"] and evidence["owned_cleanup"]
    record_property("multimodal_ingestion", json.dumps(evidence, sort_keys=True))
