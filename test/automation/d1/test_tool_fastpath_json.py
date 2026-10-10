"""TFP-D1-001/002/003/005: local JSON imports and one-way namespace promotion."""

from __future__ import annotations

import json
import threading

import pytest

from test.automation.d1.test_tool_fastpath import make_wrapper


@pytest.mark.parametrize("source", [
    'import json\nresult = json.loads(raw)\nprint(json.dumps(result, ensure_ascii=False))',
    'import json as j\nresult = j.loads(raw)\nprint(j.dumps(result, ensure_ascii=False))',
    'from json import loads, dumps\nresult = loads(raw)\nprint(dumps(result, ensure_ascii=False))',
    'from json import loads as parse, dumps as encode\nresult = parse(raw)\nprint(encode(result, ensure_ascii=False))',
    'import json\nresult = json.loads(json.dumps({"value": "规则"}))\nprint(result)',
])
def test_tfp_d1_001_json(monkeypatch, source):
    """TFP-D1-001: real JSON imports, aliases and nested calls never acquire Docker."""
    wrapper, ordinary, calls, acquisitions, releases = make_wrapper(monkeypatch)
    wrapper.send_variables({"raw": '{"value": "规则"}'})
    output = wrapper(source)
    assert "规则" in output.logs
    assert wrapper.local.state["result"] == {"value": "规则"}
    answer = wrapper('final_answer(result)')
    assert answer.is_final_answer
    assert answer.output == {"value": "规则"}
    assert acquisitions == ordinary.calls == calls == []
    wrapper.cleanup()
    assert releases == []


def test_tfp_d1_001_json_tool_results(monkeypatch):
    """TFP-D1-001: parsing a real official tool result preserves local tool execution."""
    wrapper, ordinary, calls, acquisitions, _ = make_wrapper(monkeypatch)
    wrapper('import json as j\nraw = read_skill_config(skill_name="demo")\nresult = j.loads(raw)')
    output = wrapper('final_answer(j.dumps(result, ensure_ascii=False))')
    assert output.is_final_answer
    assert json.loads(output.output) == {"value": "answer"}
    assert calls == ["demo"]
    assert acquisitions == ordinary.calls == []
    wrapper.cleanup()


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


def test_tfp_d1_005_json_error(monkeypatch):
    """TFP-D1-005: JSON errors retain actual imports without inventing unfinished ones."""
    wrapper, ordinary, calls, acquisitions, _ = make_wrapper(monkeypatch)
    source = 'from json import loads as parse\nresult = parse("invalid")\nimport json as later'
    with pytest.raises(Exception, match="Expecting value"):
        wrapper(source)
    assert wrapper._active_imports() == {"parse": "json.loads"}
    assert "later" not in wrapper.local.state
    assert acquisitions == ordinary.calls == calls == []
    output = wrapper('final_answer(parse(\'{"value": 1}\'))')
    assert output.is_final_answer and output.output == {"value": 1}
    wrapper('import math\nprint(parse("{}"))')
    assert ordinary.calls == ['from json import loads as parse', 'import math\nprint(parse("{}"))']
    wrapper.cleanup()


def test_tfp_d1_005_json_rebinding_error(monkeypatch):
    """TFP-D1-005: a failed step preserves the function actually bound before failure."""
    wrapper, ordinary, _, _, _ = make_wrapper(monkeypatch)
    wrapper('from json import loads as transform')
    with pytest.raises(Exception, match="Expecting value"):
        wrapper('result = transform("invalid")\nfrom json import dumps as transform')
    assert wrapper._active_imports() == {"transform": "json.loads"}
    wrapper('import math\nprint(transform("{}"))')
    assert ordinary.calls[0] == 'from json import loads as transform'
    wrapper.cleanup()


@pytest.mark.parametrize("failure", ["error", "cancel"])
def test_tfp_d1_005_json_restore_failure(monkeypatch, failure):
    """TFP-D1-005: failed import restoration closes resources without executing user code."""
    event = threading.Event()
    wrapper, ordinary, _, acquisitions, releases = make_wrapper(monkeypatch, stop_event=event)
    wrapper('import json')
    execute = type(ordinary).__call__

    def fail_restore(self, source):
        if source == 'import json as json':
            if failure == "cancel":
                event.set()
            else:
                raise RuntimeError("restore failed")
        return execute(self, source)

    monkeypatch.setattr(type(ordinary), "__call__", fail_restore)
    with pytest.raises(RuntimeError, match="restore failed|cancelled"):
        wrapper('import math')
    assert acquisitions == [True]
    assert wrapper.remote is None
    assert 'import math' not in ordinary.calls
    assert releases == [ordinary]
    wrapper.cleanup()
    assert releases == [ordinary]
