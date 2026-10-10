"""TFP-D5-001: JSON imports do not admit forged bindings or general host execution."""

from __future__ import annotations

import json
from types import ModuleType, SimpleNamespace

import pytest

from test.automation.d1.test_tool_fastpath import make_wrapper


@pytest.mark.parametrize("source", [
    'import json as print', 'import json as final_answer',
    'from json import loads as read_skill_config', 'from json import loads as super',
    'import json as __json', 'import json as _print_outputs',
    'import json\njson = 1', 'from json import loads\nloads = 1',
    'import json\ncallback = json.loads', 'import json\nprint(json)',
    'import json\njson.__dict__', 'import json\njson.loads.__globals__',
    'import json\njson.decoder.JSONDecoder()',
    'import json\njson.loads(raw, object_hook=callback)',
    'import json\njson.dumps(host_object)',
    'import json\njson.loads(**arguments)',
    'import json\njson.loads(*arguments)',
    'import json\n__import__("os")',
    'from json import __builtins__', 'from json import *',
    'from json.decoder import JSONDecoder',
])
def test_tfp_d5_001_json_syntax(monkeypatch, source):
    """TFP-D5-001: reject the full source before imports, tools or callbacks execute."""
    wrapper, ordinary, calls, acquisitions, _ = make_wrapper(monkeypatch, execute=False)
    callbacks = []
    wrapper.send_variables({
        "raw": '{}', "callback": lambda value: callbacks.append(value),
        "host_object": object(), "arguments": {},
    })
    source = 'read_skill_config(skill_name="demo")\n' + source
    wrapper(source)
    assert ordinary.calls == [source]
    assert acquisitions == [True]
    assert calls == callbacks == []
    assert wrapper._active_imports() == {}
    assert "json" not in wrapper.local.state
    wrapper.cleanup()


@pytest.mark.parametrize("identity", [
    "module", "function", "changed_module", "changed_module_name", "changed_function", "injected_real",
])
def test_tfp_d5_001_json_identity(monkeypatch, identity):
    """TFP-D5-001: initial variables and later shadows cannot impersonate admitted imports."""
    wrapper, ordinary, calls, acquisitions, _ = make_wrapper(monkeypatch, execute=False)
    callbacks = []

    def callback(value):
        callbacks.append(value)
        return {}

    if identity.startswith("changed"):
        wrapper('import json as j\nfrom json import loads as parse')
    if identity == "injected_real":
        wrapper.send_variables({"j": json})
        source = 'import json as j\nprint(j.loads("{}"))'
    elif identity == "changed_module_name":
        class PoisonName:
            def __eq__(self, other):
                callbacks.append(other)
                return False

        forged = ModuleType("fixture")
        forged.__name__ = PoisonName()
        wrapper.send_variables({"j": forged})
        source = 'j.loads("{}")'
    elif identity in {"module", "changed_module"}:
        wrapper.send_variables({"j": SimpleNamespace(loads=callback, dumps=json.dumps)})
        source = 'j.loads("{}")'
    else:
        wrapper.send_variables({"parse": callback})
        source = 'parse("{}")'
    source = 'read_skill_config(skill_name="demo")\n' + source
    wrapper(source)
    restoration = {
        "changed_module": 'from json import loads as parse',
        "changed_module_name": 'from json import loads as parse',
        "changed_function": 'import json as j',
    }
    expected = [restoration[identity], source] if identity in restoration else [source]
    assert ordinary.calls == expected
    assert acquisitions == [True]
    assert callbacks == calls == []
    wrapper.cleanup()
