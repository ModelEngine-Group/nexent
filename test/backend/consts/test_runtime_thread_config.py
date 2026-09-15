import os
from pathlib import Path
import subprocess
import sys

import pytest

from backend.consts.const import (
    RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS,
    RUNTIME_AGENT_THREAD_MAX_WORKERS,
    RUNTIME_MCP_TOOL_TIMEOUT_SECONDS,
)


def test_ut_be_tlm_034_platform_defaults_match_deployment_example():
    """UT-BE-TLM-034 keeps runtime defaults aligned with the tracked example."""
    assert RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS == 50
    assert RUNTIME_AGENT_THREAD_MAX_WORKERS == 200
    assert RUNTIME_MCP_TOOL_TIMEOUT_SECONDS == 60

    example_path = Path(__file__).resolve().parents[3] / "deploy" / "env" / ".env.example"
    example = example_path.read_text(encoding="utf-8")
    assert "RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS=50" in example
    assert "RUNTIME_AGENT_THREAD_MAX_WORKERS=200" in example
    assert "RUNTIME_MCP_TOOL_TIMEOUT_SECONDS=60" in example


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS", "7"),
        ("RUNTIME_AGENT_THREAD_MAX_WORKERS", "11"),
        ("RUNTIME_MCP_TOOL_TIMEOUT_SECONDS", "13"),
    ],
)
def test_ut_be_tlm_034_positive_runtime_config_overrides_default(variable, value):
    """UT-BE-TLM-034 accepts explicit positive platform configuration."""
    environment = os.environ.copy()
    environment[variable] = value
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import backend.consts.const as c; print(c.{variable})",
        ],
        cwd=Path(__file__).resolve().parents[3],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert float(result.stdout.strip()) == float(value)


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS", "0"),
        ("RUNTIME_AGENT_THREAD_MAX_WORKERS", "-1"),
        ("RUNTIME_MCP_TOOL_TIMEOUT_SECONDS", "0"),
    ],
)
def test_ut_be_tlm_034_invalid_runtime_capacity_fails_import(variable, value):
    """UT-BE-TLM-034 rejects non-positive platform capacity and timeout values."""
    environment = os.environ.copy()
    environment[variable] = value
    result = subprocess.run(
        [sys.executable, "-c", "import backend.consts.const"],
        cwd=Path(__file__).resolve().parents[3],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert variable in result.stderr
