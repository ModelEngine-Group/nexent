"""Agent factories defer initialization and release only resources they acquire."""

import json
from concurrent.futures import CancelledError
from contextlib import nullcontext
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from nexent.core.agents import nexent_agent as agent_module
from nexent.core.agents import sandbox
from nexent.core.agents.agent_model import AgentConfig, ToolConfig
from nexent.core.agents.nexent_agent import NexentAgent
from nexent.core.agents.tool_fastpath import DeferredToolExecutor
from nexent.core.tools.read_skill_config_tool import ReadSkillConfigTool
from nexent.core.utils.observer import MessageObserver


@pytest.fixture
def factory_execution(mocker, tmp_path):
    factory = NexentAgent(
        observer=Mock(spec=MessageObserver), model_config_list=[], stop_event=Event(),
        sandbox_config=sandbox.SandboxConfig(level=sandbox.SandboxLevel.DOCKER, failure_policy="error"),
        workspace_path=str(tmp_path),
    )
    tool = ReadSkillConfigTool(config_overrides={"demo": {"answer": "rules"}}, authorized_skill_names=["demo"])
    script_tool = Mock(name="script-tool")
    script_tool.name = "run_skill_script"
    mocker.patch.object(factory, "create_model", side_effect=lambda _: SimpleNamespace())
    mocker.patch.object(factory, "create_tool", side_effect=lambda config: (
        script_tool if config.class_name == "RunSkillScriptTool" else tool
    ))
    mocker.patch.object(agent_module, "_wrap_tool_with_monitoring", side_effect=lambda value, _: value)
    mocker.patch.object(agent_module, "CoreAgent", side_effect=lambda **kwargs: SimpleNamespace(
        **kwargs, python_executor=kwargs["executor"],
    ))
    monitor = Mock()
    monitor.trace_agent_step.side_effect = lambda *args, **kwargs: nullcontext()
    mocker.patch.object(agent_module, "get_monitoring_manager", return_value=monitor)
    group = SimpleNamespace(_closed=False)
    remotes = []

    def acquire(**kwargs):
        remote = Mock(
            _nexent_backend="docker", _nexent_session_container_group=group, _nexent_tool_bridge=None,
            container=SimpleNamespace(id="shared-container"),
        )
        remotes.append(remote)
        return remote

    build = mocker.patch.object(sandbox, "build_python_executor", side_effect=acquire)
    runner = mocker.patch.object(sandbox, "SandboxSkillScriptRunner")
    cleanup = mocker.patch.object(sandbox, "cleanup_executor")
    release = mocker.patch.object(sandbox, "release_python_executor")
    pull = mocker.patch.object(factory, "_pull_file_workspace_from_sandbox")
    push = mocker.patch.object(factory, "_push_file_workspace_to_sandbox")
    initialize = mocker.patch.object(factory, "_initialize_sandbox_workspaces")
    config = AgentConfig(name="root", description="Fixture", model_name="test", tools=[
        ToolConfig(name=tool.name, class_name="ReadSkillConfigTool", source="local"),
    ])
    yield SimpleNamespace(
        factory=factory, config=config, tool=tool, script_tool=script_tool, build=build, runner=runner,
        cleanup=cleanup, release=release, pull=pull, push=push, initialize=initialize,
        remotes=remotes, group=group, monitor=monitor,
    )
    factory._cleanup_sandbox()


@pytest.mark.parametrize("allowed", [None, ["ReadSkillConfigTool"], []])
def test_default_enablement_and_explicit_allowlist_control_only_activation(factory_execution, allowed):
    e = factory_execution
    assert e.factory.tool_fastpath_enabled is True
    e.factory.tool_fastpath_allowed_tools = allowed
    e.factory.agent = e.factory.create_single_agent(e.config)
    wrapper = e.factory.agent.python_executor
    assert isinstance(wrapper, DeferredToolExecutor)
    wrapper.send_tools({e.tool.name: e.tool})
    e.build.assert_not_called()
    e.monitor.trace_agent_step.assert_not_called()
    output = wrapper('result = read_skill_config("demo")\nprint(result)')
    if allowed == []:
        e.build.assert_called_once()
        assert wrapper.remote is e.remotes[0]
    else:
        assert json.loads(wrapper.state["result"]) == {"answer": "rules"}
        assert '"answer": "rules"' in output.logs
        e.build.assert_not_called()
        e.runner.assert_not_called()
        e.pull.assert_not_called()
        e.push.assert_not_called()
        e.initialize.assert_not_called()
    e.factory._cleanup_sandbox()
    e.factory._cleanup_sandbox()
    assert e.factory._tool_fastpath_executors == []
    assert e.factory.agent.python_executor is None
    assert e.cleanup.call_count == (1 if allowed == [] else 0)


