"""Run the fixed smoke on the authorized deployment with machine-local outlet IDs."""

import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.case_id("JIUWEN-RELEASE-D3-001"), pytest.mark.stage("D3")]


def test_deployed_real_smoke():
    here = Path(__file__).resolve().parent
    root = here.parents[2]
    container = os.environ.get("NEXENT_REAL_SMOKE_CONTAINER", "nexent-runtime")
    values = [
        os.environ.get(key)
        for key in ("NEXENT_REAL_NATIVE_MODEL_ID", "NEXENT_REAL_TEXT_MODEL_ID", "NEXENT_REAL_TENANT_ID")
    ]
    assert all(values), "Real smoke requires machine-local native/text outlet IDs and authorized tenant"
    for source, target in [
        (here / "deployed_smoke.py", "/tmp/m6_deployed_smoke.py"),
        (root / "test-e2e/infra/automation/jiuwen_resource_provider.py", "/tmp/m6_resource_provider.py"),
    ]:
        subprocess.run(["docker", "cp", str(source), container + ":" + target], check=True, capture_output=True)
    result = subprocess.run(
        [
            "docker",
            "exec",
            "-e",
            "PYTHONPATH=/opt/backend",
            "-w",
            "/opt/backend",
            container,
            "python",
            "/tmp/m6_deployed_smoke.py",
            *values,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1150,
    )
    safe = [
        line
        for line in result.stdout.splitlines()
        if line.startswith(("SMOKE_RESULT=", "SMOKE_FAILURE=", "SMOKE_PARTIAL="))
    ]
    print("\n".join(safe))
    return_code = result.returncode
    del result
    assert return_code == 0, "Deployed real-model smoke failed; sanitized outcomes above"
    payload = json.loads(next(line.split("=", 1)[1] for line in safe if line.startswith("SMOKE_RESULT=")))
    assert [v["core"] for v in payload["deployed_http_history"]] == ["smolagents", "jiuwen", "smolagents"]
    for name in (
        "native_resources",
        "text_resources",
        "collaboration_jiuwen",
        "collaboration_smolagents",
        "collaboration_a2a",
    ):
        assert payload[name]["completed"]
