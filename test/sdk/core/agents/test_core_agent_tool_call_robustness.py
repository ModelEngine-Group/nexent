# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Argument and model-observation regressions using the existing agent fixtures."""

import sys
from collections import UserDict
from types import ModuleType
from unittest.mock import MagicMock

import pytest
from test_core_agent import TestRunStreamRealExecution as AgentFixtures
from test_core_agent import core_agent_module as core


@pytest.fixture
def tool():
    cls = type("MCPAdaptTool", (), {"__module__": "mcpadapt.smolagents_adapter"})
    tool = cls()
    tool.name = "cite"
    tool.inputs = {"anchor_id": {}, "limit": {"nullable": True}}
    tool.forward = MagicMock(side_effect=lambda *args, **kwargs: (args, kwargs))
    return tool


@pytest.mark.parametrize("args,kwargs,expected", [
    (("anchor",), {}, {"anchor_id": "anchor"}),
    (("anchor", 3), {}, {"anchor_id": "anchor", "limit": 3}),
    (("anchor",), {"limit": 3}, {"anchor_id": "anchor", "limit": 3}),
    ((), {"anchor_id": "anchor"}, {"anchor_id": "anchor"}),
])
def test_normalized_execution_and_observer_agree(tool, args, kwargs, expected):
    observer = MagicMock()
    core._wrap_tool_for_observer(tool, observer, "agent")
    assert tool.forward(*args, **kwargs) == ((), expected)
    assert observer.add_message.call_args.kwargs["tool_arguments"] == expected


@pytest.mark.parametrize("args,kwargs", [
    (("a", 1, 2), {}),
    (("a",), {"anchor_id": "b"}),
    (("a", 1), {"limit": 2}),
])
def test_invalid_calls_preserve_original_error(tool, args, kwargs):
    original = ValueError("original adapter error")
    forward = MagicMock(side_effect=original)
    tool.forward = forward
    core._wrap_tool_for_observer(tool, MagicMock(), "agent")
    with pytest.raises(ValueError) as caught:
        tool.forward(*args, **kwargs)
    assert caught.value is original
    assert str(caught.value) == "original adapter error"
    forward.assert_called_once_with(*args, **kwargs)


@pytest.mark.parametrize("mapping", [{"anchor_id": "a"}, UserDict({"anchor_id": "a"})])
def test_mapping_object_passes_through_unchanged(tool, mapping):
    original = tool.forward
    observer = MagicMock()
    core._wrap_tool_for_observer(tool, observer, "agent")
    args, kwargs = tool.forward(mapping)
    assert args[0] is mapping
    assert kwargs == {}
    assert original.call_args.args[0] is mapping
    assert observer.add_message.call_args.kwargs["tool_arguments"] == dict(mapping)


@pytest.mark.parametrize("inputs", [None, [], "schema", {}])
def test_missing_or_invalid_inputs_preserve_call(tool, inputs):
    tool.inputs = inputs
    core._wrap_tool_for_observer(tool, MagicMock(), "agent")
    assert tool.forward("a") == (("a",), {})


def test_absent_inputs_preserve_call(tool):
    del tool.inputs
    core._wrap_tool_for_observer(tool, MagicMock(), "agent")
    assert tool.forward("a") == (("a",), {})


def test_local_python_signature_and_host_marker_are_not_reinterpreted():
    class LocalTool:
        name = "local"
        inputs = {"different_schema_name": {}}
        _nexent_execute_on_host = True

        def forward(self, value, /):
            return value

    tool = LocalTool()
    core._wrap_tool_for_observer(tool, MagicMock(), "agent")
    assert tool.forward(42) == 42
    with pytest.raises(TypeError):
        tool.forward(different_schema_name=42)


def test_wrapping_twice_does_not_duplicate_calls(tool):
    observer = MagicMock()
    core._wrap_tool_for_observer(tool, observer, "agent")
    core._wrap_tool_for_observer(tool, observer, "agent")
    tool.forward("a")
    observer.add_message.assert_called_once()


