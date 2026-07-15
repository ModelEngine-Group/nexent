"""Opt-in end-to-end tests for a predeployed shared AIO sandbox."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

backend_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../backend")
)
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from consts import const  # noqa: E402
from services.agent_runtime.config import get_openjiuwen_sandbox_settings  # noqa: E402
from services.agent_runtime.openjiuwen_sandbox import (  # noqa: E402
    OpenJiuwenDevSandboxService,
    SandboxSkillScriptExecutor,
    cleanup_sandbox_host_staging,
)
from nexent.skills.script_executor import SkillScriptExecutionRequest  # noqa: E402


pytestmark = pytest.mark.skipif(
    not const.OPENJIUWEN_SANDBOX_ENABLED
    or not const.OPENJIUWEN_SANDBOX_BASE_URL,
    reason=(
        "Set OPENJIUWEN_SANDBOX_ENABLED=true and "
        "OPENJIUWEN_SANDBOX_BASE_URL to run fixed AIO sandbox E2E tests."
    ),
)


def _artifact_path(result: str) -> Path:
    payload = next(
        json.loads(line)
        for line in result.splitlines()
        if line.startswith("{") and "absolute_path" in line
    )
    return Path(payload["absolute_path"])


@pytest.mark.asyncio
async def test_real_fixed_aio_python_shell_csv_artifact_and_concurrency(tmp_path):
    settings = get_openjiuwen_sandbox_settings()
    service = OpenJiuwenDevSandboxService(settings)
    staging_dirs: list[str] = []
    attachment = tmp_path / "input.csv"
    attachment.write_text("name,value\na,1\nb,2\n", encoding="utf-8")

    python_skill = tmp_path / "skills" / "python-csv"
    python_skill.mkdir(parents=True)
    python_script = python_skill / "analyze.py"
    python_script.write_text(
        """import argparse
import os
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--input", required=True)
args = parser.parse_args()
content = Path(args.input).read_text(encoding="utf-8")
print(f"rows={len(content.splitlines()) - 1}")
Path(os.environ["NEXENT_OUTPUT_DIR"], "python-report.txt").write_text(
    content, encoding="utf-8"
)
""",
        encoding="utf-8",
    )
    shell_skill = tmp_path / "skills" / "shell-report"
    shell_skill.mkdir(parents=True)
    shell_script = shell_skill / "report.sh"
    shell_script.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf 'shell-ok' > "${NEXENT_OUTPUT_DIR}/shell-report.txt"
printf 'shell output'
""",
        encoding="utf-8",
    )
    python_executor = SandboxSkillScriptExecutor(
        service=service,
        request_id="e2e-python",
        tenant_id="e2e-tenant-a",
        attachments={str(attachment): "input.csv"},
        host_staging_dirs=staging_dirs,
        host_staging_root=str(tmp_path / "host-staging"),
    )
    shell_executor = SandboxSkillScriptExecutor(
        service=service,
        request_id="e2e-shell",
        tenant_id="e2e-tenant-b",
        host_staging_dirs=staging_dirs,
        host_staging_root=str(tmp_path / "host-staging"),
    )

    try:
        await service.start()
        python_result, shell_result = await asyncio.gather(
            python_executor.execute(
                SkillScriptExecutionRequest(
                    skill_name="python-csv",
                    skill_root=str(python_skill),
                    script_path=str(python_script),
                    params=f"--input {attachment}",
                )
            ),
            shell_executor.execute(
                SkillScriptExecutionRequest(
                    skill_name="shell-report",
                    skill_root=str(shell_skill),
                    script_path=str(shell_script),
                )
            ),
        )

        assert "rows=2" in python_result
        assert "shell output" in shell_result
        assert _artifact_path(python_result).read_text(encoding="utf-8") == (
            attachment.read_text(encoding="utf-8")
        )
        assert _artifact_path(shell_result).read_text(encoding="utf-8") == "shell-ok"
        assert len(staging_dirs) == 2
    finally:
        cleanup_sandbox_host_staging(staging_dirs)
        await service.stop()
