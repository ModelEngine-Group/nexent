# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Fixed real-resource smoke; machine-local identities never enter repository assets."""

import json
import os
import subprocess
import uuid
from pathlib import Path

import pytest

pytestmark = [pytest.mark.case_id("JIUWEN-RESOURCES-D3-003"), pytest.mark.stage("D3")]


def test_deployed_resource_acceptance():
    here = Path(__file__).resolve().parent
    root = here.parents[2]
    local_config = os.environ.get("NEXENT_RESOURCE_ACCEPTANCE_CONFIG")
    assert local_config, "Machine-local real resource configuration is required"
    inputs = json.loads(Path(local_config).read_text(encoding="utf-8"))
    container = inputs.get("container", "nexent-runtime")
    target = "/tmp/nexent_resources_" + uuid.uuid4().hex[:12]
    result_dir = Path(os.environ["RESULT_DIR"]) / "private"
    result_dir.mkdir(exist_ok=True)
    for source, suffix in [(here / "deployed_resources.py", ".py"),
                           (root / "test-e2e/cases/JIUWEN-SKILL-FILES-D4-001/fixture.py", "_helper.py"),
                           (Path(local_config), "_config.json")]:
        subprocess.run(["docker", "cp", str(source), container + ":" + target + suffix],
                       check=True, capture_output=True)
    result = subprocess.run(["docker", "exec", "-e", "PYTHONPATH=/opt/backend", "-w", "/opt/backend", container,
        "/opt/backend/.venv/bin/python", target + ".py", target + "_config.json", target + "_helper.py", target],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1150, check=False)
    safe = [line for line in result.stdout.splitlines() if line.startswith(("RESOURCE_SCENARIO=", "RESOURCE_RESULT="))]
    print("\n".join(safe))
    # Private traces/events are needed to diagnose failures, but never print credentials/prompts.
    subprocess.run(["docker", "cp", container + ":" + target + "/.", str(result_dir)], check=True, capture_output=True)
    subprocess.run(["docker", "exec", container, "/opt/backend/.venv/bin/python", "-c",
        "from pathlib import Path; import shutil; p=Path('" + target + "'); "
        "assert p.parent==Path('/tmp') and p.name.startswith('nexent_resources_'); "
        "shutil.rmtree(p); "
        "[Path(str(p)+s).unlink(missing_ok=True) for s in ['.py','_helper.py','_config.json']]"],
        check=True, capture_output=True)
    assert result.returncode == 0, "Real resource acceptance failed; see sanitized scenarios and private local evidence"
    report = json.loads(next(line.split("=", 1)[1] for line in safe if line.startswith("RESOURCE_RESULT=")))
    assert report["status"] == "PASS" and report["cleanup"] and report["source_unchanged"]
    assert set(report["scenarios"]) == {"external_mcp", "knowledge", "skills", "mixed_core"}
    assert all(row["completed"] and row["no_replay"] for row in report["scenarios"].values())
