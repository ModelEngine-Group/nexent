"""TFP-D1-005: preserved fast-path acceptance checks."""

from __future__ import annotations

import threading
from concurrent.futures import CancelledError
from types import SimpleNamespace

import pytest
from shared.tool_fastpath import OrdinaryExecutor, make_wrapper
from shared.tool_fastpath_aidp import aidp_runtime as aidp_runtime

from nexent.core.agents.agent_model import AgentConfig
from nexent.core.agents.nexent_agent import NexentAgent
from nexent.core.agents.sandbox import SandboxConfig, SandboxLevel, SandboxScope
from nexent.core.utils.observer import MessageObserver


pytestmark = [pytest.mark.case_id("TFP-D1-005"), pytest.mark.stage("D1")]

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
    expected_error = CancelledError if failure == "binding_cancel" else RuntimeError
    with pytest.raises(expected_error, match="controlled workspace error" if failure == "workspace" else "cancelled"):
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

def test_tfp_d1_005_aidp(aidp_runtime):
    """TFP-D1-005: AIDP transport errors do not initialize Docker or replay requests."""
    executor = aidp_runtime.create().python_executor
    aidp_runtime.status.code = 400
    with pytest.raises(Exception, match="AIDP HTTP error"):
        executor('aidp_search(query="rules")')
    assert len(aidp_runtime.requests) == 1
    assert aidp_runtime.acquisitions == []
    assert executor.remote is None

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
