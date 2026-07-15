"""Framework-neutral Skill script execution boundary."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from typing import Any, Protocol

from pydantic import BaseModel, Field


class SkillScriptExecutionRequest(BaseModel):
    """Validated Skill script invocation passed to an execution backend."""

    skill_name: str
    skill_root: str
    script_path: str
    params: str | None = None
    timeout_seconds: int = Field(default=300, gt=0)


class SkillScriptExecutor(Protocol):
    """Execution backend used after SkillManager authorization and path checks."""

    def execute(self, request: SkillScriptExecutionRequest) -> Any:
        """Execute an authorized Skill script and return its tool result."""
        ...


class LocalSkillScriptExecutor:
    """Preserve the existing backend-host subprocess behavior."""

    def execute(self, request: SkillScriptExecutionRequest) -> str:
        """Execute Python or Shell scripts on the current host."""
        argv = shlex.split(request.params) if request.params else []
        if request.script_path.endswith(".py"):
            command = [sys.executable, request.script_path, *argv]
        elif request.script_path.endswith(".sh"):
            command = ["bash", request.script_path, *argv]
        else:
            raise ValueError(f"Unsupported script type: {request.script_path}")

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=request.timeout_seconds,
                env=os.environ.copy(),
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(
                f"Script execution timed out: {request.script_path}"
            ) from exc

        if result.returncode != 0:
            return json.dumps({"error": result.stderr, "output": result.stdout})
        return result.stdout
