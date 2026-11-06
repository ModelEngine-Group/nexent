# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Environment exclusion defaults and both backend bootstrap import paths."""

import importlib.util
from pathlib import Path
import runpy
import sys

import pytest

from nexent.monitor import MonitoringConfig


ROOT = Path(__file__).resolve().parents[3]
ES_KEY = "MONITORING_EXCLUDED_ELASTICSEARCH_OPERATIONS"
NAMES_KEY = "MONITORING_EXCLUDED_SPAN_NAMES"
DEFAULT_OPERATIONS = [
    "search", "indices.stats", "indices.get_settings", "indices.get_alias",
    "bulk", "indices.exists", "indices.delete",
]
DEFAULT_NAMES = ["knowledge.process.submit", "knowledge.upload.batch"]


@pytest.mark.parametrize("fallback", [False, True])
@pytest.mark.parametrize("values,expected_es,expected_names", [
    ({}, DEFAULT_OPERATIONS, DEFAULT_NAMES),
    ({ES_KEY: " indices.refresh , , indices.refresh ", NAMES_KEY: " custom.step ,custom.step"},
     ["indices.refresh"], ["custom.step"]),
    ({ES_KEY: "", NAMES_KEY: ""}, [], []),
    ({ES_KEY: ""}, [], DEFAULT_NAMES),
    ({NAMES_KEY: ""}, DEFAULT_OPERATIONS, []),
])
def test_environment_reaches_sdk_configuration(
    mocker, monkeypatch, fallback, values, expected_es, expected_names,
):
    mocker.patch("dotenv.load_dotenv")
    monkeypatch.delenv(ES_KEY, raising=False)
    monkeypatch.delenv(NAMES_KEY, raising=False)
    monkeypatch.setenv("ENABLE_TELEMETRY", "false")
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    spec = importlib.util.spec_from_file_location("contracts.constants._exclusion_environment", ROOT / "backend/contracts/constants/environment.py")
    constants = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(constants)
    for key in (ES_KEY, NAMES_KEY):
        if key in values:
            assert getattr(constants, key) == values[key]

    monkeypatch.setitem(sys.modules, "contracts.constants.environment", None if fallback else constants)
    monkeypatch.setitem(sys.modules, "backend.contracts.constants.environment", constants)
    get_manager = mocker.patch("nexent.monitor.get_monitoring_manager")
    runpy.run_path(str(ROOT / "backend/infrastructure/observability/bootstrap.py"))
    get_manager.return_value.configure.assert_called_once()
    config, = get_manager.return_value.configure.call_args.args
    assert isinstance(config, MonitoringConfig)
    assert config.excluded_elasticsearch_operations == expected_es
    assert config.excluded_span_names == expected_names


def test_monitoring_example_matches_backend_and_sdk_defaults():
    lines = (ROOT / "deploy/env/monitoring.env.example").read_text().splitlines()
    entries = dict(line.split("=", 1) for line in lines if line and not line.startswith("#"))
    config = MonitoringConfig()
    assert entries[ES_KEY].split(",") == config.excluded_elasticsearch_operations == DEFAULT_OPERATIONS
    assert entries[NAMES_KEY].split(",") == config.excluded_span_names == DEFAULT_NAMES