def test_unknown_allowlist_rejects_construction_without_acquiring_resources(factory_execution):
    e = factory_execution
    e.factory.tool_fastpath_allowed_tools = ["CustomTool"]
    with pytest.raises(ValueError, match="Unknown official fast-path tool classes"):
        e.factory.create_single_agent(e.config)
    e.build.assert_not_called()
    assert e.factory._tool_fastpath_executors == []


@pytest.mark.parametrize("scope", [sandbox.SandboxScope.SESSION, sandbox.SandboxScope.SYSTEM])
def test_cleanup_deduplicates_wrapped_and_ordinary_resources_and_preserves_scope(factory_execution, scope):
    e = factory_execution
    e.factory.sandbox_config.scope = scope
    e.factory.agent = e.factory.create_single_agent(e.config)
    wrapper = e.factory.agent.python_executor
    wrapper('import math')
    remote = e.remotes[0]
    unwrapped = Mock()
    e.factory._sandbox_executors.extend([remote, unwrapped, unwrapped])
    e.factory._cleanup_sandbox()
    e.factory._cleanup_sandbox()
    lifecycle = e.release if scope == sandbox.SandboxScope.SYSTEM else e.cleanup
    unused = e.cleanup if scope == sandbox.SandboxScope.SYSTEM else e.release
    assert [call.args[0] for call in lifecycle.call_args_list] == [unwrapped, remote]
    unused.assert_not_called()
    e.runner.return_value.cleanup.assert_called_once()
    assert e.factory._sandbox_executors == []
    assert e.factory._sandbox_skill_runners == []
    assert e.factory._tool_fastpath_executors == []


def test_cold_cleanup_does_not_sync_outputs_or_start_any_backend(factory_execution, mocker):
    e = factory_execution
    e.factory.workspace_path = None
    e.factory.sandbox_config.auto_sync_outputs = True
    e.factory.minio_client = Mock()
    sync = mocker.patch.object(sandbox, "_sync_outputs_to_minio")
    e.factory.agent = e.factory.create_single_agent(e.config)
    wrapper = e.factory.agent.python_executor
    e.factory._cleanup_sandbox()
    sync.assert_not_called()
    e.build.assert_not_called()
    e.cleanup.assert_not_called()
    with pytest.raises(RuntimeError, match="closed"):
        wrapper('import math')


@pytest.mark.parametrize("activate_child", [False, True])
def test_root_and_child_keep_independent_executors_with_shared_session_container(factory_execution, activate_child):
    e = factory_execution
    child_config = e.config.model_copy(update={"name": "child"})
    tree = {}
    child = e.factory.create_single_agent(child_config, _managed_context=True, _sandbox_tree_context=tree)
    root = e.factory.create_single_agent(e.config, _sandbox_tree_context=tree)
    e.factory.agent = root
    assert root.python_executor is not child.python_executor
    for agent in (root, child):
        agent.python_executor.send_tools({e.tool.name: e.tool})
        agent.python_executor('print("ready")')
    e.build.assert_not_called()
    root.python_executor('import math')
    if activate_child:
        child.python_executor('import math')
    count = 2 if activate_child else 1
    assert len(e.remotes) == count
    assert e.build.call_args_list[0].kwargs["session_container_group"] is None
    if activate_child:
        assert e.build.call_args_list[1].kwargs["session_container_group"] is e.group
    assert tree["session_container_group"] is e.group
    e.factory._cleanup_sandbox()
    assert e.cleanup.call_count == count
    assert len({id(call.args[0]) for call in e.cleanup.call_args_list}) == count


def test_conflicting_session_group_releases_new_lease_before_skill_runner_creation(factory_execution):
    e = factory_execution
    tree = {"session_container_group": object()}
    e.factory.agent = e.factory.create_single_agent(e.config, _sandbox_tree_context=tree)
    with pytest.raises(RuntimeError, match="multiple session sandbox containers"):
        e.factory.agent.python_executor('import math')
    e.cleanup.assert_called_once_with(e.remotes[0], agent_module.logger, timeout=5.0)
    e.runner.assert_not_called()
    assert e.factory._sandbox_executors == []


def test_closed_session_group_is_removed_after_failed_activation(factory_execution):
    e = factory_execution
    tree = {}
    e.factory.agent = e.factory.create_single_agent(e.config, _sandbox_tree_context=tree)
    e.initialize.side_effect = RuntimeError("workspace failed")
    e.cleanup.side_effect = lambda *args, **kwargs: setattr(e.group, "_closed", True)
    with pytest.raises(RuntimeError, match="workspace failed"):
        e.factory.agent.python_executor('import math')
    assert "session_container_group" not in tree
    e.cleanup.assert_called_once()
    assert e.factory._sandbox_executors == []
    assert e.factory._sandbox_skill_runners == []


