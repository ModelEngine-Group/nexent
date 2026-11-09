# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""AC-001: process configuration selects explicit runtimes and fails clearly."""

import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "value,expected",
    [(None, "codeagent"), ("codeagent", "codeagent"), ("toolcalling", "toolcalling")],
)
def test_ac001_runtime_environment_selection(value, expected):
    env = dict(os.environ)
    env.pop("NEXENT_AGENT_RUNTIME", None)
    if value is not None:
        env["NEXENT_AGENT_RUNTIME"] = value
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from backend.consts.const import NEXENT_AGENT_RUNTIME; print(NEXENT_AGENT_RUNTIME)",
        ],
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected


@pytest.mark.parametrize("value", ["", "unknown", "ToolCalling"])
def test_ac001_invalid_runtime_fails_at_configuration_boundary(value):
    result = subprocess.run(
        [sys.executable, "-c", "import backend.consts.const"],
        env={**os.environ, "NEXENT_AGENT_RUNTIME": value},
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "NEXENT_AGENT_RUNTIME must be codeagent or toolcalling" in result.stderr
