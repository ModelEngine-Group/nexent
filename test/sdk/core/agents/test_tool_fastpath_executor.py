"""Deferred execution preserves values, rejects replay and owns acquired resources."""

import json
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from smolagents.default_tools import FinalAnswerTool
from smolagents.local_python_executor import InterpreterError, LocalPythonExecutor

from nexent.core.agents import sandbox
from nexent.core.agents.tool_fastpath import DeferredToolExecutor
from nexent.core.tools.read_skill_config_tool import ReadSkillConfigTool


@pytest.fixture
def execution(mocker):
    tool = ReadSkillConfigTool(config_overrides={"demo": {"answer": "rules"}}, authorized_skill_names=["demo"])
    forward = mocker.patch.object(tool, "forward", wraps=tool.forward)
    interpreter = LocalPythonExecutor(additional_authorized_imports=["json", "math"])
    remote = Mock(
        side_effect=interpreter, _nexent_backend="docker", _nexent_tool_bridge=None,
        container=SimpleNamespace(id="container"), state=interpreter.state,
    )
    remote.send_tools.side_effect = interpreter.send_tools
    remote.send_variables.side_effect = interpreter.send_variables
    acquire, release, stop = Mock(return_value=remote), Mock(), Event()
    wrapper = DeferredToolExecutor(acquire, release, {tool.name: tool}, stop)
    wrapper.send_tools({tool.name: tool, "final_answer": FinalAnswerTool()})
    wrapper.send_variables({"metadata": {"request": "rules"}})
    yield SimpleNamespace(
        wrapper=wrapper, remote=remote, acquire=acquire, release=release,
        stop=stop, tool=tool, forward=forward,
    )
    wrapper.cleanup()


def test_pure_tool_assignment_print_and_final_answer_never_acquire_remote(execution):
    e = execution
    output = e.wrapper('result = read_skill_config(skill_name="demo")\nprint(result)\nfinal_answer(result)')
    assert json.loads(output.output) == {"answer": "rules"}
    assert output.is_final_answer
    assert '"answer": "rules"' in output.logs
    e.forward.assert_called_once_with(skill_name="demo")
    assert e.wrapper.remote is None
    assert e.wrapper.container is None
    assert e.wrapper._nexent_backend == "local"
    assert e.wrapper.state["result"] == output.output
    e.wrapper.cleanup()
    e.wrapper.cleanup()
    e.acquire.assert_not_called()
    e.release.assert_not_called()


def test_promotion_exports_only_user_values_and_preserves_reference_aliases(execution):
    e = execution
    shared = {"value": [1]}
    e.wrapper.send_variables({"left": shared, "right": shared, "tool_alias": e.tool, "_operations_count": 0})
    e.wrapper('result = read_skill_config("demo")\ncopy = result\nprint(copy)')
    # An interpreter-owned diagnostic must not become a migrated run variable.
    e.wrapper.local.state["untracked"] = "internal"
    exported = e.wrapper.export_user_variables()
    assert set(exported) == {"metadata", "left", "right", "result", "copy"}
    assert exported["left"] is exported["right"] is shared
    output = e.wrapper('import math\nprint(result, math.sqrt(4))')
    assert '"answer": "rules"' in output.logs and "2.0" in output.logs
    e.acquire.assert_called_once_with()
    e.remote.send_tools.assert_called_once_with(e.wrapper._tools)
    e.remote.send_variables.assert_called_once_with(exported)
    assert e.wrapper.container is e.remote.container
    assert e.wrapper._nexent_backend == "docker"
    assert e.wrapper.state is e.remote.state
    e.wrapper('print(copy)')
    e.acquire.assert_called_once()
    e.forward.assert_called_once()
    e.wrapper.cleanup()
    e.wrapper.cleanup()
    e.release.assert_called_once_with(e.remote)


def test_mixed_step_decides_before_any_tool_and_executes_it_once(execution, mocker):
    e = execution
    context = mocker.patch.object(sandbox, "_execute_with_tool_context", wraps=sandbox._execute_with_tool_context)
    code = 'result = read_skill_config("demo")\nimport math\nprint(result)'
    e.wrapper(code)
    e.acquire.assert_called_once()
    context.assert_called_once_with(e.remote, code)
    e.remote.assert_called_once_with(code)
    e.forward.assert_called_once()
    assert "result" not in e.remote.send_variables.call_args.args[0]


