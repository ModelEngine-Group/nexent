# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Deployment defaults and explicit overrides for independent Ops storage."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def settings(overrides, *, validate_startup=False):
    root = Path(__file__).resolve().parents[3]
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME"}}
    env.update(PYTHON_DOTENV_DISABLED="1", PYTHONPATH=os.pathsep.join((str(root), str(root / "backend"))), **overrides)
    return subprocess.run([sys.executable, "-c", """
import json
import sys
from contracts.constants import environment as e
print(json.dumps([e.OPS_MONITORING_ENABLED, e.OPS_POSTGRES_DB, e.POSTGRES_HOST, e.POSTGRES_PORT,
                  e.POSTGRES_USER, e.NEXENT_POSTGRES_PASSWORD == 'override-secret',
                  any(hasattr(e, 'OPS_POSTGRES_' + suffix) for suffix in ('HOST','PORT','USER','PASSWORD'))]))
if sys.argv[1] == 'validate':
    from infrastructure.monitoring.store import monitoring_engine
    monitoring_engine()
""", "validate" if validate_startup else "settings"], env=env, cwd=root, capture_output=True, text=True, timeout=20)


@pytest.mark.parametrize("overrides,expected", [
    ({}, [True, "nexent_ops", None, None, None, False, False]),
    ({"POSTGRES_HOST": "pg", "POSTGRES_PORT": "6543", "POSTGRES_USER": "owner", "POSTGRES_DB": "app",
      "NEXENT_POSTGRES_PASSWORD": "override-secret"}, [True, "app_ops", "pg", "6543", "owner", True, False]),
    ({"POSTGRES_DB": "app", "OPS_POSTGRES_DB": "", "OPS_MONITORING_ENABLED": ""},
     [True, "app_ops", None, None, None, False, False]),
    ({"POSTGRES_DB": "app", "POSTGRES_HOST": "pg", "POSTGRES_USER": "owner", "OPS_POSTGRES_DB": "operations"},
     [True, "operations", "pg", None, "owner", False, False]),
    ({"OPS_MONITORING_ENABLED": "false", "OPS_POSTGRES_DB": "nexent"},
     [False, "nexent", None, None, None, False, False]),
])
def test_monitoring_configuration_defaults_and_overrides(overrides, expected):
    result = settings(overrides)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == expected


@pytest.mark.parametrize("overrides", [
    {"POSTGRES_DB": "shared", "OPS_POSTGRES_DB": "shared"},
    {"OPS_POSTGRES_DB": "o" * 64},
    {"OPS_POSTGRES_DB": "数" * 22},
])
def test_invalid_ops_database_configuration_fails_before_startup(overrides):
    result = settings({"POSTGRES_HOST": "pg", "POSTGRES_USER": "owner", **overrides}, validate_startup=True)
    assert result.returncode != 0
    assert "ValueError" in result.stderr


def test_control_store_reuses_the_nexent_connection(monkeypatch):
    from infrastructure.monitoring import store
    from ops.monitoring import runtime

    values = {"POSTGRES_HOST": "shared-pg", "POSTGRES_PORT": "6543", "POSTGRES_USER": "shared-owner",
              "NEXENT_POSTGRES_PASSWORD": "shared-password", "POSTGRES_DB": "nexent", "OPS_POSTGRES_DB": "nexent_ops"}
    for name, value in values.items():
        monkeypatch.setattr(store, name, value)
    engine, calls = object(), []

    def create(url, **options):
        calls.append(url)
        return engine

    monkeypatch.setattr(store, "create_engine", create)
    monkeypatch.setattr(runtime, "ControlStore", lambda value: value)
    assert runtime.control_store() is engine
    assert (calls[0].host, calls[0].port, calls[0].username, calls[0].password, calls[0].database) == (
        "shared-pg", 6543, "shared-owner", "shared-password", "nexent_ops",
    )
