"""Whole-action admission must exclude arbitrary host Python execution."""

import json
from types import ModuleType

import pytest

from nexent.core.agents import tool_fastpath
from nexent.core.agents.tool_fastpath import is_simple_whitelisted_action


@pytest.mark.parametrize("code", [
    'result = search(query="rules")\nprint(result)\nfinal_answer(result)',
    'result = search(metadata)\ncopy = result\nprint(copy, sep="|")',
    'value = [None, True, b"bytes", (1, -2, +3.5)]\nsearch(value)',
    'value = {"key": [metadata], 2: (None, False)}\nprint(value)',
    'import json\nvalue = json.loads(json.dumps(metadata))\nsearch(value)',
    'import json as j\nprint(j.dumps({"value": -1}))',
    'from json import loads as decode, dumps as encode\nprint(decode(encode(metadata)))',
    'json = "old data"\nimport json\nprint(json.dumps(metadata))',
])
def test_admits_documented_tool_and_json_data_forms(code):
    assert is_simple_whitelisted_action(code, {"search"}, {"metadata": {"tags": ["rules"]}})


@pytest.mark.parametrize("code", [
    '', '# comment', 'search(', 'x = 1\x00',
    'import os', 'import json, os', 'from .json import loads', 'from json import *',
    'from json import load', 'import json as search', 'import json as print',
    'import json as final_answer', 'import json as super', 'import json as __json',
    'import json as same, json as same',
    'search = 1', 'print = 1', 'final_answer = 1', '__private = 1', '_print_outputs = 1',
    'a = b = 1', 'a, b = [1, 2]', 'metadata.key = 1', 'a += 1', 'a: int = 1',
    'search(metadata.key)', 'search(metadata["key"])', 'search([*metadata])',
    'search(**metadata)', 'search(*metadata)', 'search({**metadata})',
    'search({metadata: 1})', 'search(1 + 2)', 'search(-True)', 'search(-metadata)',
    'search(1j)', 'print(missing)', 'print(__name__)',
    'other()', 'metadata()', 'metadata.get("key")', 'search(search("nested"))',
    'value = final_answer("answer")', 'final_answer("answer")\nprint("after")',
    'if True:\n search("rules")', 'for x in []:\n print(x)', 'pass', '"data"',
    'import json\njson = 1', 'import json\nprint(json)',
    'import json\njson.load("file")', 'import json\njson.loads.__call__("{}")',
    'import json\nprint(json.__dict__)', 'import json\nprint(json.loads)',
    'import json\nprint(json.dumps(search("nested")))',
    'from json import loads\ncopy = loads',
])
def test_rejects_unsafe_or_unsupported_complete_actions(code):
    assert not is_simple_whitelisted_action(code, {"search"}, {"metadata": {"key": 1}})


@pytest.mark.parametrize("name", ["search", "print", "final_answer"])
def test_run_variables_cannot_shadow_callable_primitives(name):
    assert not is_simple_whitelisted_action(f'{name}("value")', {"search"}, {name: "shadow"})


@pytest.mark.parametrize("code", [None, 123, b'print("x")', 'print("中文")' + ' ' * 65536],
                         ids=["none", "number", "bytes", "over-byte-limit"])
def test_rejects_invalid_input_and_byte_limit(code):
    assert not is_simple_whitelisted_action(code, set(), {})


def test_action_statement_and_ast_size_limits():
    assert is_simple_whitelisted_action('print(1)\n' * 64, set(), {})
    assert not is_simple_whitelisted_action('print(1)\n' * 65, set(), {})
    assert not is_simple_whitelisted_action('print([' + ','.join('1' for _ in range(1000)) + '])', set(), {})


@pytest.mark.parametrize("error", [SyntaxError("bad"), ValueError("bad"), RecursionError("deep")])
def test_parser_failures_route_to_ordinary_execution(mocker, error):
    mocker.patch.object(tool_fastpath.ast, "parse", side_effect=error)
    assert not is_simple_whitelisted_action('print(1)', set(), {})


def test_existing_data_preserves_aliases_but_excludes_cycles_and_excessive_depth():
    shared = [1]
    assert is_simple_whitelisted_action('print(value)', set(), {"value": [shared, shared]})
    cycle = []
    cycle.append(cycle)
    assert not is_simple_whitelisted_action('print(value)', set(), {"value": cycle})
    value = 1
    for _ in range(32):
        value = [value]
    assert is_simple_whitelisted_action('print(value)', set(), {"value": value})
    assert not is_simple_whitelisted_action('print(value)', set(), {"value": [value]})


@pytest.mark.parametrize("value", [object(), {1}, {"key": object()}, {object(): 1}])
def test_existing_nonbasic_objects_cannot_be_passed_to_host_tools(value):
    assert not is_simple_whitelisted_action('search(value)', {"search"}, {"value": value})


def test_data_validation_does_not_invoke_container_subclass_hooks():
    class HostList(list):
        def __iter__(self):
            raise AssertionError("User-defined iterator must not run during admission")

    assert not is_simple_whitelisted_action('search(value)', {"search"}, {"value": HostList([1])})


@pytest.mark.parametrize("value,target,code", [
    (json, "json", 'print(j.loads("{}"))'),
    (json.loads, "json.loads", 'print(j("{}"))'),
    (json.dumps, "json.dumps", 'print(j({"value": 1}))'),
])
def test_cross_step_json_calls_require_real_import_bindings(value, target, code):
    assert is_simple_whitelisted_action(code, set(), {"j": value}, {"j": target})
    assert not is_simple_whitelisted_action(code, set(), {"j": value})
    assert not is_simple_whitelisted_action(code, set(), {"j": value}, {"j": "json.load"})
    assert not is_simple_whitelisted_action(code, set(), {"j": "replaced"}, {"j": target})


@pytest.mark.parametrize("variant", ["name", "function", "type"])
def test_forged_json_aliases_are_not_trusted(variant):
    forged = ModuleType("json")
    forged.loads, forged.dumps = json.loads, json.dumps
    if variant == "name":
        forged.__name__ = object()
    elif variant == "function":
        forged.loads = lambda value: value
    else:
        class ModuleSubclass(ModuleType):
            pass
        forged = ModuleSubclass("json")
        forged.loads, forged.dumps = json.loads, json.dumps
    assert not is_simple_whitelisted_action('j.loads("{}")', set(), {"j": forged}, {"j": "json"})


def test_import_cannot_overwrite_untrusted_object_but_can_refresh_a_real_alias():
    assert not is_simple_whitelisted_action('import json as j', set(), {"j": object()})
    assert is_simple_whitelisted_action('import json as j', set(), {"j": json}, {"j": "json"})
