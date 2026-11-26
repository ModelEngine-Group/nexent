# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Search admission, bounded fan-out, deadlines and cancellation contracts."""
import ast
import asyncio
import os
import time
from pathlib import Path
from threading import BoundedSemaphore, Lock

import pytest

from contracts.constants import environment
from contracts.configuration import parse_positive_int
from management.services.conversation import nl2agent_resource_index as storage


def budget(seconds=2):
    deadline = time.monotonic() + seconds

    def remaining():
        value = deadline - time.monotonic()
        if value <= 0:
            raise TimeoutError("Search budget exhausted")
        return value

    return remaining


@pytest.fixture(autouse=True)
def reset_gate(monkeypatch):
    monkeypatch.setattr(storage, "_PROCESS_SEARCH_GATE", BoundedSemaphore(8), raising=False)


def test_search_defaults_are_positive_and_eight():
    assert environment.NL2AGENT_ES_SEARCH_CONCURRENCY == 8
    assert environment.NL2AGENT_ES_PROCESS_SEARCH_CONCURRENCY == 8


@pytest.mark.parametrize("value", ["1", "3", "16", "0", "-1", "bad", ""])
def test_search_config_overrides_are_validated(monkeypatch, value):
    names = ["NL2AGENT_ES_SEARCH_CONCURRENCY", "NL2AGENT_ES_PROCESS_SEARCH_CONCURRENCY"]
    for name in names:
        monkeypatch.setenv(name, value)
    tree = ast.parse(Path(environment.__file__).read_text(encoding="utf-8"))
    assignments = [node for node in tree.body if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id in names for target in node.targets)]
    assert len(assignments) == 2
    code = compile(ast.Module(body=assignments, type_ignores=[]), environment.__file__, "exec")
    namespace = {"os": os, "parse_positive_int": parse_positive_int}
    if value in ("1", "3", "16"):
        exec(code, namespace)
        assert all(namespace[name] == int(value) for name in names)
    else:
        with pytest.raises(ValueError, match="positive integer"):
            exec(code, namespace)


async def test_one_recommendation_runs_eight_searches_and_keeps_all_jobs():
    operation = storage.map_search_jobs
    active = peak = 0
    reached = asyncio.Event()
    release = asyncio.Event()
    consumed = []

    def jobs():
        for job in range(24):
            consumed.append(job)
            yield job

    async def search(job):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if active == 8:
            reached.set()
        try:
            await release.wait()
            return job * 2
        finally:
            active -= 1

    task = asyncio.create_task(operation(jobs(), search, budget()))
    try:
        await asyncio.wait_for(reached.wait(), .5)
        assert peak == 8
        assert consumed == list(range(8))
    finally:
        release.set()
        values = await task
    assert active == 0
    assert sorted(values) == [(n, n * 2) for n in range(24)]


async def test_multiple_recommendations_share_one_process_cap():
    operation = storage.map_search_jobs
    active = peak = 0
    reached = asyncio.Event()
    release = asyncio.Event()

    async def search(job):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if active == 8:
            reached.set()
        try:
            await release.wait()
            return job
        finally:
            active -= 1

    tasks = [asyncio.create_task(operation(iter(range(16)), search, budget())) for _ in range(3)]
    try:
        await asyncio.wait_for(reached.wait(), .5)
        await asyncio.sleep(.02)
        assert active == peak == 8
    finally:
        release.set()
        results = await asyncio.gather(*tasks)
    assert active == 0 and peak == 8
    assert all(sorted(values) == [(n, n) for n in range(16)] for values in results)


@pytest.mark.parametrize("recommendation,process", [(2, 8), (8, 3), (4, 2)])
async def test_configured_recommendation_limit_applies_to_all_jobs(monkeypatch, recommendation, process):
    operation = storage.map_search_jobs
    monkeypatch.setattr(storage, "NL2AGENT_ES_SEARCH_CONCURRENCY", recommendation)
    monkeypatch.setattr(storage, "_PROCESS_SEARCH_GATE", BoundedSemaphore(process))
    active = peak = 0

    async def search(job):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(.005)
            return job
        finally:
            active -= 1

    assert len(await operation(iter(range(20)), search, budget())) == 20
    assert peak == min(recommendation, process) and active == 0


@pytest.mark.parametrize("cancel", [False, True])
async def test_queued_timeout_or_cancel_never_starts_later(monkeypatch, cancel):
    operation = storage.map_search_jobs
    gate = BoundedSemaphore(1)
    gate.acquire()
    monkeypatch.setattr(storage, "_PROCESS_SEARCH_GATE", gate)
    calls = []

    async def search(job):
        calls.append(job)
        return job

    task = asyncio.create_task(operation(iter(["late"]), search, budget(.05 if not cancel else 2)))
    if cancel:
        await asyncio.sleep(.01)
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
        await task
    gate.release()
    await asyncio.sleep(.02)
    assert calls == []
    assert await operation(iter(["fresh"]), search, budget()) == [("fresh", "fresh")]


@pytest.mark.parametrize("cancel", [False, True])
async def test_active_error_or_cancel_drains_workers_and_releases_slots(cancel):
    operation = storage.map_search_jobs
    active = 0
    reached = asyncio.Event()
    fail = asyncio.Event()

    async def search(job):
        nonlocal active
        active += 1
        if active == 8:
            reached.set()
        try:
            if job == 0:
                await fail.wait()
                raise OSError("ES unavailable")
            await asyncio.Event().wait()
        finally:
            active -= 1

    task = asyncio.create_task(operation(iter(range(32)), search, budget()))
    await asyncio.wait_for(reached.wait(), .5)
    if cancel:
        task.cancel()
    else:
        fail.set()
    with pytest.raises(asyncio.CancelledError if cancel else OSError):
        await task
    assert active == 0
    gate = storage._PROCESS_SEARCH_GATE
    try:
        assert all(gate.acquire(blocking=False) for _ in range(8))
        assert not gate.acquire(blocking=False)
    finally:
        for _ in range(8):
            gate.release()


async def test_active_search_deadline_cancels_transport_and_releases_slot():
    operation = storage.map_search_jobs
    cancelled = asyncio.Event()

    async def search(job):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    with pytest.raises(TimeoutError):
        await operation(iter([1]), search, budget(.04))
    assert cancelled.is_set()
    assert storage._PROCESS_SEARCH_GATE.acquire(blocking=False)
    storage._PROCESS_SEARCH_GATE.release()


async def test_process_gate_is_shared_across_managed_worker_event_loops():
    from nexent.core.concurrency import LanePolicy, ManagedTaskSpec, ThreadManager

    operation = storage.map_search_jobs
    manager = ThreadManager(service_name="search-gate-unit", lane_policies={
        "loops": LanePolicy(name="loops", max_workers=2, max_queue_size=0,
                            queue_timeout_seconds=0, cancel_grace_seconds=1, shutdown_grace_seconds=2)})
    manager.start()
    lock = Lock()
    active = peak = 0

    async def search(job):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            await asyncio.sleep(.02)
            return job
        finally:
            with lock:
                active -= 1

    def run():
        return asyncio.run(operation(iter(range(24)), search, budget()))

    try:
        results = await asyncio.gather(*(manager.run("loops", ManagedTaskSpec(
            task_name="cross-loop-search", owner=__name__), run) for _ in range(2)))
        assert all(len(rows) == 24 for rows in results)
        assert active == 0 and peak == 8
    finally:
        await manager.shutdown(timeout=2)
