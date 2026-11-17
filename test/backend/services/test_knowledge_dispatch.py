# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime owns discovery and shutdown without replaying failed uploads."""

import asyncio
import logging
from contextlib import contextmanager
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from nexent.storage.errors import InvalidInput, Unavailable
from runtime.knowledge_base import dispatch


@pytest.fixture
def cycle(mocker):
    events = []
    rows = [
        {"job_id": char * 32, "tenant_id": "tenant-" + char, "user_id": "user-" + char,
         "knowledge_id": 1, "file_id": char * 32, "file_version": 0, "operation": "upload"}
        for char in ("a", "b")
    ]
    records = Mock()
    records.query.return_value.items = rows

    @contextmanager
    def ports(*, context):
        try:
            yield records
        finally:
            events.append("discovery-closed")

    async def blocking(_name, action, *args, **kwargs):
        assert kwargs.pop("lane") == "control-io"
        assert kwargs.pop("owner") == "runtime.knowledge_base"
        return action(*args, **kwargs)

    mocker.patch.object(dispatch, "knowledge_dispatch_ports", ports)
    mocker.patch.object(dispatch, "run_blocking", blocking)
    worker = SimpleNamespace(process=AsyncMock(), operation_seconds=30)

    async def execute(*args, **kwargs):
        assert events == ["discovery-closed"]

    worker.process.side_effect = execute
    workers = {"upload": worker, "delete": SimpleNamespace(process=AsyncMock(), operation_seconds=30)}
    return SimpleNamespace(**locals())


async def test_discovery_closes_before_execution_and_preserves_both_actors(cycle):
    s = cycle
    assert await dispatch.dispatch_once(s.workers, owner_id="owner", stop=Event()) == 2
    assert s.records.query.call_args.args[2].limit == 100
    calls = s.worker.process.call_args_list
    assert [c.args[1].tenant_id for c in calls] == ["tenant-a", "tenant-b"]
    assert [c.args[1].user_id for c in calls] == ["user-a", "user-b"]
    assert [c.args[0].job_id for c in calls] == ["a" * 32, "b" * 32]
    assert all(c.kwargs["owner_id"] == "owner" for c in calls)


async def test_stop_between_jobs_does_not_start_next_upload(cycle):
    stop = Event()
    cycle.worker.process.side_effect = lambda *a, **kw: stop.set()
    assert await dispatch.dispatch_once(cycle.workers, owner_id="owner", stop=stop) == 1
    cycle.worker.process.assert_awaited_once()


async def test_scan_error_exits_without_execution_or_retry(cycle):
    cycle.records.query.side_effect = Unavailable()
    with pytest.raises(Unavailable):
        await dispatch.serve(cycle.workers, owner_id="owner", stop=Event())
    cycle.records.query.assert_called_once()
    cycle.worker.process.assert_not_awaited()


async def test_upload_error_exits_without_retry_or_next_job(cycle):
    cycle.worker.process.side_effect = Unavailable()
    with pytest.raises(Unavailable):
        await dispatch.serve(cycle.workers, owner_id="owner", stop=Event())
    cycle.records.query.assert_called_once()
    cycle.worker.process.assert_awaited_once()


@pytest.mark.parametrize("owner,seconds", [("", 1), ("a" * 101, 1), ("owner", True),
                                           ("owner", 0), ("owner", float("nan"))])
async def test_invalid_root_parameters_never_open_storage(cycle, owner, seconds):
    with pytest.raises(InvalidInput):
        await dispatch.serve(cycle.workers, owner_id=owner, stop=Event(), poll_seconds=seconds)
    cycle.records.query.assert_not_called()


async def test_stopped_root_never_opens_storage(cycle):
    stop = Event()
    stop.set()
    assert await dispatch.dispatch_once(cycle.workers, owner_id="owner", stop=stop) == 0
    cycle.records.query.assert_not_called()


async def test_lifespan_owns_task_and_cancels_active_worker(cycle):
    app = SimpleNamespace(state=SimpleNamespace())
    started, finished = asyncio.Event(), asyncio.Event()
    cancellation = []

    async def execute(*args, **kwargs):
        cancellation.append(kwargs["context"].cancelled)
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            assert cancellation[0].is_set()
            finished.set()

    cycle.worker.process.side_effect = execute
    async with dispatch.knowledge_lifespan(app, workers=cycle.workers):
        await asyncio.wait_for(started.wait(), 2)
        owned = app.state.required_background_tasks
        assert len(owned) == 1 and not owned[0].done()
    assert finished.is_set() and owned[0].done()
    assert app.state.required_background_tasks == ()
    cycle.worker.process.assert_awaited_once()


async def test_failed_lifespan_task_stays_failed_without_restart(cycle, caplog):
    app = SimpleNamespace(state=SimpleNamespace())
    cycle.worker.process.side_effect = RuntimeError("private-secret")
    with caplog.at_level(logging.WARNING):
        async with dispatch.knowledge_lifespan(app, workers=cycle.workers):
            task, = app.state.required_background_tasks
            await asyncio.wait({task}, timeout=2)
            assert task.done() and isinstance(task.exception(), RuntimeError)
            await asyncio.sleep(0)
            cycle.worker.process.assert_awaited_once()
    assert "knowledge_dispatch_failed" in caplog.text
    assert "private-secret" not in caplog.text


def test_default_worker_reuses_existing_limits_and_model_authority(mocker):
    from contracts.constants import environment
    from runtime.knowledge_base import composition as knowledge

    service = SimpleNamespace(client=Mock(), models=Mock())
    mocker.patch.object(knowledge, "default_service", return_value=service)
    mocker.patch.object(environment, "MAX_KNOWLEDGE_FILE_SIZE_BYTES", 12345)
    mocker.patch.object(environment, "MAX_TIMEOUT", 3600)
    workers = dispatch.default_workers()
    worker = workers["upload"]
    assert worker.client is service.client and worker.models is service.models
    assert worker.operation_seconds == 3600
    assert worker.max_artifact_bytes == worker.max_source_bytes == 12345
    assert workers["delete"].client is service.client
    assert workers["delete"].operation_seconds == 3600


async def test_dispatch_selects_delete_worker_from_trusted_metadata(cycle):
    cycle.rows[1]["operation"] = "delete"
    assert await dispatch.dispatch_once(cycle.workers, owner_id="owner", stop=Event()) == 2
    cycle.worker.process.assert_awaited_once()
    deletion = cycle.workers["delete"].process
    deletion.assert_awaited_once()
    assert deletion.call_args.args[0].job_id == "b" * 32
    assert deletion.call_args.args[1].user_id == "user-b"