@pytest.mark.parametrize("phase", ["binding", "workspace"])
def test_failed_child_activation_retains_shared_skills_until_root_cleanup(factory_execution, phase):
    e = factory_execution
    root = NexentAgent(observer=Mock(spec=MessageObserver), model_config_list=[], stop_event=Event())
    root_lease = Mock()
    root.agent = SimpleNamespace(python_executor=root_lease)
    root._sandbox_executors.append(root_lease)
    e.factory._sandbox_skill_cleanup_owner = root
    e.config.tools = [ToolConfig(name="run_skill_script", class_name="RunSkillScriptTool", source="builtin")]
    if phase == "binding":
        e.script_tool.bind_execution_backend.side_effect = RuntimeError("child activation failed")
    else:
        e.initialize.side_effect = RuntimeError("child activation failed")
    e.factory.agent = e.factory.create_single_agent(e.config)
    with pytest.raises(RuntimeError, match="child activation failed"):
        e.factory.agent.python_executor('import math')
    runner = e.runner.return_value
    runner.cleanup.assert_not_called()
    assert root._sandbox_skill_runners == [runner]
    assert e.factory._sandbox_skill_runners == []
    assert e.factory._sandbox_executors == []
    e.cleanup.assert_called_once_with(e.remotes[0], agent_module.logger, timeout=5.0)
    e.factory._cleanup_sandbox()
    runner.cleanup.assert_not_called()
    root._close_subagent_invocations()
    root._cleanup_sandbox()
    root._cleanup_sandbox()
    runner.cleanup.assert_called_once()
    assert root._sandbox_skill_runners == []
    assert e.cleanup.call_count == 2
    assert e.cleanup.call_args.args[0] is root_lease


@pytest.mark.parametrize("error", [RuntimeError("bind failed"), CancelledError("bind cancelled")])
def test_skill_binding_failure_releases_executor_even_before_runner_is_registered(factory_execution, error):
    e = factory_execution
    e.config.tools = [ToolConfig(name="run_skill_script", class_name="RunSkillScriptTool", source="builtin")]
    e.script_tool.bind_execution_backend.side_effect = error
    e.factory.agent = e.factory.create_single_agent(e.config)
    wrapper = e.factory.agent.python_executor
    e.build.assert_not_called()
    with pytest.raises(type(error), match="bind"):
        wrapper('import math')
    assert wrapper.remote is None
    e.runner.return_value.cleanup.assert_called_once()
    e.cleanup.assert_called_once()
    assert e.factory._sandbox_executors == []
    assert e.factory._sandbox_skill_runners == []


@pytest.mark.parametrize("phase", ["acquire", "workspace"])
def test_factory_cancellation_after_acquisition_releases_lease(factory_execution, phase):
    e = factory_execution
    acquire = e.build.side_effect
    if phase == "acquire":
        def cancel(**kwargs):
            remote = acquire(**kwargs)
            e.factory.stop_event.set()
            return remote
        e.build.side_effect = cancel
    else:
        e.initialize.side_effect = CancelledError("workspace cancelled")
    e.factory.agent = e.factory.create_single_agent(e.config)
    with pytest.raises(CancelledError):
        e.factory.agent.python_executor('import math')
    e.cleanup.assert_called_once()
    assert e.factory._sandbox_executors == []
    assert e.factory._sandbox_skill_runners == []


def test_skill_backend_is_bound_only_on_activation_and_callback_pulls_outputs(factory_execution):
    e = factory_execution
    e.config.tools = [ToolConfig(name="run_skill_script", class_name="RunSkillScriptTool", source="builtin")]
    e.factory.agent = e.factory.create_single_agent(e.config)
    e.script_tool.bind_execution_backend.assert_not_called()
    e.factory.agent.python_executor('import math')
    binding = e.script_tool.bind_execution_backend.call_args
    assert binding.args == (e.runner.return_value,)
    e.pull.reset_mock()
    binding.kwargs["on_complete"](None)
    e.pull.assert_called_once_with()


def test_unwrapped_root_is_also_released_when_not_registered(factory_execution):
    e = factory_execution
    executor = Mock()
    e.factory.agent = SimpleNamespace(python_executor=executor)
    e.factory._cleanup_sandbox()
    e.cleanup.assert_called_once_with(executor, agent_module.logger, timeout=5.0)
    assert e.factory.agent.python_executor is None


def test_local_fallback_without_container_skips_copy_and_retains_actual_backend(factory_execution):
    e = factory_execution
    e.factory.sandbox_config.failure_policy = "local"
    acquire = e.build.side_effect

    def fallback(**kwargs):
        remote = acquire(**kwargs)
        remote._nexent_backend = "local"
        remote.container = None
        return remote

    e.build.side_effect = fallback
    e.factory.agent = e.factory.create_single_agent(e.config)
    wrapper = e.factory.agent.python_executor
    wrapper('import math')
    assert wrapper._nexent_backend == "local"
    assert wrapper.container is None
    e.push.assert_not_called()
    e.initialize.assert_called_once_with(executors=[e.remotes[0]])
    e.factory.observer.add_message.assert_called_once()
    wrapper('print("later")')
    e.build.assert_called_once()
