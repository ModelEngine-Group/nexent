# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Code execution timing starts after deferred executor preparation completes."""

import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from smolagents.default_tools import FinalAnswerTool

from nexent.core.agents import sandbox
from nexent.core.agents.tool_fastpath import DeferredToolExecutor
from nexent.monitor import phase_capture

from .test_phase_capture import local_spans as local_spans


@pytest.fixture
def execution_clock(monkeypatch):
    clock = SimpleNamespace(value=0.0, base=time.time_ns())
    clock.advance = lambda seconds: setattr(clock, "value", clock.value + seconds)
    monkeypatch.setattr(
        phase_capture,
        "time",
        SimpleNamespace(
            perf_counter=lambda: clock.value,
            time_ns=lambda: clock.base + int(clock.value * 1_000_000_000),
        ),
    )
    return clock


@pytest.mark.parametrize("error", [None, RuntimeError, asyncio.CancelledError])
def test_deferred_code_duration_excludes_initialization_and_migration(
    local_spans, execution_clock, error
):
    manager, exporter = local_spans
    clock = execution_clock
    output = SimpleNamespace(output="answer", logs="logs")

    def execute(code):
        if code == "import json as json":
            clock.advance(0.75)
            return output
        assert code == "print(1 + 2)"
        clock.advance(0.125)
        if error:
            raise error("private failure")
        return output

    remote = Mock(
        side_effect=execute, _nexent_backend="docker", _nexent_tool_bridge=None
    )
    remote.send_tools.side_effect = lambda _tools: clock.advance(0.5)
    remote.send_variables.side_effect = lambda _variables: clock.advance(0.25)

    def acquire():
        with phase_capture.trace_phase("agent.sandbox.initialize"):
            clock.advance(3)
        return remote

    acquire = Mock(side_effect=acquire)
    release = Mock()
    wrapper = DeferredToolExecutor(acquire, release, {})
    try:
        wrapper.send_tools({"final_answer": FinalAnswerTool()})
        wrapper("import json\nfinal_answer(3)")
        with (
            manager.start_agent_run(),
            manager.trace_tool_call("python_interpreter", "root") as parent,
        ):
            if error:
                with pytest.raises(error):
                    sandbox._execute_with_tool_context(
                        wrapper, "print(1 + 2)", trace_execution=True
                    )
            else:
                assert (
                    sandbox._execute_with_tool_context(
                        wrapper, "print(1 + 2)", trace_execution=True
                    )
                    is output
                )
                assert (
                    sandbox._execute_with_tool_context(
                        wrapper, "print(1 + 2)", trace_execution=True
                    )
                    is output
                )
        acquired = next(
            s
            for s in exporter.get_finished_spans()
            if s.name == "agent.sandbox.initialize"
        )
        executions = [
            s for s in exporter.get_finished_spans() if s.name == "code.execute"
        ]
        assert len(executions) == (1 if error else 2)
        assert acquired.attributes["nexent.duration_ms"] == pytest.approx(3000)
        for node in executions:
            assert node.parent.span_id == parent.context.span_id
            assert node.start_time >= acquired.end_time
            assert node.attributes["nexent.duration_ms"] == pytest.approx(125)
            assert node.attributes["nexent.node.kind"] == "phase"
            assert json.loads(node.attributes["input.value"]) == {
                "code": "print(1 + 2)"
            }
            assert "output.value" not in node.attributes
            assert "private failure" not in str(node.attributes)
            if error:
                assert node.attributes["error.type"] == error.__name__
        acquire.assert_called_once()
        remote.send_tools.assert_called_once()
        remote.send_variables.assert_called_once()
        assert [call.args[0] for call in remote.call_args_list] == [
            "import json as json",
            *(["print(1 + 2)"] * (1 if error else 2)),
        ]
    finally:
        wrapper.cleanup()
    release.assert_called_once_with(remote)


def test_official_local_path_is_timed_without_initializing_sandbox(
    local_spans, execution_clock
):
    manager, exporter = local_spans
    output = SimpleNamespace(output="local", logs="")

    class Local:
        state = {}

        def __call__(self, code):
            assert code == "final_answer(3)"
            execution_clock.advance(0.25)
            return output

    acquire, release = Mock(), Mock()
    wrapper = DeferredToolExecutor(acquire, release, {})
    wrapper.send_tools({"final_answer": FinalAnswerTool()})
    wrapper.local = Local()
    with (
        manager.start_agent_run(),
        manager.trace_tool_call("python_interpreter", "root"),
    ):
        assert (
            sandbox._execute_with_tool_context(
                wrapper, "final_answer(3)", trace_execution=True
            )
            is output
        )
    node = next(s for s in exporter.get_finished_spans() if s.name == "code.execute")
    assert node.attributes["nexent.duration_ms"] == pytest.approx(250)
    assert node.attributes["execution.backend"] == "local"
    acquire.assert_not_called()
    wrapper.cleanup()
    release.assert_not_called()


@pytest.mark.parametrize("enabled", [False, True])
def test_direct_executor_default_and_remote_capture_keep_result(
    local_spans, monkeypatch, enabled
):
    manager, exporter = local_spans
    if enabled:
        monkeypatch.setattr(manager._config, "provider", "otlp")
    result = SimpleNamespace(output="direct", logs="")
    executor = Mock(
        return_value=result, _nexent_tool_bridge=None, _nexent_backend="local"
    )
    with manager.start_agent_run():
        assert (
            sandbox._execute_with_tool_context(
                executor, "print(3)", trace_execution=enabled
            )
            is result
        )
    executor.assert_called_once_with("print(3)")
    assert not any(s.name == "code.execute" for s in exporter.get_finished_spans())
