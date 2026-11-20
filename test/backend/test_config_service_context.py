# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management launch compatibility and request-context isolation wiring."""

import runpy
import sys
from types import ModuleType
from unittest.mock import Mock

import pytest


@pytest.fixture
def launcher(monkeypatch):
    """Execute the real launcher without importing the live application."""
    application = ModuleType("management.api.application")
    application.app = object()
    environment = ModuleType("contracts.constants.environment")
    environment.APP_VERSION = "test-version"
    logging_module = ModuleType("backend.http.logging")
    logging_module.get_uvicorn_logging_config = Mock(return_value={"sentinel": "logging"})
    logging_module.configure_elasticsearch_logging = Mock()
    monkeypatch.setitem(sys.modules, "management.api.application", application)
    monkeypatch.setitem(sys.modules, "contracts.constants.environment", environment)
    monkeypatch.setitem(sys.modules, "backend.http.logging", logging_module)
    monkeypatch.setattr("logging.config.dictConfig", Mock())
    monkeypatch.setattr("dotenv.load_dotenv", Mock())

    def execute(run, name="__main__"):
        monkeypatch.setattr("uvicorn.run", run)
        runpy.run_module("backend.http.config_service", run_name=name)

    return execute, application.app


def test_management_enables_supported_request_context_isolation(launcher):
    execute, app = launcher
    calls = []

    def run(application, *, reset_contextvars=False, **kwargs):
        calls.append((application, reset_contextvars, kwargs))

    execute(run)
    assert calls == [(app, True, {
        "host": "0.0.0.0", "port": 5010, "log_level": "info", "log_config": {"sentinel": "logging"},
    })]


def test_management_preserves_older_uvicorn_call_contract(launcher):
    execute, app = launcher
    calls = []

    def run(application, *, host, port, log_level, log_config):
        calls.append((application, host, port, log_level, log_config))

    execute(run)
    assert calls == [(app, "0.0.0.0", 5010, "info", {"sentinel": "logging"})]


def test_management_does_not_retry_launcher_failure(launcher):
    execute, _ = launcher
    calls = []
    error = TypeError("unrelated server startup failure")

    def run(application, *, reset_contextvars=False, **kwargs):
        calls.append(reset_contextvars)
        raise error

    with pytest.raises(TypeError) as caught:
        execute(run)
    assert caught.value is error
    assert calls == [True]


def test_import_does_not_start_management_server(launcher):
    execute, _ = launcher
    run = Mock()
    execute(run, name="launcher_import_probe")
    run.assert_not_called()
