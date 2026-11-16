# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""TFP-D1-006: preserved fast-path acceptance checks."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from shared.tool_fastpath import FinalEnvelopeModel, OrdinaryExecutor
from smolagents.default_tools import FinalAnswerTool

from nexent.core.agents.agent_model import AgentConfig, AgentRunInfo, ToolConfig
from nexent.core.agents.nexent_agent import NexentAgent
from nexent.core.agents.sandbox import SandboxConfig, SandboxLevel, SandboxScope
from nexent.core.agents.tool_fastpath import (
    DeferredToolExecutor,
)
from nexent.core.utils.observer import MessageObserver


pytestmark = [pytest.mark.case_id("TFP-D1-006"), pytest.mark.stage("D1")]

@pytest.mark.parametrize("activate_child", [False, True])
def test_tfp_d1_006(monkeypatch, tmp_path, activate_child):
    """TFP-D1-006: deferred tree activation, workspace, cleanup and disabled mode."""
    import nexent.core.agents.nexent_agent as factory_module
    import nexent.core.agents.sandbox as sandbox_module

    group = object()
    builds = []
    raw_executors = []
    releases = []
    preparations = []
    script_runners = []

    def build(**kwargs):
        builds.append(kwargs)
        raw = OrdinaryExecutor(group=group)
        raw.container = SimpleNamespace(id=f"container-{len(builds)}")
        raw_executors.append(raw)
        return raw

    class ScriptRunner:
        def __init__(self, *args, **kwargs):
            self.cleanup_calls = 0
            script_runners.append(self)

        def cleanup(self):
            self.cleanup_calls += 1

    class FixtureCore:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            self.python_executor = kwargs["executor"]
            self.state = {}

    monkeypatch.setattr(sandbox_module, "build_python_executor", build)
    monkeypatch.setattr(sandbox_module, "SandboxSkillScriptRunner", ScriptRunner)
    monkeypatch.setattr(sandbox_module, "cleanup_executor", lambda ex, *args, **kwargs: releases.append(ex))
    monkeypatch.setattr(factory_module, "CoreAgent", FixtureCore)
    runtime = NexentAgent(
        observer=MessageObserver(), model_config_list=[], stop_event=threading.Event(),
        sandbox_config=SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SESSION),
        workspace_path=str(tmp_path),
    )
    monkeypatch.setattr(NexentAgent, "create_model", lambda self, _: SimpleNamespace())
    monkeypatch.setattr(NexentAgent, "_pull_file_workspace_from_sandbox", lambda self: preparations.append("pull"))
    monkeypatch.setattr(
        NexentAgent, "_push_file_workspace_to_sandbox", lambda self, **kwargs: preparations.append("push"),
    )

    def initialize(owner, executors=None):
        if executors or owner._sandbox_executors:
            preparations.append("initialize")

    monkeypatch.setattr(NexentAgent, "_initialize_sandbox_workspaces", initialize)
    child_config = AgentConfig(name="child", description="Child fixture", model_name="test", tools=[])
    root_config = AgentConfig(
        name="root", description="Root fixture", model_name="test",
        tools=[ToolConfig(class_name="RunSkillScriptTool", name="run_skill_script", source="builtin")],
        worker_agents=[child_config],
    )
    root = runtime.create_single_agent(root_config)
    script_tool = root.tools[0]
    assert script_tool.execution_backend is None
    runtime.agent = root
    wrappers = list(runtime._tool_fastpath_executors)
    assert len(wrappers) == 1
    child_definition = root.managed_agents[0]
    assert child_definition._inner.state == {}
    assert builds == []
    assert script_runners == []
    assert preparations == []
    for wrapper in wrappers:
        wrapper.send_tools({"final_answer": FinalAnswerTool()})
        wrapper("print(1)")
    assert builds == []
    root.python_executor("import math")
    assert script_tool.execution_backend is script_runners[0]
    invocation = child_definition._invocation_factory() if activate_child else nullcontext(None)
    with invocation as child:
        if activate_child:
            child_wrapper = child.python_executor
            assert isinstance(child_wrapper, DeferredToolExecutor)
            assert child_wrapper is not root.python_executor
            child_wrapper.send_tools({"final_answer": FinalAnswerTool()})
            child_wrapper("print(1)")
            assert len(builds) == 1
            assert len(script_runners) == 1
            child_wrapper("import math")
        count = 2 if activate_child else 1
        assert len(builds) == count
        assert builds[0]["session_container_group"] is None
        if activate_child:
            assert builds[1]["session_container_group"] is group
        assert preparations == ["pull", "push", "initialize"] * count
        assert [raw.calls for raw in raw_executors] == [["[0, None]", "import math"]] * count
    assert len(releases) == (1 if activate_child else 0)
    assert all(runner.cleanup_calls == 0 for runner in script_runners)
    runtime._close_subagent_invocations()
    runtime._cleanup_sandbox()
    runtime._cleanup_sandbox()
    assert len(builds) == count
    assert len(releases) == count
    assert len({id(raw) for raw in releases}) == count
    assert all(runner.cleanup_calls == 1 for runner in script_runners)
    assert runtime._sandbox_executors == []
    assert runtime._tool_fastpath_executors == []

    runtime.tool_fastpath_enabled = False
    eager = runtime.create_single_agent(child_config)
    assert eager.executor is raw_executors[-1]
    assert len(builds) == count + 1
    assert raw_executors[-1].calls == ["[0, None]"]
    runtime.agent = eager
    runtime._cleanup_sandbox()
    assert releases[-1] is raw_executors[-1]
    assert len(releases) == count + 1

