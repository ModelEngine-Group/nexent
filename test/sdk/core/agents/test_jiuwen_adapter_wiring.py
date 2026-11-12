# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Adapter resource registration preserves ownership, authorization and sandbox policy."""

import asyncio
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from nexent.core.agents.contracts.config import AgentConfig, ToolConfig
from nexent.core.agents.contracts.run import AgentRunInfo
from nexent.core.agents.cores.jiuwen.adapter import JiuwenAdapter
from nexent.core.agents.sandbox.config import SandboxConfig, SandboxLevel
from nexent.core.concurrency import RunCancellationScope
from nexent.core.concurrency.cancellation import RunTerminated
from nexent.core.utils.observer import MessageObserver


@pytest.fixture
def adapter():
    info = AgentRunInfo(query="Latest task", tenant_id="tenant", user_id="user", stop_event=Event(),
        observer=MessageObserver(lang="zh"), model_config_list=[],
        agent_config=AgentConfig(name="fixture", description="Fixture", model_name="model", tools=[]))
    instance = JiuwenAdapter(info)
    instance.scope, instance.manager = RunCancellationScope(info.stop_event), Mock()
    instance.run_info.thread_manager = instance.manager
    instance.native_agent = SimpleNamespace(ability_manager=Mock())
    instance.resources = SimpleNamespace(agent=SimpleNamespace(python_executor=None),
        _sandbox_executors=[], _sandbox_skill_runners=[], workspace_mapping="mapping",
        _pull_file_workspace_from_sandbox=Mock())
    return instance


def capture_registration(adapter, mocker):
    def local_function(card, fn):
        fn.card = card
        return fn

    mocker.patch("openjiuwen.core.foundation.tool.LocalFunction", side_effect=local_function)
    handler = mocker.patch.object(adapter, "_business_handler", side_effect=lambda name, fn, **kwargs: fn)
    return handler


