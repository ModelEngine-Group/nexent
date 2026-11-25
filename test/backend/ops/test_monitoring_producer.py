# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Shared ingestion remains independent of Ops and preserves retry/lifetime contracts."""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

import pytest


ROOT = Path(__file__).resolve().parents[3]


def test_application_factory_and_producer_import_without_service_implementations():
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join(
        (str(ROOT), str(ROOT / "backend"), str(ROOT / "sdk"), os.environ.get("PYTHONPATH", "")))}
    result = subprocess.run([sys.executable, "-c", """
import importlib.abc
import sys
class RejectServices(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'ops', 'management', 'runtime'}:
            raise AssertionError('Shared code imported ' + fullname)
sys.meta_path.insert(0, RejectServices())
from backend.http.server.app_factory import create_app
from infrastructure.monitoring.runtime import Producer
assert create_app()
assert Producer.__module__ == 'infrastructure.monitoring.runtime'
"""], cwd=ROOT, env=environment, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_producer_retries_the_same_batch_before_draining_next_events():
    from infrastructure.monitoring.contracts import Fact
    from infrastructure.monitoring.runtime import Producer

    store = Mock()
    store.enqueue.side_effect = [RuntimeError("unavailable"), None]
    producer = Producer(store, ZoneInfo("UTC"), {"skill": Fact})
    producer.emit(dict(tenant_id="t", fact_kind="skill", fact_id="f", call_context_id="c",
                       started_at="2026-11-23T00:00:00Z", record_revision=1, outcome="started"))
    cancelled = Mock()
    cancelled.wait.side_effect = [False, False, True]
    cancelled.is_set.return_value = False
    producer.run(cancelled)
    assert store.enqueue.call_count == 2
    assert store.enqueue.call_args_list[0] == store.enqueue.call_args_list[1]
    assert producer.queue.empty()


@pytest.mark.parametrize("failed", [False, True])
def test_shutdown_drains_queued_events_and_reports_storage_failure(failed, caplog):
    from infrastructure.monitoring.contracts import Fact
    from infrastructure.monitoring.runtime import Producer

    store = Mock()
    if failed:
        store.enqueue.side_effect = RuntimeError("unavailable")
    producer = Producer(store, ZoneInfo("UTC"), {"skill": Fact})
    producer.emit(dict(tenant_id="t", fact_kind="skill", fact_id="f", call_context_id="c",
                       started_at="2026-11-23T00:00:00Z", record_revision=1, outcome="started"))
    cancelled = Mock()
    cancelled.wait.return_value = True
    producer.run(cancelled)
    store.enqueue.assert_called_once()
    assert ("shutdown drain failed" in caplog.text) is failed


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("body_failed", [False, True])
async def test_producer_lifetime_owns_sink_and_resources(monkeypatch, enabled, body_failed):
    from infrastructure.monitoring import runtime
    from nexent.monitor.facts import get_fact_sink

    monkeypatch.setattr(runtime, "OPS_MONITORING_ENABLED", enabled)
    engine, store, manager = Mock(), Mock(), Mock(shutdown=AsyncMock())
    create = Mock(return_value=engine)
    start = Mock(return_value=manager)
    monkeypatch.setattr(runtime, "monitoring_engine", create)
    monkeypatch.setattr(runtime, "BatchStore", Mock(return_value=store))
    monkeypatch.setattr(runtime, "start_worker", start)
    try:
        async with runtime.producer_lifespan():
            if enabled:
                get_fact_sink()(dict(tenant_id="t", model_type="llm", fact_id="f", call_context_id="c",
                                     fact_kind="model", started_at="2026-11-23T00:00:00Z",
                                     record_revision=1, outcome="started"))
                assert start.call_args.args[1].__self__.queue.qsize() == 1
            if body_failed:
                raise RuntimeError("business startup failed")
    except RuntimeError as error:
        assert body_failed and str(error) == "business startup failed"
    if enabled:
        assert get_fact_sink() is None
        manager.shutdown.assert_awaited_once_with(timeout=8)
        store.engine.dispose.assert_called_once()
    else:
        create.assert_not_called()
        start.assert_not_called()
