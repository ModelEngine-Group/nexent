# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Deployment timeouts reach SDK parameters without SDK environment reads."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

VARIABLES = ("RUNTIME_AGENT_COLLABORATION_TIMEOUT_SECONDS", "DEFAULT_TOOL_CALL_TIMEOUT")


def build_configured_run(values, overrides=None):
    root = Path(__file__).resolve().parents[3]
    environment = dict(os.environ, PYTHON_DOTENV_DISABLED="1",
                       PYTHONPATH=os.pathsep.join(str(root / name) for name in ("backend", "sdk")))
    for variable in VARIABLES:
        environment.pop(variable, None)
    environment.update(values)
    return subprocess.run(
        [sys.executable, "-c", """
import json
import sys

from runtime.adapters.nexent.factory import build_run_info

info = build_run_info(
    query="", model_config_list=[],
    agent_config={"name": "test", "description": "", "tools": [], "model_name": "test"},
    **json.loads(sys.argv[1]),
)
print(json.dumps([info.collaboration_timeout_seconds, info.tool_call_timeout_seconds]))
""", json.dumps(overrides or {})],
        cwd=root, env=environment,
        capture_output=True, text=True, check=False,
    )


@pytest.mark.parametrize("values,expected", [
    ({}, [300.0, 300.0]),
    (dict(zip(VARIABLES, ("900", "1200.5"))), [900.0, 1200.5]),
    (dict(zip(VARIABLES, ("0.05", "0.1"))), [0.05, 0.1]),
])
def test_timeouts_accept_defaults_and_independent_positive_overrides(values, expected):
    result = build_configured_run(values)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == expected


def test_explicit_run_timeout_takes_precedence_over_deployment():
    result = build_configured_run(
        dict(zip(VARIABLES, ("900", "1200.5"))), {"tool_call_timeout_seconds": 45},
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [900.0, 45.0]


@pytest.mark.parametrize("variable", VARIABLES)
@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "invalid", ""])
def test_invalid_timeouts_fail_startup_with_variable_name(variable, value):
    result = build_configured_run({variable: value})
    assert result.returncode != 0
    assert variable in result.stderr and "positive number" in result.stderr
