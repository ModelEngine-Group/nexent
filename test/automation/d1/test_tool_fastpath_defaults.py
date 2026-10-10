"""TFP-D1-006: default enablement and explicit opt-out across SDK run paths."""

from __future__ import annotations

import threading
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from nexent.core.agents.agent_model import AgentConfig, AgentRunInfo
from nexent.core.agents.nexent_agent import NexentAgent
from nexent.core.agents.sandbox import SandboxConfig, SandboxLevel, SandboxScope
from nexent.core.agents.tool_fastpath import DeferredToolExecutor
from nexent.core.utils.observer import MessageObserver
from test.automation.d1.test_tool_fastpath import OrdinaryExecutor


@pytest.mark.parametrize("with_mcp", [False, True])
@pytest.mark.parametrize("setting", ["default", "missing", "disabled", "enabled"])
def test_tfp_d1_006_run_defaults(monkeypatch, with_mcp, setting):
    """TFP-D1-006: actual run construction stays cold by default and honors false."""
    import nexent.core.agents.run_agent as run_module
    import nexent.core.agents.sandbox as sandbox_module

    acquisitions, releases, runtimes, outputs = [], [], [], []
    ordinary = OrdinaryExecutor()

    def acquire(**kwargs):
        acquisitions.append(kwargs)
        return ordinary

    monkeypatch.setattr(sandbox_module, "build_python_executor", acquire)
    monkeypatch.setattr(sandbox_module, "cleanup_executor", lambda executor, *args, **kwargs: releases.append(executor))
    monkeypatch.setattr(
        run_module, "ManagedMCPToolCollection",
        lambda **kwargs: nullcontext(SimpleNamespace(tools=[])),
    )

    def construct(**kwargs):
        runtime = NexentAgent(**kwargs)
        runtimes.append(runtime)
        monkeypatch.setattr(runtime, "create_model", lambda _: SimpleNamespace(model_id="fixture"))

        def execute(**kwargs):
            executor = runtime.agent.python_executor
            executor.send_tools(runtime.agent.tools)
            executor.send_variables(runtime.agent.state)
            outputs.append(executor('final_answer("answer")'))

        monkeypatch.setattr(runtime, "agent_run_with_observer", execute)
        return runtime

    monkeypatch.setattr(run_module, "NexentAgent", construct)
    info = AgentRunInfo(
        query="fixture", model_config_list=[], observer=MessageObserver(),
        agent_config=AgentConfig(
            name="fixture", description="Default enablement fixture", model_name="fixture", tools=[],
        ),
        stop_event=threading.Event(), thread_manager=object(),
        sandbox_config=SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SESSION),
        mcp_host=["http://mcp.fixture.invalid/mcp"] if with_mcp else None,
    )
    if setting == "missing":
        info = SimpleNamespace(**info.__dict__)
        del info.tool_fastpath_enabled
    elif setting != "default":
        info.tool_fastpath_enabled = setting == "enabled"
    enabled = setting != "disabled"
    try:
        run_module.agent_run_thread(info)
        assert info.attempt_outcome == "completed"
        assert len(runtimes) == 1
        runtime = runtimes[0]
        assert runtime.tool_fastpath_enabled is enabled
        assert isinstance(runtime.agent.python_executor, DeferredToolExecutor) is enabled
        assert len(outputs) == 1
        assert outputs[0].is_final_answer
        assert outputs[0].output == "answer"
        assert len(acquisitions) == (0 if enabled else 1)
        assert ordinary.calls == ([] if enabled else ["[0, None]", 'final_answer("answer")'])
    finally:
        for runtime in runtimes:
            runtime._cleanup_sandbox()
            runtime._cleanup_sandbox()
    assert releases == ([] if enabled else [ordinary])