@pytest.mark.parametrize("lang,required,optional", [("zh", "必填", "可选"), ("en", "required", "optional")])
def test_bridge_hint_keeps_last_error_and_parameters(tool, lang, required, optional):
    error = RuntimeError("Cell In[4]\nbridge stack\nRuntimeError: Local tool bridge request failed [cite]: "
                         "server detail\nanchor missing")
    hint = core._tool_failure_hint(error, {"cite": tool}, lang)
    assert "anchor missing" in hint
    assert f"anchor_id ({required})" in hint
    assert f"limit ({optional})" in hint
    assert "cite(anchor_id=..., limit=...)" in hint
    assert "Cell" not in hint and "stack" not in hint and "server detail" not in hint


def test_local_exception_chain_identifies_tool_without_changing_exception(tool):
    tool.forward = MagicMock(side_effect=ValueError("anchor missing"))
    core._wrap_tool_for_observer(tool, MagicMock(), "agent")
    try:
        try:
            tool.forward("a")
        except ValueError as original:
            raise RuntimeError(f"Code execution failed: ValueError: {original}") from original
    except RuntimeError as error:
        assert "anchor_id" in core._tool_failure_hint(error, {"cite": tool}, "en")


def test_caught_tool_error_does_not_relabel_later_python_error(tool):
    tool.forward = MagicMock(side_effect=ValueError("anchor missing"))
    core._wrap_tool_for_observer(tool, MagicMock(), "agent")
    try:
        try:
            tool.forward("a")
        except ValueError:
            raise NameError("ordinary Python error")
    except NameError as error:
        assert core._tool_failure_hint(error, {"cite": tool}, "en") is None


@pytest.mark.parametrize("error", [SyntaxError("invalid syntax"), NameError("missing variable"),
                                    RuntimeError("Local tool bridge request failed [unknown]: offline")])
def test_non_tool_errors_are_not_summarized(tool, error):
    assert core._tool_failure_hint(error, {"cite": tool}, "zh") is None


@pytest.mark.parametrize("tool_failure", [True, False])
def test_step_memory_shortens_only_tool_errors_and_retains_ui_details(monkeypatch, caplog, tool, tool_failure):
    agent, step, _ = AgentFixtures()._create_cmsr_007_step_agent('<code>cite("a")</code>')
    agent.lang = "zh"
    agent.tools = {"cite": tool}
    agent._screen_execution_output = lambda text, code: (text, None)
    full_error = ("Cell In[4]\nbridge stack\nRuntimeError: Local tool bridge request failed [cite]: bad anchor"
                  if tool_failure else "NameError: missing variable")
    error = RuntimeError(full_error)
    error.execution_logs = "partial stdout"
    agent.python_executor = MagicMock(side_effect=error)
    sandbox_package = ModuleType("nexent.core.agents.sandbox")
    sandbox_package.__path__ = []
    sandbox = ModuleType("nexent.core.agents.sandbox.execution")
    sandbox._execute_with_tool_context = lambda executor, code, **_kwargs: executor(code)
    sandbox_package.execution = sandbox
    monkeypatch.setitem(sys.modules, sandbox_package.__name__, sandbox_package)
    monkeypatch.setitem(sys.modules, sandbox.__name__, sandbox)

    class ExecutionError(Exception):
        def __init__(self, message, logger):
            super().__init__(message)

    monkeypatch.setattr(core, "AgentExecutionError", ExecutionError)
    monkeypatch.setattr(core, "ToolInputBlockedError", type("BlockedError", (Exception,), {}))
    with pytest.raises(ExecutionError) as caught:
        list(agent._step_stream(step))
    assert step.observations == "partial stdout"
    if tool_failure:
        assert "anchor_id" in str(caught.value)
        assert "bridge stack" not in str(caught.value)
        assert "bridge stack" in caplog.text and "Traceback" in caplog.text
        assert any("bridge stack" in str(call.args[2]) for call in agent.observer.add_message.call_args_list)
    else:
        assert str(caught.value) == full_error
        assert not any("Traceback" in str(call.args[2]) for call in agent.observer.add_message.call_args_list)
