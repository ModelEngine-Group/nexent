# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Shared launcher orders independent Ops migrations before application startup."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


def launch(tmp_path, mode, enabled=None, **failures):
    root = Path(__file__).resolve().parents[3]
    shutil.copy(root / "deploy/common/start-backend.sh", tmp_path / "start-backend.sh")
    for kind, name in (("main", "run-sql-migrations.sh"), ("ops", "run-ops-sql-migrations.sh")):
        (tmp_path / name).write_text(
            f'#!/usr/bin/env bash\nprintf "{kind}:%s\\n" "$1" >> "$BOOTSTRAP_LOG"\nexit "${{FAIL_{kind.upper()}:-0}}"\n',
            encoding="utf-8",
        )
    env = {key: value for key, value in os.environ.items() if not key.startswith(("OPS_", "NEXENT_SQL_", "FAIL_"))}
    env.update(NEXENT_SQL_STARTUP_MODE=mode, BOOTSTRAP_LOG=str(tmp_path / "calls"), **failures)
    if enabled is not None:
        env["OPS_MONITORING_ENABLED"] = enabled
    bash = shutil.which("bash")
    assert bash, "Bash is required for the deployment entrypoint regression"
    result = subprocess.run([bash, str(tmp_path / "start-backend.sh"), bash, "-c",
                             'printf "APP\\n" >> "$BOOTSTRAP_LOG"'], env=env, capture_output=True, text=True, timeout=10)
    log = tmp_path / "calls"
    return result, log.read_text().splitlines() if log.exists() else []


@pytest.mark.parametrize("mode,enabled,expected", [
    ("migrate", None, ["main:--migrate", "ops:--migrate", "APP"]),
    ("wait", None, ["main:--wait", "ops:--wait", "APP"]),
    ("off", None, ["ops:--migrate", "APP"]),
    ("off", "", ["ops:--migrate", "APP"]),
    ("off", "TRUE", ["ops:--migrate", "APP"]),
    ("off", "false", ["APP"]),
    ("migrate", "false", ["main:--migrate", "APP"]),
    ("wait", "false", ["main:--wait", "APP"]),
])
def test_launcher_initializes_or_waits_for_ops_before_application(tmp_path, mode, enabled, expected):
    result, calls = launch(tmp_path, mode, enabled)
    assert result.returncode == 0, result.stderr
    assert calls == expected


@pytest.mark.parametrize("failures", [{"FAIL_MAIN": "17"}, {"FAIL_OPS": "19"}])
def test_migration_failure_prevents_application_launch(tmp_path, failures):
    result, calls = launch(tmp_path, "migrate", **failures)
    assert result.returncode != 0
    assert "APP" not in calls


def test_invalid_startup_mode_does_not_run_any_migration(tmp_path):
    result, calls = launch(tmp_path, "invalid")
    assert result.returncode != 0
    assert calls == []
