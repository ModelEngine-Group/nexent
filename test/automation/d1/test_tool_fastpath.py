"""TFP-D1-001 through TFP-D1-006: deferred official-tool execution contracts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from smolagents.default_tools import FinalAnswerTool
from smolagents.local_python_executor import CodeOutput, LocalPythonExecutor

from nexent.core.agents.agent_model import AgentConfig, ToolConfig
from nexent.core.agents.nexent_agent import NexentAgent
from nexent.core.agents.sandbox import SandboxConfig, SandboxLevel, SandboxScope
from nexent.core.agents.tool_fastpath import (
    DeferredToolExecutor,
    is_simple_whitelisted_action,
    official_fastpath_tools,
)
from nexent.core.tools.read_skill_config_tool import ReadSkillConfigTool
from nexent.core.utils.observer import MessageObserver


class OrdinaryExecutor:
    """Controlled ordinary executor with a real interpreter for safe test code."""

    def __init__(self, *, group=None, execute=True):
        self.interpreter = LocalPythonExecutor(["json"])
        self._nexent_backend = "docker"
        self._nexent_session_container_group = group
        self.container = None
        self.calls = []
        self.variables = {}
        self.tools = {}
        self.execute = execute

    @property
    def state(self):
        return self.interpreter.state

    def send_variables(self, variables):
        self.variables.update(variables)
        self.interpreter.send_variables(variables)

    def send_tools(self, tools):
        self.tools = tools
        self.interpreter.send_tools(tools)

    def __call__(self, code):
        self.calls.append(code)
        if self.execute:
            return self.interpreter(code)
        return CodeOutput(output=None, logs="", is_final_answer=False)


def make_wrapper(monkeypatch, *, execute=True, stop_event=None):
    tool = ReadSkillConfigTool(
        config_overrides={"demo": {"value": "answer"}}, authorized_skill_names=["demo"],
    )
    calls = []
    forward = tool.forward

    def observed(skill_name):
        calls.append(skill_name)
        return forward(skill_name)

    monkeypatch.setattr(tool, "forward", observed)
    acquisitions = []
    releases = []
    ordinary = OrdinaryExecutor(execute=execute)

    def acquire():
        acquisitions.append(True)
        return ordinary

    wrapper = DeferredToolExecutor(acquire, releases.append, {tool.name: tool}, stop_event)
    wrapper.send_tools({tool.name: tool, "final_answer": FinalAnswerTool()})
    wrapper.send_variables({"metadata": {"request": "example"}})
    return wrapper, ordinary, calls, acquisitions, releases


def test_tfp_d1_001(monkeypatch):
    """TFP-D1-001: assignment, logs and saved final answer without acquisition."""
    wrapper, ordinary, calls, acquisitions, releases = make_wrapper(monkeypatch)
    from nexent.core.agents.core_agent import _wrap_tool_for_observer
    from nexent.core.agents.nexent_agent import _wrap_tool_with_monitoring

    observer = MessageObserver()
    events = []
    monkeypatch.setattr(observer, "add_message", lambda *args, **kwargs: events.append((args, kwargs)))
    tool = wrapper._tools["read_skill_config"]
    assert _wrap_tool_with_monitoring(tool, "fixture") is tool
    _wrap_tool_for_observer(tool, observer, "fixture")
    assert wrapper._nexent_backend == "local"
    first = wrapper('result = read_skill_config(skill_name="demo")\nprint(result)')
    assert '"answer"' in first.logs
    assert not first.is_final_answer
    last = wrapper("final_answer(result)")
    assert last.is_final_answer
    assert last.output == wrapper.local.state["result"]
    assert calls == ["demo"]
    assert len(events) == 1
    assert events[0][1]["tool_name"] == tool.name
    assert acquisitions == []
    assert ordinary.calls == []
    wrapper.cleanup()
    wrapper.cleanup()
    assert releases == []


@pytest.mark.parametrize("suffix", ["import math", "unapproved()", "result.upper()", "42"])
def test_tfp_d1_002(monkeypatch, suffix):
    """TFP-D1-002: validate the entire source before the first local call."""
    wrapper, ordinary, calls, acquisitions, _ = make_wrapper(monkeypatch, execute=False)
    source = f'result = read_skill_config(skill_name="demo")\n{suffix}'
    wrapper(source)
    assert acquisitions == [True]
    assert ordinary.calls == [source]
    assert calls == []


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

def test_tfp_d1_004(monkeypatch):
    """TFP-D1-004: exact official identity and trusted factory source are required."""
    wrapper, ordinary, _, acquisitions, _ = make_wrapper(monkeypatch, execute=False)
    official = wrapper._tools["read_skill_config"]
    from nexent.core.tools.knowledge_base_search_tool import KnowledgeBaseSearchTool
    from nexent.core.tools.read_skill_md_tool import ReadSkillMdTool

    for tool in (
        official, ReadSkillMdTool(),
        KnowledgeBaseSearchTool(index_names=[], observer=MessageObserver()),
    ):
        trusted = ToolConfig(class_name=type(tool).__name__, name=tool.name, source="local")
        assert official_fastpath_tools([trusted], [tool], [trusted.class_name]) == {tool.name: tool}
    config = ToolConfig(class_name="ReadSkillConfigTool", name=official.name, source="builtin")
    assert official_fastpath_tools([config], [official], [config.class_name]) == {official.name: official}
    config.source = "mcp"
    assert official_fastpath_tools([config], [official], [config.class_name]) == {}
    config.source = "builtin"
    custom = SimpleNamespace(name=official.name)
    assert official_fastpath_tools([config], [custom], [config.class_name]) == {}

    class UnknownSubclass(ReadSkillConfigTool):
        pass

    subclass = UnknownSubclass(config_overrides={})
    assert official_fastpath_tools([config], [subclass], [config.class_name]) == {}
    with pytest.raises(ValueError, match="Unknown official"):
        official_fastpath_tools([config], [official], ["UnregisteredTool"])
    assert official_fastpath_tools([config], [official], []) == {}
    assert not is_simple_whitelisted_action("alias = read_skill_config\nalias()", {official.name}, {})
    assert not is_simple_whitelisted_action("print = 1", {official.name}, {})
    assert not is_simple_whitelisted_action("_print_outputs = 1", {official.name}, {})
    wrapper.send_tools({official.name: custom, "final_answer": FinalAnswerTool()})
    wrapper('read_skill_config(skill_name="demo")')
    assert wrapper.remote is not None
    assert acquisitions == [True]
    assert ordinary.calls == ['read_skill_config(skill_name="demo")']
    wrapper, ordinary, _, acquisitions, _ = make_wrapper(monkeypatch, execute=False)
    wrapper.send_tools({"final_answer": lambda answer: pytest.fail("Forged final answer ran locally")})
    wrapper('final_answer("demo")')
    assert acquisitions == [True]
    assert ordinary.calls == ['final_answer("demo")']


def test_tfp_d1_005(monkeypatch):
    """TFP-D1-005: failures never replay; cancellation releases acquisition."""
    event = threading.Event()
    wrapper, ordinary, calls, acquisitions, releases = make_wrapper(monkeypatch, stop_event=event)

    def failing(**kwargs):
        calls.append("failed")
        raise RuntimeError("controlled tool error")

    monkeypatch.setattr(wrapper._tools["read_skill_config"], "forward", failing)
    with pytest.raises(Exception, match="controlled tool error"):
        wrapper('read_skill_config(skill_name="demo")')
    assert calls == ["failed"]
    assert acquisitions == []
    event.set()
    with pytest.raises(RuntimeError, match="cancelled"):
        wrapper("print(1)")
    assert acquisitions == []
    wrapper.cleanup()
    wrapper.cleanup()
    assert releases == []
    with pytest.raises(RuntimeError, match="closed"):
        wrapper("print(1)")

    event.clear()
    wrapper, ordinary, _, acquisitions, releases = make_wrapper(monkeypatch, stop_event=event)

    def cancelled_acquisition():
        acquisitions.append(True)
        event.set()
        return ordinary

    wrapper._create_executor = cancelled_acquisition
    with pytest.raises(RuntimeError, match="cancelled"):
        wrapper("import math")
    assert releases == [ordinary]
    assert ordinary.calls == []
    wrapper.cleanup()
    assert releases == [ordinary]

    wrapper, ordinary, _, acquisitions, releases = make_wrapper(monkeypatch)

    def failing_variables(_variables):
        raise RuntimeError("controlled migration error")

    monkeypatch.setattr(ordinary, "send_variables", failing_variables)
    with pytest.raises(RuntimeError, match="controlled migration error"):
        wrapper("import math")
    assert acquisitions == [True]
    assert ordinary.calls == []
    assert wrapper.remote is None
    assert releases == [ordinary]
    wrapper.cleanup()
    assert releases == [ordinary]


@pytest.mark.parametrize("failure", ["workspace", "workspace_cancel", "binding_cancel"])
def test_tfp_d1_005_deferred_setup(monkeypatch, tmp_path, failure):
    """TFP-D1-005: failed setup releases leases and a retry uses a fresh group."""
    import nexent.core.agents.nexent_agent as factory_module
    import nexent.core.agents.sandbox as sandbox_module

    builds, closed, runner_cleanup, executors = [], [], [], []

    def build(**kwargs):
        builds.append(kwargs)
        group = kwargs["session_container_group"]
        if group is None:
            group = sandbox_module._SessionDockerContainerGroup(
                SimpleNamespace(cleanup=lambda: closed.append(True)),
            )
        group.acquire()
        raw = OrdinaryExecutor(group=group)
        executors.append(raw)
        return raw

    class ScriptRunner:
        def __init__(self, *args, **kwargs):
            if failure == "binding_cancel" and len(builds) == 1:
                event.set()

        def cleanup(self):
            runner_cleanup.append(True)

    monkeypatch.setattr(sandbox_module, "build_python_executor", build)
    monkeypatch.setattr(sandbox_module, "SandboxSkillScriptRunner", ScriptRunner)
    monkeypatch.setattr(
        sandbox_module, "cleanup_executor",
        lambda ex, *args, **kwargs: ex._nexent_session_container_group.release(),
    )
    monkeypatch.setattr(
        factory_module, "CoreAgent", lambda **kwargs: SimpleNamespace(**kwargs, python_executor=kwargs["executor"]),
    )
    event = threading.Event()
    runtime = NexentAgent(
        observer=MessageObserver(), model_config_list=[], stop_event=event,
        sandbox_config=SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SESSION),
        tool_fastpath_enabled=True, workspace_path=str(tmp_path),
    )
    monkeypatch.setattr(runtime, "create_model", lambda _: SimpleNamespace())

    def fail_setup(**kwargs):
        if failure != "workspace":
            event.set()
        else:
            raise RuntimeError("controlled workspace error")

    monkeypatch.setattr(runtime, "_initialize_sandbox_workspaces", fail_setup)
    root = runtime.create_single_agent(AgentConfig(name="root", description="Fixture", model_name="test", tools=[]))
    runtime.agent = root
    wrapper = root.python_executor
    with pytest.raises(RuntimeError, match="controlled workspace error" if failure == "workspace" else "cancelled"):
        wrapper("import math")
    assert runtime._sandbox_executors == []
    assert wrapper.remote is None
    assert closed == [True]
    if failure == "binding_cancel":
        assert executors[0].calls == []
    event.clear()
    monkeypatch.setattr(runtime, "_initialize_sandbox_workspaces", lambda **kwargs: None)
    wrapper("import math")
    assert len(builds) == 2
    assert all(kwargs["session_container_group"] is None for kwargs in builds)
    runtime._cleanup_sandbox()
    runtime._cleanup_sandbox()
    assert closed == [True, True]
    assert runner_cleanup == [True, True]


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
            script_runners.append(self)

        def cleanup(self):
            pass

    monkeypatch.setattr(sandbox_module, "build_python_executor", build)
    monkeypatch.setattr(sandbox_module, "SandboxSkillScriptRunner", ScriptRunner)
    monkeypatch.setattr(sandbox_module, "cleanup_executor", lambda ex, *args, **kwargs: releases.append(ex))
    monkeypatch.setattr(
        factory_module, "CoreAgent", lambda **kwargs: SimpleNamespace(**kwargs, python_executor=kwargs["executor"]),
    )
    runtime = NexentAgent(
        observer=MessageObserver(), model_config_list=[], stop_event=threading.Event(),
        sandbox_config=SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SESSION),
        workspace_path=str(tmp_path),
    )
    monkeypatch.setattr(runtime, "create_model", lambda _: SimpleNamespace())
    monkeypatch.setattr(runtime, "_pull_file_workspace_from_sandbox", lambda: preparations.append("pull"))
    monkeypatch.setattr(runtime, "_push_file_workspace_to_sandbox", lambda **kwargs: preparations.append("push"))
    monkeypatch.setattr(runtime, "_initialize_sandbox_workspaces", lambda **kwargs: preparations.append("initialize"))
    child_config = AgentConfig(name="child", description="Child fixture", model_name="test", tools=[])
    root_config = AgentConfig(
        name="root", description="Root fixture", model_name="test",
        tools=[ToolConfig(class_name="RunSkillScriptTool", name="run_skill_script", source="builtin")],
        managed_agents=[child_config],
    )
    root = runtime.create_single_agent(root_config)
    script_tool = root.tools[0]
    assert script_tool.execution_backend is None
    runtime.agent = root
    wrappers = list(runtime._tool_fastpath_executors)
    assert len(wrappers) == 2
    assert builds == []
    assert script_runners == []
    assert preparations == []
    for wrapper in wrappers:
        wrapper.send_tools({"final_answer": FinalAnswerTool()})
        wrapper("print(1)")
    assert builds == []
    root.python_executor("import math")
    assert script_tool.execution_backend is script_runners[0]
    if activate_child:
        wrappers[0]("import math")
    count = 2 if activate_child else 1
    assert len(builds) == count
    assert builds[0]["session_container_group"] is None
    if activate_child:
        assert builds[1]["session_container_group"] is group
    assert preparations == ["pull", "push", "initialize"] * count
    assert [raw.calls for raw in raw_executors] == [["[0, None]", "import math"]] * count
    runtime._cleanup_sandbox()
    runtime._cleanup_sandbox()
    assert len(releases) == count
    assert len({id(raw) for raw in releases}) == count
    assert runtime._sandbox_executors == []
    assert runtime._tool_fastpath_executors == []

    runtime.tool_fastpath_enabled = False
    eager = runtime.create_single_agent(child_config)
    assert eager.executor is raw_executors[-1]
    assert len(builds) == count + 1
    assert raw_executors[-1].calls == ["[0, None]"]


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
        "    import backend.consts.const as c\n"
        "print(json.dumps([c.NEXENT_TOOL_FASTPATH_ENABLED, c.NEXENT_TOOL_FASTPATH_ALLOWED_TOOLS]))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", source], cwd=Path(__file__).resolve().parents[3],
        env=environment, capture_output=True, text=True, timeout=10, check=True,
    )
    assert json.loads(result.stdout) == expected
