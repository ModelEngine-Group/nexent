# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Only the Ops entrypoint owns Ops SQL initialization."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


def launch(tmp_path, mode, enabled=None, *, ops_entry=False, missing_ops_helper=False, **failures):
    root = Path(__file__).resolve().parents[3]
    name = "start-ops.sh" if ops_entry else "start-backend.sh"
    shutil.copy(root / "deploy/common" / name, tmp_path / name)
    for kind, helper in (("main", "run-sql-migrations.sh"), ("ops", "run-ops-sql-migrations.sh")):
        if kind == "ops" and missing_ops_helper:
            continue
        (tmp_path / helper).write_text(
            f'#!/usr/bin/env bash\nprintf "{kind}:%s\\n" "$1" >> "$BOOTSTRAP_LOG"\nexit "${{FAIL_{kind.upper()}:-0}}"\n',
            encoding="utf-8",
        )
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("OPS_", "NEXENT_SQL_", "FAIL_")) and key != "UMASK"}
    env.update(NEXENT_SQL_STARTUP_MODE=mode, BOOTSTRAP_LOG=str(tmp_path / "calls"), **failures)
    if enabled is not None:
        env["OPS_MONITORING_ENABLED"] = enabled
    bash = shutil.which("bash")
    assert bash, "Bash is required for the deployment entrypoint regression"
    result = subprocess.run([bash, str(tmp_path / name), bash, "-c",
                             'printf "APP\\n" >> "$BOOTSTRAP_LOG"'], env=env, capture_output=True, text=True, timeout=10)
    log = tmp_path / "calls"
    return result, log.read_text().splitlines() if log.exists() else []


@pytest.mark.parametrize("mode,enabled,expected", [
    ("migrate", None, ["main:--migrate", "APP"]),
    ("wait", None, ["main:--wait", "APP"]),
    ("off", None, ["APP"]),
    ("off", "", ["APP"]),
    ("off", "TRUE", ["APP"]),
    ("off", "false", ["APP"]),
    ("migrate", "false", ["main:--migrate", "APP"]),
    ("wait", "false", ["main:--wait", "APP"]),
])
def test_generic_launcher_only_runs_business_sql(tmp_path, mode, enabled, expected):
    result, calls = launch(tmp_path, mode, enabled)
    assert result.returncode == 0, result.stderr
    assert calls == expected


@pytest.mark.parametrize("mode", ["off", "migrate", "wait"])
@pytest.mark.parametrize("enabled", [None, "true", "TRUE", "false"])
def test_ops_entrypoint_initializes_its_own_storage_only(tmp_path, mode, enabled):
    result, calls = launch(tmp_path, mode, enabled, ops_entry=True)
    assert result.returncode == 0, result.stderr
    assert calls == (["APP"] if enabled == "false" else ["ops:--migrate", "APP"])


@pytest.mark.parametrize("ops_entry,failures", [
    (False, {"FAIL_MAIN": "17"}), (True, {"FAIL_OPS": "19"}),
])
def test_migration_failure_prevents_application_launch(tmp_path, ops_entry, failures):
    result, calls = launch(tmp_path, "migrate", ops_entry=ops_entry, **failures)
    assert result.returncode != 0
    assert "APP" not in calls


def test_invalid_startup_mode_does_not_run_any_migration(tmp_path):
    result, calls = launch(tmp_path, "invalid")
    assert result.returncode != 0
    assert calls == []


@pytest.mark.parametrize("mode,expected", [
    ("off", ["APP"]),
    ("migrate", ["main:--migrate", "APP"]),
    ("wait", ["main:--wait", "APP"]),
])
def test_generic_launcher_needs_no_ops_helper_when_monitoring_is_enabled(tmp_path, mode, expected):
    result, calls = launch(tmp_path, mode, "true", missing_ops_helper=True)
    assert result.returncode == 0, result.stderr
    assert calls == expected
    assert not (tmp_path / "run-ops-sql-migrations.sh").exists()


def test_ops_still_requires_its_migration_helper(tmp_path):
    result, calls = launch(tmp_path, "off", "true", ops_entry=True, missing_ops_helper=True)
    assert result.returncode != 0
    assert "run-ops-sql-migrations.sh" in result.stderr
    assert calls == []


@pytest.mark.parametrize("ops_entry", [False, True])
@pytest.mark.parametrize("umask", ["invalid", "9999"])
def test_invalid_umask_prevents_migrations_and_application(tmp_path, ops_entry, umask):
    result, calls = launch(tmp_path, "migrate", ops_entry=ops_entry, UMASK=umask)
    assert result.returncode != 0
    assert calls == []
