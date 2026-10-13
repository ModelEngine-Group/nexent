"""TFP-D5-002: preserved fast-path acceptance checks."""

from __future__ import annotations

import time

import pytest
from shared.tool_fastpath import make_wrapper


pytestmark = [pytest.mark.case_id("TFP-D5-002"), pytest.mark.stage("D5")]

def test_tfp_d5_002(monkeypatch, record_property):
    """TFP-D5-002: one thousand warmed local actions avoid all factory calls."""
    wrapper, ordinary, calls, acquisitions, releases = make_wrapper(monkeypatch)
    source = 'result = read_skill_config(skill_name="demo")\nprint(result)'
    wrapper(source)
    calls.clear()
    timings = []
    for _ in range(1000):
        started = time.perf_counter()
        output = wrapper(source)
        timings.append(time.perf_counter() - started)
        assert '"answer"' in output.logs
    assert len(calls) == 1000
    assert acquisitions == []
    assert ordinary.calls == []
    wrapper.cleanup()
    wrapper.cleanup()
    assert releases == []
    p95 = sorted(timings)[949]
    record_property("fastpath_p95_ms", p95 * 1000)
    record_property("executor_factory_calls", len(acquisitions))
    assert p95 <= 0.010
