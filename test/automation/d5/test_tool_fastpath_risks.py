"""TFP-D5-001/002: hostile admission rejection and startup avoidance."""

from __future__ import annotations

import time

import pytest

from nexent.core.agents.tool_fastpath import is_simple_whitelisted_action
from test.automation.d1.test_tool_fastpath import make_wrapper


@pytest.mark.parametrize("source, shadow", [(source, None) for source in [
    "import os",
    "read_skill_config.__class__",
    'read_skill_config(skill_name="demo").upper()',
    "alias = read_skill_config\nalias()",
    'read_skill_config(**{"skill_name": "demo"})',
    "print(*values)",
    "for item in values:\n    print(item)",
    "while True:\n    print(1)",
    "x = [item for item in values]",
    "x = lambda: 1",
    "print = read_skill_config",
    "read_skill_config = 1",
    "final_answer = 1",
    "__name__ = 1",
    "_operations_count = 1",
    "print(metadata.__class__)",
    "print(getattr(metadata, 'value'))",
    "print(values[0])",
    "final_answer(1)\nprint(2)",
    "x = final_answer(1)",
    "x = missing_value",
    "print(host_object)",
    "print(cyclic)",
]] + [(f'{name}("demo")', name) for name in ("read_skill_config", "print", "final_answer")])
def test_tfp_d5_001(monkeypatch, source, shadow):
    """TFP-D5-001: every hostile step delegates unchanged before local effects."""
    cyclic = []
    cyclic.append(cyclic)
    variables = {"metadata": {}, "values": [1], "host_object": object(), "cyclic": cyclic}
    unauthorized_calls = []
    if shadow is not None:
        variables[shadow] = lambda *_args: unauthorized_calls.append(shadow)
    assert not is_simple_whitelisted_action(source, {"read_skill_config"}, variables)
    wrapper, ordinary, calls, acquisitions, _ = make_wrapper(monkeypatch, execute=False)
    wrapper.send_variables(variables)
    wrapper(source)
    assert ordinary.calls == [source]
    assert calls == []
    assert acquisitions == [True]
    assert unauthorized_calls == []
    wrapper('print("safe")')
    assert ordinary.calls == [source, 'print("safe")']
    assert acquisitions == [True]


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
