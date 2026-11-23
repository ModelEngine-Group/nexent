"""TFP-D1-002: preserved fast-path acceptance checks."""

from __future__ import annotations

import pytest
from shared.tool_fastpath import make_wrapper
from shared.tool_fastpath_aidp import aidp_runtime as aidp_runtime


pytestmark = [pytest.mark.case_id("TFP-D1-002"), pytest.mark.stage("D1")]

@pytest.mark.parametrize("suffix", ["import math", "unapproved()", "result.upper()", "42"])
def test_tfp_d1_002(monkeypatch, suffix):
    """TFP-D1-002: validate the entire source before the first local call."""
    wrapper, ordinary, calls, acquisitions, _ = make_wrapper(monkeypatch, execute=False)
    source = f'result = read_skill_config(skill_name="demo")\n{suffix}'
    wrapper(source)
    assert acquisitions == [True]
    assert ordinary.calls == [source]
    assert calls == []

def test_tfp_d1_002_aidp(aidp_runtime):
    """TFP-D1-002: an AIDP mixed step delegates intact before any provider request."""
    executor = aidp_runtime.create().python_executor
    source = 'result = aidp_search(query="rules")\nimport math'
    executor(source)
    assert len(aidp_runtime.acquisitions) == 1
    assert aidp_runtime.ordinary.calls == ["[0, None]", source]
    assert aidp_runtime.requests == []

@pytest.mark.parametrize("suffix", [
    'import math', 'from json import *', 'from .json import loads',
    'json.dump({}, target)', 'json.load(target)', 'json.JSONDecoder()',
    'json.loads(raw)\nfor item in result:\n    print(item)',
])
def test_tfp_d1_002_json(monkeypatch, suffix):
    """TFP-D1-002: reject complete mixed steps before even their safe JSON import."""
    wrapper, ordinary, calls, acquisitions, _ = make_wrapper(monkeypatch, execute=False)
    wrapper.send_variables({"raw": '{}', "target": "fixture"})
    source = f'import json\nresult = read_skill_config(skill_name="demo")\n{suffix}'
    wrapper(source)
    assert ordinary.calls == [source]
    assert calls == []
    assert acquisitions == [True]
    assert "json" not in wrapper.local.state
    wrapper.cleanup()
