# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""One execution clock supplies immutable values without a telemetry dependency."""

import builtins
import importlib.util
import sys
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from unittest.mock import Mock

import pytest

from nexent.core.concurrency import LanePolicy, ManagedTaskSpec, ThreadManager
from nexent.monitor.run_timing import RunTiming


BASE = datetime(2026, 11, 19, 23, 59, 59, 123456, timezone.utc)
BASE_NS = int(BASE.replace(microsecond=0).timestamp()) * 1_000_000_000 + 123_456_000


def timing(*, wall=None, ticks=None, run_id="run"):
    wall_clock = Mock(side_effect=wall if wall is not None else [BASE_NS, BASE_NS + 350_999_999])
    elapsed_clock = Mock(side_effect=ticks if ticks is not None else [10**30, 10**30 + 350_999_999])
    value = RunTiming(run_id=run_id, utc_clock_ns=wall_clock, monotonic_clock_ns=elapsed_clock)
    return value, wall_clock, elapsed_clock


def test_explicit_start_and_finish_read_each_clock_only_once_per_boundary():
    value, wall, elapsed = timing()
    wall.assert_not_called()
    elapsed.assert_not_called()
    assert value.start() == BASE
    assert value.start() == BASE
    assert value.started_at == BASE and value.started_at_ns == BASE_NS
    assert value.finish().duration_ms == 350
    result = value.finish()
    assert value.finish() is result
    assert value.start() == BASE
    assert wall.call_count == elapsed.call_count == 2


def test_two_consumers_receive_the_same_final_result_and_matching_start():
    value, wall, elapsed = timing()
    start = value.start()
    monitor = value.finish()
    trajectory = value.finish()
    assert monitor is trajectory
    assert monitor.run_id == value.run_id == "run"
    assert monitor.started_at == start
    assert monitor.started_at_ns == value.started_at_ns == BASE_NS
    assert monitor.ended_at_ns == BASE_NS + 350_999_000
    assert monitor.ended_at == BASE + timedelta(microseconds=350_999)
    assert wall.call_count == elapsed.call_count == 2


@pytest.mark.parametrize("field", ["run_id", "started_at", "ended_at", "duration_ms", "execution_started_at"])
def test_finished_result_is_immutable(field):
    value, _, _ = timing()
    value.start()
    result = value.finish()
    with pytest.raises(FrozenInstanceError):
        setattr(result, field, None)


@pytest.mark.parametrize("elapsed_ns,expected", [(0, 0), (999_999, 0), (1_000_000, 1), (350_999_999, 350)])
def test_measured_zero_and_integer_millisecond_precision(elapsed_ns, expected):
    value, _, _ = timing(ticks=[2**120, 2**120 + elapsed_ns])
    value.start()
    assert value.finish().duration_ms == expected


def test_large_elapsed_sum_is_not_rounded_through_a_float():
    milliseconds = 2**53 + 9
    value, _, _ = timing(ticks=[10**40, 10**40 + milliseconds * 1_000_000])
    value.start()
    assert value.finish().duration_ms == milliseconds


def test_utc_timestamps_have_one_precision_for_span_and_fact_consumers():
    value, _, _ = timing(wall=[BASE_NS + 789, BASE_NS + 1_234_567_890])
    value.start()
    result = value.finish()
    assert result.started_at == BASE and result.started_at_ns == BASE_NS
    assert result.ended_at == BASE + timedelta(microseconds=1_234_567)
    assert result.ended_at_ns == BASE_NS + 1_234_567_000
    assert datetime.fromisoformat(result.started_at.isoformat()) == result.started_at
    assert result.started_at.utcoffset() == result.ended_at.utcoffset() == timedelta()


def test_wall_clock_regression_does_not_invent_a_zero_duration():
    value, _, _ = timing(wall=[BASE_NS, BASE_NS - 5_000_000_000])
    value.start()
    result = value.finish()
    assert result.ended_at == result.started_at == BASE
    assert result.duration_ms == 350


def test_negative_monotonic_interval_is_unknown_and_still_frozen():
    value, wall, elapsed = timing(ticks=[100, 99])
    value.start()
    result = value.finish()
    assert result.duration_ms is None
    assert value.finish() is result
    assert wall.call_count == elapsed.call_count == 2


def test_identity_can_bind_after_preparation_but_cannot_be_replaced():
    value, wall, elapsed = timing(run_id=None)
    value.start()
    assert value.run_id is None
    assert value.bind_run_id("root") == "root"
    assert value.bind_run_id("root") == "root"
    with pytest.raises(ValueError, match="identity"):
        value.bind_run_id("child")
    result = value.finish()
    assert result.run_id == "root" and result.started_at == BASE
    assert value.bind_run_id("root") == "root"
    assert wall.call_count == elapsed.call_count == 2


