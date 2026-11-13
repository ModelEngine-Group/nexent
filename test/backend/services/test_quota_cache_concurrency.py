# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Quota refresh coalescing, invalidation races and managed worker cleanup."""

import asyncio
import threading

import pytest

from management.services.knowledge_base import quota_common as common
from management.services.knowledge_base.quota import QuotaService
from nexent.core.concurrency import LanePolicy, ManagedTaskSpec, ThreadManager


@pytest.fixture(autouse=True)
def empty_cache():
    QuotaService.invalidate_usage_cache()
    yield
    QuotaService.invalidate_usage_cache()
    assert common._usage_refresh_locks == {}


@pytest.fixture
async def manager():
    value = ThreadManager(service_name="quota-test", lane_policies={
        "control-io": LanePolicy(name="control-io", max_workers=4, max_queue_size=8),
    })
    value.start()
    yield value
    await value.shutdown(timeout=3)


async def wait_started(event):
    async def check():
        while not event.is_set():
            await asyncio.sleep(0.001)
    await asyncio.wait_for(check(), 3)


@pytest.mark.asyncio
async def test_concurrent_cold_requests_compute_once(manager, mocker):
    started, release = threading.Event(), threading.Event()
    service = QuotaService("a")

    def compute():
        started.set()
        assert release.wait(3)
        return {"total_bytes": 7, "breakdown": [{"actual_bytes": 7}]}

    compute_mock = mocker.patch.object(service, "_compute_usage", side_effect=compute)
    async def request(detail):
        return await manager.run("control-io", ManagedTaskSpec(task_name="quota", owner="test"),
                                 service.get_usage, detail=detail)
    first = asyncio.create_task(request(True))
    await wait_started(started)
    others = [asyncio.create_task(request(False)) for _ in range(3)]
    await asyncio.sleep(0)
    release.set()
    results = await asyncio.gather(first, *others)
    assert results[0] == {"total_bytes": 7, "breakdown": [{"actual_bytes": 7}]}
    assert results[1:] == [{"total_bytes": 7}] * 3
    compute_mock.assert_called_once()


@pytest.mark.asyncio
async def test_invalidation_during_refresh_prevents_stale_publication(manager, mocker):
    started, release = threading.Event(), threading.Event()
    service = QuotaService("a")

    def compute():
        started.set()
        assert release.wait(3)
        return {"total_bytes": 7}

    compute_mock = mocker.patch.object(service, "_compute_usage", side_effect=compute)
    task = asyncio.create_task(manager.run("control-io", ManagedTaskSpec(task_name="quota", owner="test"), service.get_usage))
    await wait_started(started)
    QuotaService.invalidate_usage_cache("a")
    release.set()
    assert await task == {"total_bytes": 7}
    assert "a" not in common._usage_cache
    compute_mock.side_effect = None
    compute_mock.return_value = {"total_bytes": 9}
    assert service.get_usage() == {"total_bytes": 9}
    assert compute_mock.call_count == 2


def test_force_refresh_ttl_and_error_release(mocker):
    service = QuotaService("a")
    clock = mocker.patch("management.services.knowledge_base.usage.time.time", return_value=100)
    compute = mocker.patch.object(service, "_compute_usage", return_value={"total_bytes": 7, "breakdown": []})
    assert service.get_usage() == {"total_bytes": 7}

    clock.return_value = 159
    assert service.get_usage(detail=True) == {"total_bytes": 7, "breakdown": []}
    assert compute.call_count == 1
    clock.return_value = 160
    service.get_usage()
    service.get_usage(force_refresh=True)
    assert compute.call_count == 3
    QuotaService.invalidate_usage_cache("a")
    compute.side_effect = RuntimeError("stats unavailable")
    with pytest.raises(RuntimeError, match="stats unavailable"):
        service.get_usage()
    assert common._usage_refresh_locks == {}
    compute.side_effect = None
    assert service.get_usage() == {"total_bytes": 7}


@pytest.mark.asyncio
async def test_refresh_for_another_tenant_is_not_serialized(manager, mocker):
    started, release = threading.Event(), threading.Event()
    first, other = QuotaService("a"), QuotaService("b")

    def compute():
        started.set()
        assert release.wait(3)
        return {"total_bytes": 1}

    mocker.patch.object(first, "_compute_usage", side_effect=compute)
    mocker.patch.object(other, "_compute_usage", return_value={"total_bytes": 2})
    task = asyncio.create_task(manager.run("control-io", ManagedTaskSpec(task_name="quota", owner="test"), first.get_usage))
    await wait_started(started)
    try:
        response = await asyncio.wait_for(manager.run(
            "control-io", ManagedTaskSpec(task_name="quota-other", owner="test"), other.get_usage,
        ), 1)
        assert response == {"total_bytes": 2}
        assert not task.done()
    finally:
        release.set()
    assert await task == {"total_bytes": 1}