def test_prepare_registers_tools_children_and_per_call_a2a_proxies(adapter, mocker):
    from openjiuwen.harness import factory as native_factory

    child = AgentConfig(name="child", description="Child", model_name="child-model", tools=[])
    tools = [ToolConfig(name="lookup", class_name="Lookup", source="local"),
             ToolConfig(name="parallel_executor", class_name="ParallelExecutorTool", source="builtin"),
             ToolConfig(name="remote_lookup", class_name="RemoteLookup", source="mcp")]
    adapter.run_info.agent_config.tools = tools
    adapter.run_info.agent_config.worker_agents = [child]
    adapter.tool_configs, adapter.visible_tool_names = tools, {"lookup", "child", "remote", "parallel_executor"}
    external = SimpleNamespace(invocation_name="remote", description="Remote", name="Remote", agent_id=9,
                               to_a2a_agent_info=Mock(return_value="external-info"))
    adapter.external_agents = [external]
    local, worker = Mock(), Mock()
    for tool, name in [(local, "lookup"), (worker, "child")]:
        tool.name, tool.description, tool.inputs = name, name, {"task": {"type": "string"}}
    resources = Mock()
    resources.create_tool.return_value = local
    resources._create_subagent_definition.return_value = worker
    resources._prepare_file_workspace.return_value = "Authorized latest task"
    resources._wrap_subagent.side_effect = lambda definition, *args, **kwargs: definition
    resource_type = mocker.patch("nexent.core.agents.cores.jiuwen.adapter.AgentResources", return_value=resources)
    mocker.patch("nexent.core.agents.cores.jiuwen.adapter._wrap_tool_with_monitoring", side_effect=lambda tool, name: tool)
    capture_registration(adapter, mocker)
    native = adapter.native_agent
    factory = mocker.patch.object(native_factory, "create_deep_agent", return_value=native)
    context_type = mocker.patch("nexent.core.agents.cores.jiuwen.context.JiuwenContextBridge")
    model = SimpleNamespace()
    mocker.patch.object(adapter, "_create_model", return_value=model)
    mocker.patch.object(adapter, "_compile_context", return_value="shared instructions")
    mocker.patch.object(adapter, "_bind_skill_sandbox")
    mocker.patch.object(adapter, "_skill_rails", return_value=[])
    parallel = mocker.patch.object(adapter, "_bind_parallel_tool")
    executor = mocker.patch.object(adapter, "_bind_text_executor")
    adapter.context_items = []
    adapter.run_info.tool_call_timeout_seconds = 900
    proxies = [Mock(return_value="first"), Mock(return_value="second")]
    proxy_type = mocker.patch("nexent.core.agents.resources.a2a.ExternalA2AAgentWrapper", side_effect=proxies)
    adapter.prepare()
    resources.create_tool.assert_called_once_with(tools[0])
    resources._create_subagent_definition.assert_called_once_with(child, {})
    assert set(adapter.business_tools) == {"lookup", "child", "remote"}
    assert adapter.query == "Authorized latest task" and resources.core_run_info is adapter.run_info
    assert resource_type.call_args.kwargs["tenant_id"] == "tenant"
    assert resource_type.call_args.kwargs["user_id"] == "user"
    settings = factory.call_args.kwargs
    assert settings["system_prompt"] == "shared instructions" and settings["language"] == "cn"
    assert len(settings["tools"]) == 3 and settings["tool_owner_id"] == adapter.owner_id
    # Every native business/child/A2A card uses the run's deployment deadline.
    from openjiuwen.core.single_agent.ability_manager import AbilityManager
    assert all(AbilityManager._resolve_call_timeout(tool.card) == 900 for tool in settings["tools"])
    for key in ("enable_task_loop", "enable_sys_operation", "enable_read_image_multimodal",
                "enable_model_anomaly_detection_rail", "enable_tool_resilience_rail", "enable_skill_discovery",
                "parallel_tool_calls"):
        assert settings[key] is False
    assert model.prefix == [] and model.prepare_messages == adapter._prepare_model_messages
    context_type.assert_called_once_with(adapter.run_info, adapter.scope, adapter.manager, model, [])
    parallel.assert_called_once()
    executor.assert_called_once()
    remote = adapter.business_tools["remote"]
    assert remote.forward("task one") == "first" and remote.forward("task two") == "second"
    assert proxy_type.call_count == 2
    for proxy, task in zip(proxies, ["task one", "task two"]):
        proxy.set_runtime_metadata.assert_called_once_with(adapter.run_info.runtime_metadata)
        proxy.assert_called_once_with(task=task)
    adapter.scope.cancel()
    with pytest.raises(RunTerminated):
        remote.forward("forbidden after stop")
    assert proxy_type.call_count == 2
    card, terminal = native.ability_manager.add_ability.call_args.args
    assert card.name == adapter.clarification.name
    with pytest.raises(RuntimeError, match="escaped the model boundary"):
        terminal(questions=[])


def test_cancelled_prepare_does_not_allocate_resources(adapter, mocker):
    resources = mocker.patch("nexent.core.agents.cores.jiuwen.adapter.AgentResources")
    adapter.run_info.stop_event.set()
    with pytest.raises(RunTerminated):
        adapter.prepare()
    resources.assert_not_called()


@pytest.mark.parametrize("level", [None, SandboxLevel.LOCAL, SandboxLevel.DOCKER])
def test_skill_execution_uses_configured_sandbox_and_sync_callback(adapter, mocker, level):
    adapter.run_info.sandbox_config = None if level is None else SandboxConfig(level=level, network_disabled=True)
    build = mocker.patch("nexent.core.agents.sandbox.execution.build_python_executor", return_value="executor")
    runner_type = mocker.patch("nexent.core.agents.sandbox.execution.SandboxSkillScriptRunner", return_value="runner")
    skill, ordinary = Mock(), Mock()
    skill.name, ordinary.name = "run_skill_script", "lookup"
    adapter.business_tools = {"run_skill_script": skill, "lookup": ordinary}
    adapter._bind_skill_sandbox()
    if level != SandboxLevel.DOCKER:
        build.assert_not_called()
        runner_type.assert_not_called()
        assert adapter.resources._sandbox_executors == []
        return
    assert adapter.resources.agent.python_executor == "executor"
    assert adapter.resources._sandbox_executors == ["executor"]
    assert adapter.resources._sandbox_skill_runners == ["runner"]
    assert runner_type.call_args.kwargs["network_enabled"] is False
    assert runner_type.call_args.kwargs["workspace_mapping"] == "mapping"
    skill.bind_execution_backend.assert_called_once()
    skill.bind_execution_backend.call_args.kwargs["on_complete"]("result")
    adapter.resources._pull_file_workspace_from_sandbox.assert_called_once()
    ordinary.bind_execution_backend.assert_not_called()


