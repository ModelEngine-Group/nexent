# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Adapter resource registration preserves ownership, authorization and sandbox policy."""

import asyncio
import json
from threading import Event
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock, Mock

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
        wrapper = Mock(wraps=fn)
        wrapper.card = card
        return wrapper

    mocker.patch("openjiuwen.core.foundation.tool.LocalFunction", side_effect=local_function)
    handler = mocker.patch.object(adapter, "_business_handler", side_effect=lambda name, fn, **kwargs: fn)
    return handler


@pytest.mark.parametrize("text_protocol", [True, False])
@pytest.mark.parametrize("retriever", [False, True])
def test_prepare_registers_agent_cards_separately_from_tools(adapter, mocker, text_protocol, retriever):
    from openjiuwen.core.single_agent import AgentCard

    from nexent.core.agents.cores.jiuwen import collaboration

    child = AgentConfig(name="child", description="Child", model_name="child-model", tools=[])
    tools = [ToolConfig(name="lookup", class_name="Lookup", source="local"),
             ToolConfig(name="parallel_executor", class_name="ParallelExecutorTool", source="builtin"),
             ToolConfig(name="remote_lookup", class_name="RemoteLookup", source="mcp")]
    adapter.run_info.agent_config.tools = tools
    adapter.text_protocol = text_protocol
    adapter.run_info.agent_config.worker_agents = [child]
    adapter.tool_configs, adapter.visible_tool_names = tools, {"lookup", "child", "remote", "parallel_executor"}
    external = SimpleNamespace(invocation_name="remote", description="Remote", name="Remote", agent_id=9,
                               to_a2a_agent_info=Mock(return_value="external-info"))
    adapter.external_agents = [external]
    local, worker = Mock(), Mock()
    documents = [{"id": "doc-1", "content": "evidence", "source": "source-1"}]
    if retriever:
        local = type("KnowledgeBaseSearchTool", (), {})()
        local.forward = Mock(return_value=documents)
    original_forward = getattr(local, "forward")
    monitoring = Mock()
    from contextlib import nullcontext
    monitoring.trace_retriever_call.side_effect = lambda *args, **kwargs: nullcontext()
    mocker.patch("nexent.core.agents.resources.monitoring.get_monitoring_manager", return_value=monitoring)
    for tool, name in [(local, "lookup"), (worker, "child")]:
        tool.name, tool.description, tool.inputs = name, name, {"task": {"type": "string"}}
    resources = Mock()
    resources.create_tool.return_value = local
    resources._create_subagent_definition.return_value = worker
    resources._prepare_file_workspace.return_value = "Authorized latest task"
    resources._wrap_subagent.side_effect = lambda definition, *args, **kwargs: definition
    resource_type = mocker.patch("nexent.core.agents.cores.jiuwen.adapter.AgentResources", return_value=resources)
    capture_registration(adapter, mocker)
    native = adapter.native_agent
    factory = mocker.patch.object(collaboration, "create_collaboration_host", return_value=native)
    context_type = mocker.patch("nexent.core.agents.cores.jiuwen.context.JiuwenContextBridge")
    model = SimpleNamespace()
    mocker.patch.object(adapter, "_create_model", return_value=model)
    mocker.patch.object(adapter, "_compile_context", return_value="shared instructions")
    mocker.patch.object(adapter, "_bind_skill_sandbox")
    mocker.patch.object(adapter, "_skill_rails", return_value=[])
    parallel = mocker.patch.object(adapter, "_bind_parallel_tool")
    executor = mocker.patch.object(adapter, "_bind_text_executor")
    from nexent.core.agents.context.execution_history import ExecutionHistory
    from nexent.core.agents.contracts.context import ContextItemInput
    reader = Mock(return_value="old original")
    discovery = Mock(return_value={"results": [{"output_ref": "message:10/unit-index:3"}],
                                   "next_offset": 1, "eof": True})
    history = adapter.run_info.observer.execution_history = ExecutionHistory(
        read_conversation_result=reader, discover_summary_sources=discovery)
    adapter.context_items = [ContextItemInput(id="summary", type="history_summary", content={
        "summary": "Older results summarized", "covered_through_message_id": 50,
    })]
    adapter.run_info.tool_call_timeout_seconds = 900
    adapter.prepare()
    assert adapter.execution_history is history
    assert "old original" in adapter.business_tools["read_execution_output"].forward("message:10/unit-index:3")
    reader.assert_called_once_with(10, 3)
    discovered = json.loads(adapter.business_tools["read_execution_output"].forward("summary"))
    assert discovered["results"][0]["output_ref"] == "message:10/unit-index:3"
    discovery.assert_called_once()
    resources.create_tool.assert_called_once_with(tools[0])
    if retriever:
        assert local._nexent_monitoring_wrapped is True
        assert local.forward(task="search") is documents
        original_forward.assert_called_once_with(task="search")
        monitoring.trace_retriever_call.assert_called_once()
        monitoring.set_retriever_output.assert_called_once_with(documents)
        monitoring.trace_tool_call.assert_not_called()
    else:
        assert local.forward is original_forward
        monitoring.trace_retriever_call.assert_not_called()
        monitoring.trace_tool_call.assert_not_called()
    resources._create_subagent_definition.assert_called_once_with(child, {}, scope_factory=ANY)
    assert set(adapter.business_tools) == {"lookup", "child", "remote", "read_execution_output"}
    assert adapter.query == "Authorized latest task" and resources.core_run_info is adapter.run_info
    assert resource_type.call_args.kwargs["tenant_id"] == "tenant"
    assert resource_type.call_args.kwargs["user_id"] == "user"
    settings = factory.call_args.kwargs
    assert settings["system_prompt"] == "shared instructions" and settings["language"] == "cn"
    assert {tool.card.name for tool in settings["tools"]} == {"lookup", "read_execution_output"}
    assert settings["tool_owner_id"] == adapter.owner_id
    from openjiuwen.core.single_agent.ability_manager import AbilityManager
    assert all(AbilityManager._resolve_call_timeout(tool.card) == 900 for tool in settings["tools"])
    for key in ("enable_task_loop", "enable_sys_operation", "enable_read_image_multimodal",
                "enable_model_anomaly_detection_rail", "enable_tool_resilience_rail", "enable_skill_discovery"):
        assert settings[key] is False
    assert settings["parallel_tool_calls"] is not text_protocol
    assert not any(tool.card.parallel_safe for tool in settings["tools"])
    assert model.prefix == [] and model.prepare_messages == adapter._prepare_model_messages
    context_type.assert_called_once_with(adapter.run_info, adapter.scope, adapter.manager, model, adapter.context_items,
                                         message_format="openai_chat_completions")
    assert parallel.call_count == int(text_protocol)
    executor.assert_called_once()
    calls = native.ability_manager.add_collaborator.call_args_list
    assert [call.args[0].card.name for call in calls] == ["child", "remote"]
    for call in calls:
        delegate = call.args[0]
        assert isinstance(delegate.card, AgentCard) and delegate.card.input_params["additionalProperties"] is False
        assert delegate.card.id.startswith(adapter.owner_id)
        assert adapter.events.local_tool_schemas[delegate.card.name] == delegate.card.input_params
        assert delegate.parent_session == adapter.session_id
        assert call.kwargs == {"parallel_safe": False}
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
    allowed = ToolConfig(name="lookup", class_name="Lookup", source="mcp",
                         inputs='{"provider": {"type": "string"}}', usage="fixture-server")
    hidden = ToolConfig(name="hidden", class_name="Hidden", source="mcp",
                        inputs='{"provider": {"type": "string"}}', usage="fixture-server")
    adapter.tool_configs, adapter.visible_tool_names = [allowed, hidden], {"lookup"} if visible else set()
    adapter.run_info.mcp_host = ["http://fixture.invalid/mcp"]
    adapter.run_info.user_context = {"user_id": "captured", "tenant_id": "tenant"}
    lazy_tool = SimpleNamespace(card=SimpleNamespace(name="lookup", properties=None))
    collection = MagicMock()
    entered = collection.__enter__.return_value
    entered.create_tool.return_value = lazy_tool
    adapter.run_info.tool_call_timeout_seconds = 900
    owner = mocker.patch("nexent.core.agents.cores.jiuwen.mcp.JiuwenMCPCollection", return_value=collection)
    adapter._connect_mcp()
    if not visible:
        owner.assert_not_called()
        adapter.native_agent.ability_manager.add_ability.assert_not_called()
        return
    values = owner.call_args.kwargs
    assert "authorized_tools" not in values, "lazy tools are created per config after enter"
    assert values["user_context"] == adapter.run_info.user_context
    assert values["server_parameters"] == adapter.run_info.mcp_host
    assert values["cancellation_scope"] is adapter.scope and values["connect_timeout_seconds"] == 10.0
    entered.create_tool.assert_called_once_with(allowed)
    adapter.native_agent.ability_manager.add_ability.assert_called_once_with(lazy_tool.card, lazy_tool)
    # The real timeout setter annotated the lazy tool's card.
    assert lazy_tool.card.properties == {"resilience": {"timeout_s": 900}}


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
