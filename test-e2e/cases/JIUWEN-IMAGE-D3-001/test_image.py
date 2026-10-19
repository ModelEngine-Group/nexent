"""Real image model and authenticated deployment qualification, with local fixture IDs."""

import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.case_id("JIUWEN-IMAGE-D3-001"), pytest.mark.stage("D3")]


def test_deployed_image_and_followup():
    here = Path(__file__).resolve().parent
    container = os.environ.get("NEXENT_REAL_SMOKE_CONTAINER", "nexent-runtime")
    values = [
        os.environ.get(key)
        for key in (
            "NEXENT_IMAGE_AGENT_ID",
            "NEXENT_IMAGE_SOURCE_MESSAGE_ID",
            "NEXENT_IMAGE_USER_ID",
            "NEXENT_IMAGE_EXPECTED_FACT",
        )
    ]
    assert all(values), "Authorized image fixture IDs and expected visual fact are required"
    target = "/tmp/jiuwen_image_case.py"
    subprocess.run(
        ["docker", "cp", str(here / "deployed_image.py"), container + ":" + target], check=True, capture_output=True
    )
    try:
        result = subprocess.run(
            [
                "docker",
                "exec",
                "-e",
                "PYTHONPATH=/opt/backend",
                "-w",
                "/opt/backend",
                container,
                "/opt/backend/.venv/bin/python",
                target,
                *values,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=550,
        )
        safe = [line for line in result.stdout.splitlines() if line.startswith(("IMAGE_RESULT=", "IMAGE_FAILURE="))]
        code = result.returncode
        del result
        print("\n".join(safe))
        assert code == 0, "Image runtime verification failed; only sanitized outcomes are shown"
        data = json.loads(next(line.split("=", 1)[1] for line in safe if line.startswith("IMAGE_RESULT=")))
        assert data["completed"] and data["followup_no_replay"] and data["cleanup"]
        assert data["tool_counts"] == [1, 0] and data["messages"] == 4
    finally:
        subprocess.run(
            [
                "docker",
                "exec",
                container,
                "/opt/backend/.venv/bin/python",
                "-c",
                "from pathlib import Path; Path('/tmp/jiuwen_image_case.py').unlink(missing_ok=True)",
            ],
            check=True,
            capture_output=True,
        )