@pytest.mark.parametrize("level, backend", [
    (SandboxLevel.LOCAL, "local"), (SandboxLevel.WASM, "wasm"), (SandboxLevel.DOCKER, "local"),
])
def test_tfp_d1_006_backends(monkeypatch, level, backend):
    """TFP-D1-006: only Docker is deferred and its local fallback stays sticky."""
    import nexent.core.agents.nexent_agent as factory_module
    import nexent.core.agents.sandbox as sandbox_module

    raw = OrdinaryExecutor()
    raw._nexent_backend = backend
    builds, releases = [], []

    def build(**kwargs):
        builds.append(kwargs)
        return raw

    monkeypatch.setattr(sandbox_module, "build_python_executor", build)
    monkeypatch.setattr(sandbox_module, "SandboxSkillScriptRunner", lambda *args, **kwargs: SimpleNamespace(cleanup=lambda: None))
    monkeypatch.setattr(sandbox_module, "cleanup_executor", lambda ex, *args, **kwargs: releases.append(ex))
    monkeypatch.setattr(
        factory_module, "CoreAgent", lambda **kwargs: SimpleNamespace(**kwargs, python_executor=kwargs["executor"]),
    )
    runtime = NexentAgent(
        observer=MessageObserver(), model_config_list=[], stop_event=threading.Event(),
        sandbox_config=SandboxConfig(level=level, scope=SandboxScope.SESSION), tool_fastpath_enabled=True,
    )
    monkeypatch.setattr(runtime, "create_model", lambda _: SimpleNamespace())
    runtime.agent = runtime.create_single_agent(
        AgentConfig(name="root", description="Fixture", model_name="test", tools=[]),
    )
    executor = runtime.agent.python_executor
    assert isinstance(executor, DeferredToolExecutor) == (level == SandboxLevel.DOCKER)
    assert len(builds) == (0 if level == SandboxLevel.DOCKER else 1)
    executor.send_tools({"final_answer": FinalAnswerTool()})
    executor("import math")
    assert len(builds) == 1
    assert executor._nexent_backend == backend
    assert executor('final_answer("answer")').is_final_answer
    runtime._cleanup_sandbox()
    runtime._cleanup_sandbox()
    assert releases == [raw]

@pytest.mark.parametrize("enabled, allowed, expected", [
    (None, None, [True, ["KnowledgeBaseSearchTool", "ReadSkillMdTool", "ReadSkillConfigTool", "AidpSearchTool"]]),
    ("false", None, [False, ["KnowledgeBaseSearchTool", "ReadSkillMdTool", "ReadSkillConfigTool", "AidpSearchTool"]]),
    ("true", " ReadSkillConfigTool,ReadSkillConfigTool ", [True, ["ReadSkillConfigTool"]]),
    ("true", "", [True, []]),
])
def test_tfp_d1_006_configuration(enabled, allowed, expected):
    """TFP-D1-006: deployment defaults and explicit allowlists are propagated."""
    environment = os.environ.copy()
    for name, value in (
        ("NEXENT_TOOL_FASTPATH_ENABLED", enabled),
        ("NEXENT_TOOL_FASTPATH_ALLOWED_TOOLS", allowed),
    ):
        if value is None:
            environment.pop(name, None)
        else:
            environment[name] = value
    source = (
        "import json\nfrom unittest.mock import patch\n"
        "with patch('dotenv.load_dotenv'):\n"
        "    import backend.contracts.constants.environment as c\n"
        "print(json.dumps([c.NEXENT_TOOL_FASTPATH_ENABLED, c.NEXENT_TOOL_FASTPATH_ALLOWED_TOOLS]))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", source], cwd=Path(__file__).resolve().parents[3],
        env=environment, capture_output=True, text=True, timeout=10, check=True,
    )
    assert json.loads(result.stdout) == expected

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
        monkeypatch.setattr(runtime, "create_model", lambda _: FinalEnvelopeModel())

        def execute(**kwargs):
            outputs.append(runtime.agent.run("fixture", max_steps=1))

        monkeypatch.setattr(runtime, "agent_run_with_observer", execute)
        return runtime

    monkeypatch.setattr(run_module, "NexentAgent", construct)
    info = AgentRunInfo(
        query="fixture", model_config_list=[], observer=MessageObserver(),
        agent_config=AgentConfig(
            name="fixture", description="Default enablement fixture", model_name="fixture", tools=[],
            enable_protocol_repair_retry=True,
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
        assert runtime.agent.memory.steps[-1].is_final_answer is True
        assert str(outputs[0]) == "answer"
        assert "final_answer" not in runtime.agent.tools
        assert len(acquisitions) == (0 if enabled else 1)
        assert ordinary.calls == ([] if enabled else ["[0, None]"])
    finally:
        for runtime in runtimes:
            runtime._cleanup_sandbox()
            runtime._cleanup_sandbox()
    assert releases == ([] if enabled else [ordinary])
