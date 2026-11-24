# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import sys
from types import ModuleType

import pytest

from management.services.knowledge_base import deletion


@pytest.fixture
def worker_settings(monkeypatch):
    monkeypatch.setattr(deletion, "REDIS_URL", "redis://broker.invalid:6379/0")
    monkeypatch.setattr(deletion, "REDIS_BACKEND_URL", "redis://results.invalid:6379/1")


@pytest.fixture
def celery_constructor(monkeypatch, mocker):
    module = ModuleType("celery")
    module.Celery = mocker.Mock()
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return module.Celery


def test_worker_control_uses_the_configured_broker_and_backend(worker_settings, celery_constructor):
    result = deletion._create_worker_control()

    assert result is celery_constructor.return_value
    celery_constructor.assert_called_once_with(
        "nexent",
        broker="redis://broker.invalid:6379/0",
        backend="redis://results.invalid:6379/1",
        broker_transport_options={"master_name": "mymaster"},
    )


@pytest.mark.parametrize("setting", ["REDIS_URL", "REDIS_BACKEND_URL"])
def test_worker_control_requires_both_redis_settings(monkeypatch, worker_settings, celery_constructor, setting):
    monkeypatch.setattr(deletion, setting, "")

    assert deletion._create_worker_control() is None
    celery_constructor.assert_not_called()


def test_worker_control_is_optional_without_celery(monkeypatch, worker_settings):
    monkeypatch.setitem(sys.modules, "celery", None)

    assert deletion._create_worker_control() is None