@pytest.mark.parametrize("name", ["lookup", "parallel_executor", "not-authorized"])
def test_parallel_registration_limits_calls_to_authorized_bindings(adapter, mocker, name):
    capture_registration(adapter, mocker)
    scheduler = Mock()
    scheduler.forward.return_value = {"answer": 5}
    scheduler_type = mocker.patch("nexent.core.tools.parallel_executor.ParallelExecutorTool", return_value=scheduler)
    lookup = Mock()
    adapter.resource_bridge = SimpleNamespace(bindings=lambda: {"lookup": lookup})
    adapter._bind_parallel_tool()
    scheduler_type.assert_called_once_with(execution_lane="control-io")
    card, forward = adapter.native_agent.ability_manager.add_ability.call_args.args
    assert card.name == "parallel_executor" and card.input_params["additionalProperties"] is False
    tasks = [{"tool_name": name, "arguments": {"a": 2}, "result_key": "answer"}]
    if name == "lookup":
        assert forward(tasks, timeout=3, max_workers=2) == {"answer": 5}
        scheduler.forward.assert_called_once_with([(lookup, {"a": 2}, "answer")], timeout=3, max_workers=2)
    else:
        with pytest.raises(PermissionError, match="unavailable resource"):
            forward(tasks)
        scheduler.forward.assert_not_called()


@pytest.mark.parametrize("visible", [False, True])
def test_mcp_connection_uses_only_visible_authorized_tools_and_resolved_deadlines(adapter, mocker, visible):
    allowed = ToolConfig(name="lookup", class_name="Lookup", source="mcp")
    hidden = ToolConfig(name="hidden", class_name="Hidden", source="mcp")
    adapter.tool_configs, adapter.visible_tool_names = [allowed, hidden], {"lookup"} if visible else set()
    adapter.run_info.mcp_host = ["http://fixture.invalid/mcp"]
    adapter.run_info.user_context = {"user_id": "captured", "tenant_id": "tenant"}
    collection = MagicMock()
    from openjiuwen.core.foundation.tool import ToolCard
    card = ToolCard(name="lookup", description="Remote lookup", properties={"provider": "fixture"})
    collection.__enter__.return_value.tools = [SimpleNamespace(card=card)]
    adapter.run_info.tool_call_timeout_seconds = 900
    owner = mocker.patch("nexent.core.agents.cores.jiuwen.mcp.JiuwenMCPCollection", return_value=collection)
    adapter._connect_mcp()
    if not visible:
        owner.assert_not_called()
        adapter.native_agent.ability_manager.add_ability.assert_not_called()
        return
    values = owner.call_args.kwargs
    assert values["authorized_tools"] == [allowed] and values["user_context"] == adapter.run_info.user_context
    assert values["server_parameters"] == adapter.run_info.mcp_host
    assert values["cancellation_scope"] is adapter.scope and values["connect_timeout_seconds"] == 10.0
    adapter.native_agent.ability_manager.add_ability.assert_called_once_with(
        card, collection.__enter__.return_value.tools[0])
    assert card.properties == {"provider": "fixture", "resilience": {"timeout_s": 900}}


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["before", "during", "success", "boundary"])
async def test_message_preparation_never_retries_a_terminal_mcp_error(adapter, phase):
    error = RuntimeError("MCP terminal")
    adapter.mcp = SimpleNamespace(terminal_error=error if phase == "before" else None)

    async def prepare(messages, tools):
        if phase == "during":
            adapter.mcp.terminal_error = error
        return ["prepared"]

    adapter.context_bridge = SimpleNamespace(prepare_messages=AsyncMock(side_effect=prepare))
    if phase == "boundary":
        adapter.run_info.observer.boundary_reached = True
        with pytest.raises(asyncio.CancelledError):
            await adapter._prepare_model_messages([], [])
        adapter.context_bridge.prepare_messages.assert_not_awaited()
    elif phase == "success":
        assert await adapter._prepare_model_messages([], []) == ["prepared"]
        adapter.context_bridge.prepare_messages.assert_awaited_once_with([], [])
    else:
        with pytest.raises(RuntimeError) as caught:
            await adapter._prepare_model_messages([], [])
        assert caught.value is error
        assert adapter.context_bridge.prepare_messages.await_count == (phase == "during")