@pytest.mark.parametrize("run_id", ["", " ", 1, True])
def test_invalid_execution_identity_is_rejected(run_id):
    with pytest.raises(ValueError, match="Run ID"):
        RunTiming(run_id=run_id)


def test_actual_execution_anchor_retains_its_own_start_date():
    value, wall, elapsed = timing(wall=[BASE_NS, BASE_NS + 2_000_000_000, BASE_NS + 3_000_000_000])
    value.start()
    actual = value.mark_execution_started()
    assert value.mark_execution_started() == actual
    result = value.finish()
    assert result.started_at.date().isoformat() == "2026-11-19"
    assert actual == result.execution_started_at == BASE + timedelta(seconds=2)
    assert result.execution_started_at.date().isoformat() == "2026-11-20"
    assert value.mark_execution_started() == actual
    assert wall.call_count == 3 and elapsed.call_count == 2


def test_completion_without_actual_execution_does_not_create_an_execution_anchor():
    value, _, _ = timing(run_id=None)
    value.start()
    result = value.finish()
    assert result.run_id is None and result.execution_started_at is None
    with pytest.raises(RuntimeError, match="finished"):
        value.mark_execution_started()
    with pytest.raises(RuntimeError, match="finished"):
        value.bind_run_id("late")


@pytest.mark.parametrize("operation", ["finish", "mark_execution_started"])
def test_terminal_or_execution_observation_requires_a_start(operation):
    value, wall, elapsed = timing()
    assert value.started_at is None and value.started_at_ns is None
    with pytest.raises(RuntimeError, match="started"):
        getattr(value, operation)()
    wall.assert_not_called()
    elapsed.assert_not_called()


def test_clock_exception_does_not_cache_a_partial_start():
    value, wall, elapsed = timing(wall=[OSError("clock unavailable"), BASE_NS])
    with pytest.raises(OSError, match="unavailable"):
        value.start()
    assert value.started_at is None
    elapsed.assert_not_called()
    assert value.start() == BASE
    assert wall.call_count == 2 and elapsed.call_count == 1


@pytest.mark.parametrize("bad", [True, 1.5, "100", None])
def test_invalid_monotonic_clock_result_does_not_finish_or_fabricate_zero(bad):
    value, _, _ = timing(wall=[BASE_NS] * 3, ticks=[0, bad, 5_000_000])
    value.start()
    with pytest.raises(TypeError, match="integer"):
        value.finish()
    assert value.finish().duration_ms == 5


def test_nested_execution_objects_do_not_share_identity_or_boundaries():
    parent, _, _ = timing(run_id="parent")
    child, _, _ = timing(run_id="child", wall=[BASE_NS + 20_000_000, BASE_NS + 100_000_000],
                         ticks=[10, 80_000_010])
    parent.start()
    child.start()
    child_result = child.finish()
    parent_result = parent.finish()
    assert parent_result.run_id == "parent" and child_result.run_id == "child"
    assert parent_result.duration_ms == 350 and child_result.duration_ms == 80
    assert parent_result.started_at < child_result.started_at < child_result.ended_at < parent_result.ended_at


def test_module_is_loadable_without_telemetry_or_product_consumers(monkeypatch):
    path = Path(__file__).resolve().parents[3] / "sdk/nexent/monitor/run_timing.py"
    name = "isolated_agent_run_timing"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    original = builtins.__import__

    def isolated_import(name, *args, **kwargs):
        if name.split(".")[0] in {"opentelemetry", "nexent", "sqlalchemy", "elasticsearch"}:
            raise ImportError("External timing consumer is unavailable")
        return original(name, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "__import__", isolated_import)
        spec.loader.exec_module(module)
        value = module.RunTiming(run_id="standalone")
        value.start()
        assert value.finish().duration_ms >= 0


@pytest.mark.asyncio
async def test_concurrent_start_and_finish_publish_one_result():
    value, wall, elapsed = timing()
    barrier = Barrier(2)
    manager = ThreadManager("shared-run-clock", {"calls": LanePolicy("calls", 2, 0)})
    manager.start()

    def finish():
        barrier.wait(timeout=5)
        value.start()
        barrier.wait(timeout=5)
        return value.finish()

    try:
        jobs = [manager.submit("calls", ManagedTaskSpec("timing", "test"), finish) for _ in range(2)]
        left, right = [job.future.result(timeout=8) for job in jobs]
        assert left is right and left.duration_ms == 350
        assert wall.call_count == elapsed.call_count == 2
    finally:
        await manager.shutdown(timeout=8)
