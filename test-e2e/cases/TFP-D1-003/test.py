"""TFP-D1-003: preserved fast-path acceptance checks."""

from __future__ import annotations

import pytest
from shared.tool_fastpath import make_wrapper


pytestmark = [pytest.mark.case_id("TFP-D1-003"), pytest.mark.stage("D1")]

def test_tfp_d1_003(monkeypatch):
    """TFP-D1-003: promotion preserves values and aliases without replay."""
    wrapper, ordinary, calls, acquisitions, releases = make_wrapper(monkeypatch)
    wrapper.send_variables({"tool_copy": wrapper._tools["read_skill_config"]})
    wrapper('items = []\nalias = items\nresult = read_skill_config(skill_name="demo")')
    wrapper("import math\nprint(result)")
    assert ordinary.variables["items"] is ordinary.variables["alias"]
    assert ordinary.variables["metadata"] == {"request": "example"}
    assert '"answer"' in ordinary.variables["result"]
    assert not {"__name__", "_print_outputs", "_operations_count"} & ordinary.variables.keys()
    assert "read_skill_config" not in ordinary.variables
    assert "tool_copy" not in ordinary.variables
    wrapper('read_skill_config(skill_name="demo")')
    assert len(ordinary.calls) == 2
    assert wrapper._nexent_backend == "docker"
    assert calls == ["demo", "demo"]
    assert acquisitions == [True]
    wrapper.cleanup()
    wrapper.cleanup()
    assert releases == [ordinary]

def test_tfp_d1_003_json(monkeypatch):
    """TFP-D1-003: imported symbols are restored, while parsed values and aliases migrate."""
    wrapper, ordinary, calls, acquisitions, releases = make_wrapper(monkeypatch)
    wrapper.send_variables({"j": "previous-data", "parse": "previous-data"})
    wrapper('import json as j\nfrom json import loads as parse, dumps as encode')
    wrapper('raw = read_skill_config(skill_name="demo")\nresult = parse(raw)\nalias = result')
    assert not {"j", "parse", "encode"} & wrapper.export_user_variables().keys()
    source = 'import math\nprint(encode(j.loads(raw)))'
    output = wrapper(source)
    assert '"answer"' in output.logs
    assert ordinary.variables["result"] is ordinary.variables["alias"]
    assert ordinary.variables["result"] == {"value": "answer"}
    assert not {"j", "parse", "encode"} & ordinary.variables.keys()
    assert ordinary.calls == [
        'from json import dumps as encode\nimport json as j\nfrom json import loads as parse', source,
    ]
    wrapper('final_answer(parse(raw))')
    assert len(ordinary.calls) == 3
    assert calls == ["demo"]
    assert acquisitions == [True]
    wrapper.cleanup()
    assert releases == [ordinary]

def test_tfp_d1_003_json_replaced_binding(monkeypatch):
    """TFP-D1-003: basic data replacing an imported alias migrates as user data."""
    wrapper, ordinary, _, acquisitions, _ = make_wrapper(monkeypatch)
    wrapper('import json as j')
    wrapper.send_variables({"j": {"value": "data"}})
    wrapper('import math\nprint(j)')
    assert ordinary.variables["j"] == {"value": "data"}
    assert ordinary.calls == ['import math\nprint(j)']
    assert acquisitions == [True]
    wrapper.cleanup()
