# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import logging.config
import sys
import warnings
from runpy import run_module
from types import ModuleType, SimpleNamespace

import dotenv
import pytest
import uvicorn

from backend.http import logging as service_logging


@pytest.fixture
def startup(mocker):
    config = {"version": 1}
    return SimpleNamespace(
        config=config,
        load_env=mocker.patch.object(dotenv, "load_dotenv"),
        uvicorn_config=mocker.patch.object(service_logging, "get_uvicorn_logging_config", return_value=config),
        configure_logging=mocker.patch.object(logging.config, "dictConfig"),
        configure_elasticsearch=mocker.patch.object(service_logging, "configure_elasticsearch_logging"),
        serve=mocker.patch.object(uvicorn, "run"),
    )


@pytest.mark.parametrize(
    "service,port,categories",
    [("management", 5010, ["config"]), ("runtime", 5014, ["runtime", "model_call"])],
)
@pytest.mark.parametrize("execute", [False, True], ids=["import", "module-entrypoint"])
def test_launcher_initializes_logging_and_only_serves_as_main(monkeypatch, startup, service, port, categories, execute):
    application = ModuleType(f"{service}.api.application")
    application.app = object()
    monkeypatch.setitem(sys.modules, application.__name__, application)

    with warnings.catch_warnings():
        run_module(f"{service}.launcher", run_name="__main__" if execute else None, alter_sys=True)

    startup.load_env.assert_called_once_with()
    startup.configure_logging.assert_called_once_with(startup.config)
    startup.configure_elasticsearch.assert_called_once_with()
    assert startup.uvicorn_config.call_count == (2 if execute else 1)
    assert all(call.kwargs == {"categories": categories} for call in startup.uvicorn_config.call_args_list)
    if execute:
        startup.serve.assert_called_once_with(
            application.app, host="0.0.0.0", port=port, log_level="info", log_config=startup.config,
        )
    else:
        startup.serve.assert_not_called()
