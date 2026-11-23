# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Ops worker startup, retry and owned-resource cleanup contracts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from ops.monitoring import runtime


@pytest.fixture
def resources(mocker):
    mocker.patch.object(runtime, "OPS_MONITORING_ENABLED", True)
    mocker.patch.object(runtime, "ES_HOST", "http://es:9200")
    mocker.patch.object(runtime, "OPS_MONITORING_TIMEZONE", "UTC")
    store = mocker.patch.object(runtime, "control_store").return_value
    es = mocker.patch.object(runtime, "Elasticsearch").return_value
    install = mocker.patch.object(runtime, "install_templates")
    monitoring = mocker.patch.object(runtime, "Monitoring").return_value
    worker = mocker.patch.object(runtime, "start_worker")
    worker.return_value.shutdown = AsyncMock()
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()), store=store, es=es,
                           install=install, monitoring=monitoring, worker=worker)


def test_control_store_uses_dedicated_monitoring_engine(mocker):
    engine = mocker.patch.object(runtime, "monitoring_engine").return_value
    assert runtime.control_store().engine is engine


@pytest.mark.asyncio
async def test_disabled_monitoring_opens_no_resources(resources, mocker):
    mocker.patch.object(runtime, "OPS_MONITORING_ENABLED", False)
    async with runtime.ops_monitoring_lifespan(resources.app):
        assert not hasattr(resources.app.state, "monitoring")
    runtime.control_store.assert_not_called()
    runtime.Elasticsearch.assert_not_called()
    resources.worker.assert_not_called()


@pytest.mark.asyncio
async def test_missing_es_configuration_fails_before_opening_database(resources, mocker):
    mocker.patch.object(runtime, "ES_HOST", "")
    with pytest.raises(RuntimeError, match="Elasticsearch endpoint"):
        async with runtime.ops_monitoring_lifespan(resources.app):
            pytest.fail("Invalid monitoring configuration must fail startup")
    runtime.control_store.assert_not_called()
    runtime.Elasticsearch.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["schema", "template", "worker"])
async def test_startup_failure_releases_es_and_database(resources, failure):
    target = {"schema": resources.store.verify_schema, "template": resources.install,
              "worker": resources.worker}[failure]
    target.side_effect = RuntimeError("startup failed")
    with pytest.raises(RuntimeError, match="startup failed"):
        async with runtime.ops_monitoring_lifespan(resources.app):
            pytest.fail("Failed startup must not enter the application")
    resources.es.close.assert_called_once()
    resources.store.engine.dispose.assert_called_once()
    resources.worker.return_value.shutdown.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("body_error", [False, True])
async def test_active_worker_is_stopped_before_owned_clients_close(resources, body_error):
    events = []

    async def shutdown(*, timeout):
        assert timeout == 12
        events.append("worker")

    resources.worker.return_value.shutdown.side_effect = shutdown
    resources.es.close.side_effect = lambda: events.append("es")
    resources.store.engine.dispose.side_effect = lambda: events.append("database")

    async def run():
        async with runtime.ops_monitoring_lifespan(resources.app):
            assert resources.app.state.monitoring is resources.monitoring
            resources.store.verify_schema.assert_called_once()
            resources.install.assert_called_once()
            if body_error:
                raise ValueError("application failed")

    if body_error:
        with pytest.raises(ValueError, match="application failed"):
            await run()
    else:
        await run()
    assert events == ["worker", "es", "database"]


@pytest.mark.asyncio
async def test_worker_retries_failed_cycle_and_observes_cancellation(resources, caplog):
    resources.monitoring.tick.side_effect = [RuntimeError("transient"), None]
    cancelled = MagicMock()
    cancelled.is_set.side_effect = [False, False, True]
    async with runtime.ops_monitoring_lifespan(resources.app):
        name, callback = resources.worker.call_args.args
        assert name == "ops-monitoring"
        callback(cancelled)
    assert resources.monitoring.tick.call_count == 2
    assert cancelled.wait.call_count == 2
    cancelled.wait.assert_called_with(1)
    assert "Ops monitoring cycle failed error=RuntimeError" in caplog.text
