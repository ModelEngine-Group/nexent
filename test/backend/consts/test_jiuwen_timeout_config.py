# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Deployment timeouts reach SDK parameters without SDK environment reads."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

VARIABLES = ("RUNTIME_AGENT_COLLABORATION_TIMEOUT_SECONDS", "DEFAULT_TOOL_CALL_TIMEOUT")


def read_configuration(values):
    environment = dict(os.environ, PYTHON_DOTENV_DISABLED="1")
    for variable in VARIABLES:
        environment.pop(variable, None)
    environment.update(values)
    return subprocess.run(
        [sys.executable, "-c",
         ("import json; from backend.contracts.constants import environment as c; "
          "print(json.dumps([c.RUNTIME_AGENT_COLLABORATION_TIMEOUT_SECONDS, c.DEFAULT_TOOL_CALL_TIMEOUT]))")],
        cwd=Path(__file__).resolve().parents[3], env=environment,
        capture_output=True, text=True, check=False,
    )


@pytest.mark.parametrize("values,expected", [
    ({}, [300.0, 300.0]),
    (dict(zip(VARIABLES, ("900", "1200.5"))), [900.0, 1200.5]),
    (dict(zip(VARIABLES, ("0.05", "0.1"))), [0.05, 0.1]),
])
def test_timeouts_accept_defaults_and_independent_positive_overrides(values, expected):
    result = read_configuration(values)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == expected


@pytest.mark.parametrize("variable", VARIABLES)
@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "invalid", ""])
def test_invalid_timeouts_fail_startup_with_variable_name(variable, value):
    result = read_configuration({variable: value})
    assert result.returncode != 0
    assert variable in result.stderr and "positive number" in result.stderr
