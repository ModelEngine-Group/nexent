"""Tests for framework-neutral Skill script executors."""

import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from nexent.skills.script_executor import (
    LocalSkillScriptExecutor,
    SkillScriptExecutionRequest,
)


def test_local_executor_preserves_python_command_and_environment(mocker, tmp_path):
    script_path = tmp_path / "run.py"
    script_path.write_text("print('ok')", encoding="utf-8")
    run = mocker.patch(
        "nexent.skills.script_executor.subprocess.run",
        return_value=SimpleNamespace(returncode=0, stdout="ok\n", stderr=""),
    )
    request = SkillScriptExecutionRequest(
        skill_name="demo",
        skill_root=str(tmp_path),
        script_path=str(script_path),
        params='--name "hello world"',
        timeout_seconds=42,
    )

    result = LocalSkillScriptExecutor().execute(request)

    assert result == "ok\n"
    assert run.call_args.args[0] == [
        sys.executable,
        str(script_path),
        "--name",
        "hello world",
    ]
    assert run.call_args.kwargs["timeout"] == 42
    assert run.call_args.kwargs["env"]


def test_local_executor_preserves_nonzero_result_shape(mocker, tmp_path):
    script_path = tmp_path / "run.sh"
    script_path.write_text("exit 2", encoding="utf-8")
    mocker.patch(
        "nexent.skills.script_executor.subprocess.run",
        return_value=SimpleNamespace(
            returncode=2,
            stdout="partial",
            stderr="failed",
        ),
    )

    result = LocalSkillScriptExecutor().execute(
        SkillScriptExecutionRequest(
            skill_name="demo",
            skill_root=str(tmp_path),
            script_path=str(script_path),
        )
    )

    assert json.loads(result) == {"error": "failed", "output": "partial"}


def test_local_executor_maps_subprocess_timeout(mocker, tmp_path):
    script_path = tmp_path / "run.py"
    script_path.write_text("pass", encoding="utf-8")
    mocker.patch(
        "nexent.skills.script_executor.subprocess.run",
        side_effect=subprocess.TimeoutExpired("python", 1),
    )

    with pytest.raises(TimeoutError, match="timed out"):
        LocalSkillScriptExecutor().execute(
            SkillScriptExecutionRequest(
                skill_name="demo",
                skill_root=str(tmp_path),
                script_path=str(script_path),
                timeout_seconds=1,
            )
        )
