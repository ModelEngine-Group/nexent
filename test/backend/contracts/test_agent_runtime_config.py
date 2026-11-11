# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""AC-001: actual configuration executes in an isolated module namespace."""

import runpy
from pathlib import Path

import pytest

CONFIGURATION = Path(__file__).resolve().parents[3] / "backend/contracts/constants/environment.py"


@pytest.mark.parametrize(
    "value,expected",
    [(None, "codeagent"), ("codeagent", "codeagent"), ("toolcalling", "toolcalling")],
)
def test_ac001_runtime_environment_selection(monkeypatch, value, expected):
    monkeypatch.delenv("NEXENT_AGENT_RUNTIME", raising=False)
    if value is not None:
        monkeypatch.setenv("NEXENT_AGENT_RUNTIME", value)
    settings = runpy.run_path(str(CONFIGURATION), run_name="contracts.constants._runtime_test")
    assert settings["NEXENT_AGENT_RUNTIME"] == expected


@pytest.mark.parametrize("value", ["", "unknown", "ToolCalling"])
def test_ac001_invalid_runtime_fails_at_configuration_boundary(monkeypatch, value):
    monkeypatch.setenv("NEXENT_AGENT_RUNTIME", value)
    with pytest.raises(
        ValueError, match="NEXENT_AGENT_RUNTIME must be codeagent or toolcalling"
    ):
        runpy.run_path(str(CONFIGURATION), run_name="contracts.constants._runtime_test")