@pytest.mark.parametrize("source,alias", [
    ('import json', 'json'), ('import json as j', 'j'),
    ('from json import loads as decode', 'decode'), ('from json import dumps as encode', 'encode'),
])
def test_json_aliases_are_recreated_once_before_the_first_ordinary_step(execution, source, alias, mocker):
    e = execution
    context = mocker.patch.object(sandbox, "_execute_with_tool_context", wraps=sandbox._execute_with_tool_context)
    e.wrapper(source)
    e.wrapper('result = read_skill_config("demo")')
    e.acquire.assert_not_called()
    assert alias not in e.wrapper.export_user_variables()
    e.wrapper('import math\nprint(result)')
    restored = 'import json as json' if source == 'import json' else source
    assert [call.args for call in context.call_args_list] == [
        (e.remote, restored), (e.remote, 'import math\nprint(result)'),
    ]
    assert alias not in e.remote.send_variables.call_args.args[0]
    assert e.remote.state[alias] is not None
    e.wrapper('print(result)')
    assert context.call_count == 3
    e.acquire.assert_called_once()
    e.forward.assert_called_once()


def test_nested_json_and_cross_step_alias_calls_remain_local(execution):
    e = execution
    e.wrapper('import json as j\nfrom json import loads as decode, dumps as encode')
    first = e.wrapper('value = decode(j.dumps(metadata))\nprint(encode(value))')
    assert json.loads(first.logs) == {"request": "rules"}
    second = e.wrapper('print(j.loads(encode(value)))')
    assert "rules" in second.logs
    assert e.wrapper.export_user_variables()["value"] == {"request": "rules"}
    e.acquire.assert_not_called()


def test_overwritten_import_is_migrated_as_data_without_import_replay(execution):
    e = execution
    e.wrapper('import json as j')
    e.wrapper.send_variables({"j": {"changed": True}})
    assert e.wrapper.export_user_variables()["j"] == {"changed": True}
    e.wrapper('import math\nprint(j)')
    e.remote.assert_called_once_with('import math\nprint(j)')
    assert e.remote.state["j"] == {"changed": True}


@pytest.mark.parametrize("source,restored", [
    ('import json as j\nvalue = j.loads("bad")', 'import json as j'),
    ('from json import loads as decode\nvalue = decode("bad")', 'from json import loads as decode'),
    ('value = read_skill_config("demo")\nimport json as j', None),
])
def test_local_error_keeps_only_completed_imports_and_never_replays_tools(execution, source, restored):
    e = execution
    if restored is None:
        e.forward.side_effect = ValueError("tool failed")
    with pytest.raises(InterpreterError):
        e.wrapper(source)
    e.acquire.assert_not_called()
    assert "value" not in e.wrapper.export_user_variables()
    e.wrapper('import math')
    expected = [restored, 'import math'] if restored else ['import math']
    assert [call.args[0] for call in e.remote.call_args_list] == expected
    assert e.forward.call_count == (0 if restored else 1)


def test_replaced_same_name_tool_cannot_use_local_fastpath(execution):
    e = execution
    replacement = ReadSkillConfigTool(config_overrides={"demo": {"answer": "custom"}}, authorized_skill_names=["demo"])
    e.wrapper.send_tools({replacement.name: replacement})
    output = e.wrapper('read_skill_config("demo")')
    assert json.loads(output.output) == {"answer": "custom"}
    e.forward.assert_not_called()
    e.acquire.assert_called_once()


@pytest.mark.parametrize("terminal", [None, lambda answer: answer])
def test_missing_or_forged_final_answer_forces_ordinary_execution(execution, terminal):
    e = execution
    e.wrapper.send_tools({} if terminal is None else {"final_answer": terminal})
    e.remote.side_effect = lambda code: code
    assert e.wrapper('final_answer("answer")') == 'final_answer("answer")'
    e.acquire.assert_called_once()


