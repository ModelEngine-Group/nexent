"""Run-local tool policy and deferred official-tool registration must agree."""

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
from nexent.core.tools.knowledge_base_search_tool import KnowledgeBaseSearchTool
from nexent.core.tools.read_skill_config_tool import ReadSkillConfigTool
from nexent.core.utils.observer import MessageObserver


@pytest.fixture
def policy_factory(mocker):
    factory = NexentAgent(
        observer=Mock(spec=MessageObserver), model_config_list=[], stop_event=Event(),
        sandbox_config=sandbox.SandboxConfig(level=sandbox.SandboxLevel.DOCKER, failure_policy="error"),
    )
    knowledge = object.__new__(KnowledgeBaseSearchTool)
    read = ReadSkillConfigTool(config_overrides={"demo": {"value": "rules"}}, authorized_skill_names=["demo"])
    script = Mock()
    script.name = "run_skill_script"
    tools = {tool.name: tool for tool in (knowledge, read, script)}
    configurations = [
        ToolConfig(name=tool.name, class_name=class_name, source=source, metadata={"schema_version": "v1"})
        for tool, class_name, source in (
            (knowledge, "KnowledgeBaseSearchTool", "local"),
            (read, "ReadSkillConfigTool", "builtin"),
            (script, "RunSkillScriptTool", "builtin"),
        )
    ]
    create_tool = mocker.patch.object(factory, "create_tool", side_effect=lambda config: tools[config.name])
    mocker.patch.object(factory, "create_model", side_effect=lambda _: SimpleNamespace())
    mocker.patch.object(agent_module, "_wrap_tool_with_monitoring", side_effect=lambda tool, _: tool)
    core = mocker.patch.object(agent_module, "CoreAgent", side_effect=lambda **kwargs: SimpleNamespace(
        **kwargs, python_executor=kwargs["executor"],
    ))
    remote = Mock(_nexent_backend="docker", _nexent_session_container_group=None, _nexent_tool_bridge=None)
    build = mocker.patch.object(sandbox, "build_python_executor", return_value=remote)
    runner = mocker.patch.object(sandbox, "SandboxSkillScriptRunner")
    cleanup = mocker.patch.object(sandbox, "cleanup_executor")
    monitoring = Mock()
    monitoring.trace_agent_step.side_effect = lambda *args, **kwargs: nullcontext()
    mocker.patch.object(agent_module, "get_monitoring_manager", return_value=monitoring)
    config = AgentConfig(name="root", description="Policy regression", model_name="fixture", tools=configurations)
    yield SimpleNamespace(
        factory=factory, config=config, tools=tools, knowledge=knowledge, read=read,
        create_tool=create_tool, core=core, build=build, runner=runner, cleanup=cleanup,
    )
    factory._cleanup_sandbox()


def apply_policy(config, allowed, *, hidden=()):
    config.prompt_tool_policy_snapshot = {
        "enabled": list(allowed), "allowed": list(allowed), "system_default_hidden": list(hidden),
        "policy_version": "policy-1", "tool_schema_version": "v1",
    }


@pytest.mark.parametrize("selection", ["first-two", "middle-only", "first-only", "none", "all"])
@pytest.mark.parametrize("managed", [False, True], ids=["root", "child"])
def test_filtered_configuration_and_instances_stay_paired_without_starting_docker(policy_factory, selection, managed):
    e = policy_factory
    names = [config.name for config in e.config.tools]
    allowed = {
        "first-two": names[:2], "middle-only": names[1:2], "first-only": names[:1], "none": [], "all": names,
    }[selection]
    original = list(e.config.tools)
    apply_policy(e.config, allowed)
    e.factory.agent = e.factory.create_single_agent(e.config, _managed_context=managed)
    wrapper = e.factory.agent.python_executor
    assert isinstance(wrapper, DeferredToolExecutor)
    assert [call.args[0].name for call in e.create_tool.call_args_list] == allowed
    assert e.core.call_args.kwargs["tools"] == [e.tools[name] for name in allowed]
    expected_fastpath = {name: e.tools[name] for name in allowed if name != "run_skill_script"}
    assert wrapper._allowed_tools == expected_fastpath
    assert e.config.tools == original
    wrapper.send_tools({name: e.tools[name] for name in allowed})
    output = wrapper('value = "ready"\nprint(value)')
    assert output.logs.strip() == "ready"
    if e.read.name in allowed:
        assert '"value": "rules"' in wrapper('read_skill_config("demo")').output
    e.build.assert_not_called()
    e.runner.assert_not_called()


def test_schema_filtering_cannot_shift_official_implementation_matching(policy_factory):
    e = policy_factory
    names = [config.name for config in e.config.tools]
    e.config.tools[0].metadata = {"schema_version": "stale"}
    apply_policy(e.config, names)
    e.factory.agent = e.factory.create_single_agent(e.config)
    wrapper = e.factory.agent.python_executor
    assert [call.args[0].name for call in e.create_tool.call_args_list] == names[1:]
    assert wrapper._allowed_tools == {e.read.name: e.read}
    e.build.assert_not_called()


def test_hidden_executable_tools_use_execution_policy_instead_of_visible_registry(policy_factory):
    e = policy_factory
    apply_policy(e.config, [e.read.name], hidden=[e.knowledge.name])
    e.factory.agent = e.factory.create_single_agent(e.config)
    wrapper = e.factory.agent.python_executor
    assert wrapper._allowed_tools == {e.knowledge.name: e.knowledge, e.read.name: e.read}
    audit = e.factory.observer.add_message.call_args.args[2]
    assert e.read.name in audit and e.knowledge.name not in audit
    e.build.assert_not_called()


def test_filtered_same_class_mcp_tool_does_not_gain_official_host_eligibility(policy_factory):
    e = policy_factory
    e.config.tools[0].source = "mcp"
    apply_policy(e.config, [e.knowledge.name, e.read.name])
    e.factory.agent = e.factory.create_single_agent(e.config)
    assert e.factory.agent.python_executor._allowed_tools == {e.read.name: e.read}
    e.build.assert_not_called()


def test_filtered_out_tool_is_never_executed_or_migrated(policy_factory, mocker):
    e = policy_factory
    forward = mocker.patch.object(e.read, "forward", wraps=e.read.forward)
    apply_policy(e.config, [e.knowledge.name])
    e.factory.agent = e.factory.create_single_agent(e.config)
    wrapper = e.factory.agent.python_executor
    wrapper.send_tools({e.knowledge.name: e.knowledge})
    code = 'read_skill_config("demo")'
    wrapper(code)
    e.build.assert_called_once()
    assert e.build.return_value.call_args_list[-1].args == (code,)
    assert set(e.build.return_value.send_tools.call_args.args[0]) == {e.knowledge.name}
    forward.assert_not_called()


def test_disabled_fastpath_keeps_filtered_eager_factory_behavior(policy_factory):
    e = policy_factory
    e.factory.tool_fastpath_enabled = False
    apply_policy(e.config, [e.read.name])
    e.factory.agent = e.factory.create_single_agent(e.config)
    assert e.factory.agent.python_executor is e.build.return_value
    assert e.core.call_args.kwargs["tools"] == [e.read]
    e.build.assert_called_once()
    e.build.return_value.assert_called_once_with('[0, None]')
