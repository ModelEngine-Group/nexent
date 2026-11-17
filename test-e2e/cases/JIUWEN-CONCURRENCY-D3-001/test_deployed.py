# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Run fixed real-provider acceptance without storing private authentication."""

import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.case_id("JIUWEN-CONCURRENCY-D3-001"), pytest.mark.stage("D3")]


def test_deployed_first_attempt_parallel_children():
    path = os.environ.get("NEXENT_JIUWEN_CONCURRENCY_CONFIG")
    assert path, "Machine-local authorized concurrency configuration is required"
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    container = config.pop("container", "nexent-runtime")
    code = Path(__file__).with_name("deployed_probe.py").read_text(encoding="utf-8")
    result = subprocess.run(
        ["docker", "exec", "-i", "-e", "PYTHONPATH=/opt/backend", container,
         "/opt/backend/.venv/bin/python", "-", json.dumps(config)],
        input=code, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1000,
    )
    summaries = [line for line in result.stdout.splitlines() if line.startswith("CONCURRENCY_RESULT=")]
    assert summaries, "Probe did not produce its owned execution and cleanup report"
    report = json.loads(summaries[-1].split("=", 1)[1])
    Path(os.environ["RESULT_DIR"]).joinpath("deployed-result.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))
    assert result.returncode == 0 and report["status"] == "PASS", "Real concurrent child execution failed"
    assert report["cleanup"] and report["source_unchanged"]
    assert report["owned_conversations_cleaned"] == 2 and len(report["runs"]) == 6
    assert all(r["child_statuses"] == ["completed"] * 3 and r["history_matches"] for r in report["runs"])