def test_updates_after_promotion_are_forwarded_to_the_existing_executor(execution):
    e = execution
    e.wrapper('import math')
    tools = {e.tool.name: e.tool}
    e.wrapper.send_tools(tools)
    variables = {"later": [1, 2]}
    e.wrapper.send_variables(variables)
    e.remote.send_tools.assert_called_with(tools)
    e.remote.send_variables.assert_called_with(variables)
    assert e.wrapper('print(later)').logs.strip() == "[1, 2]"
    e.acquire.assert_called_once()


@pytest.mark.parametrize("operation", ["tools", "variables", "call"])
@pytest.mark.parametrize("closed", [False, True])
def test_cancelled_or_closed_executor_rejects_mutation_without_initialization(execution, operation, closed):
    e = execution
    if closed:
        e.wrapper.cleanup()
    else:
        e.stop.set()
    with pytest.raises(RuntimeError, match="closed" if closed else "cancelled"):
        if operation == "tools":
            e.wrapper.send_tools({})
        elif operation == "variables":
            e.wrapper.send_variables({"value": 1})
        else:
            e.wrapper('import math')
    e.acquire.assert_not_called()
    e.release.assert_not_called()


@pytest.mark.parametrize("phase", ["tools", "variables", "imports"])
@pytest.mark.parametrize("error", [RuntimeError("setup failed"), KeyboardInterrupt("setup interrupted")])
def test_failed_promotion_releases_acquired_executor_without_replaying_local_step(execution, phase, error):
    e = execution
    e.wrapper('import json as j\nresult = read_skill_config("demo")')
    if phase == "tools":
        e.remote.send_tools.side_effect = error
    elif phase == "variables":
        e.remote.send_variables.side_effect = error
    else:
        e.remote.side_effect = error
    with pytest.raises(type(error), match="setup"):
        e.wrapper('import math')
    assert e.wrapper.remote is None
    e.forward.assert_called_once()
    e.release.assert_called_once_with(e.remote)
    e.wrapper.cleanup()
    e.release.assert_called_once()


@pytest.mark.parametrize("phase", ["acquire", "variables", "imports"])
def test_cancellation_during_promotion_reclaims_the_acquired_resource(execution, phase):
    e = execution
    e.wrapper('import json as j')
    if phase == "acquire":
        def acquire():
            e.stop.set()
            return e.remote
        e.acquire.side_effect = acquire
    elif phase == "variables":
        e.remote.send_variables.side_effect = lambda _: e.stop.set()
    else:
        e.remote.side_effect = lambda _: e.stop.set()
    with pytest.raises(RuntimeError, match="cancelled"):
        e.wrapper('import math')
    assert e.wrapper.remote is None
    e.acquire.assert_called_once()
    e.release.assert_called_once_with(e.remote)
    if phase == "acquire":
        e.remote.send_tools.assert_not_called()
    assert all(call.args[0] != 'import math' for call in e.remote.call_args_list)


def test_factory_failure_has_no_acquired_resource_to_release(execution):
    e = execution
    e.acquire.side_effect = RuntimeError("factory failed")
    with pytest.raises(RuntimeError, match="factory failed"):
        e.wrapper('import math')
    assert e.wrapper.remote is None
    e.wrapper.cleanup()
    e.acquire.assert_called_once()
    e.release.assert_not_called()


def test_ordinary_action_error_keeps_resource_for_cleanup_without_retry(execution):
    e = execution
    e.remote.side_effect = RuntimeError("ordinary failed")
    with pytest.raises(RuntimeError, match="ordinary failed"):
        e.wrapper('import math')
    assert e.wrapper.remote is e.remote
    e.remote.assert_called_once_with('import math')
    e.release.assert_not_called()
    e.wrapper.cleanup()
    e.release.assert_called_once_with(e.remote)


def test_actual_fallback_and_absent_remote_diagnostics_are_reported(execution):
    e = execution
    e.remote._nexent_backend = "local"
    e.wrapper('import math')
    assert e.wrapper._nexent_backend == "local"
    del e.remote._nexent_backend
    del e.remote.state
    del e.remote.container
    assert e.wrapper._nexent_backend == "unknown"
    assert e.wrapper.state == {}
    assert e.wrapper.container is None
