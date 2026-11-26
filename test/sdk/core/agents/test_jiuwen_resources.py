# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Resource bridge validation, loop ownership and captured MCP parameters."""

import asyncio
from concurrent.futures import Future
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from jsonschema import ValidationError
from nexent.core.agents.cores.jiuwen.adapter import JiuwenAdapter
from nexent.core.agents.cores.jiuwen.resources import JiuwenResourceBridge
from nexent.core.agents.cores.jiuwen.mcp import JiuwenMCPCollection, _ManagedNativeClient
from nexent.core.concurrency import (
    LanePolicy,
    ManagedTaskSpec,
    RunCancellationScope,
    ThreadManager,
)
from nexent.core.concurrency.cancellation import RunTerminated
from nexent.consts.mcp_errors import MCPToolTimeoutError
from nexent.monitor.facts import set_fact_sink
from nexent.monitor.monitoring import AgentRunMetadata, agent_monitoring_context


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments,expected", [((2,), 2), (("wrong",), None), ((2, 3), None)])
async def test_text_bridge_returns_to_owned_loop_and_checks_schema(mocker, arguments, expected):
    from openjiuwen.core.runner import Runner

    tool = SimpleNamespace(invoke=AsyncMock(return_value=2))
    mocker.patch.object(Runner.resource_mgr, "get_tool", return_value=tool)
    card = SimpleNamespace(name="allowed", id="owned", input_params={
        "type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]})
    hidden = SimpleNamespace(name="hidden", id="hidden", input_params={})
    agent = SimpleNamespace(ability_manager=SimpleNamespace(list=lambda: [card, hidden]))
    scope = RunCancellationScope()
    bridge = JiuwenResourceBridge(agent, asyncio.get_running_loop(), scope, {"allowed"})
    bindings = bridge.bindings()
    assert set(bindings) == {"allowed"}
    manager = ThreadManager("bridge-unit", {"sandbox": LanePolicy(name="sandbox", max_workers=1, max_queue_size=1)})
    manager.start()
    try:
        execution = manager.submit("sandbox", ManagedTaskSpec(task_name="bridge-call", owner=__name__),
                                   bindings["allowed"], *arguments)
        if expected is not None:
            assert await asyncio.wrap_future(execution.future) == expected
            tool.invoke.assert_awaited_once_with({"a": 2})
        else:
            with pytest.raises((ValidationError, ValueError)):
                await asyncio.wrap_future(execution.future)
            tool.invoke.assert_not_awaited()
        scope.cancel()
        with pytest.raises(RunTerminated):
            bindings["allowed"](2)
    finally:
        assert not (await manager.shutdown(timeout=2)).stuck_execution_ids


@pytest.mark.asyncio
async def test_mcp_configured_values_and_captured_identity_override_model_input():
    manager = Mock()
    scope = RunCancellationScope()
    user = {"user_id": "captured", "user_groups": ["original"]}
    owner = JiuwenMCPCollection(authorized_tools=[], observe=Mock(), manager=manager, user_context=user,
        server_parameters=[], cancellation_scope=scope, tool_timeout_seconds=1, close_timeout_seconds=1)
    owner._call_tool = Mock(return_value=20)
    def submit(lane, spec, forward, *args):
        future = Future()
        future.set_result(forward(*args))
        return SimpleNamespace(future=future)
    manager.submit.side_effect = submit
    params = {"b": 4, "user_id": "untrusted-config"}
    client = _ManagedNativeClient(owner, "session", "multiply", ["user_id", "user_groups"], params)
    user["user_id"] = "later"
    user["user_groups"].append("later")
    params["b"] = 99
    assert await client.call_tool("multiply", {"a": 5, "b": 99, "user_id": "spoofed"}) == 20
    owner._call_tool.assert_called_once_with("session", "multiply", {
        "a": 5, "b": 4, "user_id": "captured", "user_groups": ["original"]})
    assert manager.submit.call_args.args[0] == "model-tool-io"


@pytest.mark.asyncio
@pytest.mark.parametrize("async_function", [False, True])
async def test_business_entry_awaits_both_async_functions_and_returned_awaitables(async_function):
    async def forward(value):
        return value + 1

    info = SimpleNamespace(agent_config=SimpleNamespace(name="fixture"), observer=Mock())
    adapter = JiuwenAdapter(info)
    adapter.scope = RunCancellationScope()
    adapter._observe_tool = Mock(return_value=nullcontext())
    adapter.manager = ThreadManager("async-resource-unit", {
        "model-tool-io": LanePolicy(name="model-tool-io", max_workers=1, max_queue_size=1)})
    adapter.manager.start()
    try:
        handler = adapter._business_handler("fixture", forward if async_function else lambda value: forward(value))
        assert await handler(value=4) == 5
        info.observer.add_message.assert_called_once()
    finally:
        assert not (await adapter.manager.shutdown(timeout=2)).stuck_execution_ids


@pytest.mark.asyncio
@pytest.mark.parametrize("authorized", [True, False, "empty"])
async def test_skill_root_and_name_must_both_belong_to_the_same_authorized_snapshot(tmp_path, authorized):
    from nexent.core.agents.cores.jiuwen.skills import NexentSkillRail

    first, second = tmp_path / "first", tmp_path / "second"
    path = first / ("allowed" if authorized else "second_only") / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text("authorized content", encoding="utf-8")
    rail = NexentSkillRail([str(first), str(second)], ["allowed", "second_only"],
        authorized_by_root={} if authorized == "empty" else {
            str(first): ["allowed"], str(second): ["second_only"]})
    if authorized is True:
        assert await rail._read_skill_text(path) == "authorized content"
    else:
        with pytest.raises(PermissionError):
            await rail._read_skill_text(path)


@pytest.mark.asyncio
async def test_mcp_native_call_emits_one_caller_observed_fact():
    facts = []
    set_fact_sink(facts.append)
    manager = ThreadManager("jiuwen-mcp-fact", {"model-tool-io": LanePolicy("model-tool-io", 1, 1)})
    manager.start()
    metadata = AgentRunMetadata(tenant_id="tenant-1", agent_id=7, monitoring_run_id="run-1",
                                monitoring_root_run_id="root-1", monitoring_group_ids=(1, 2), is_debug=False)
    try:
        owner = JiuwenMCPCollection(authorized_tools=[], observe=Mock(), manager=manager,
            server_parameters=[], cancellation_scope=RunCancellationScope(),
            tool_timeout_seconds=1, close_timeout_seconds=1)
        owner._call_tool = Mock(return_value=20)
        client = _ManagedNativeClient(owner, "session", "multiply", [], None, server_url="http://mcp.invalid/mcp")
        with agent_monitoring_context(metadata):
            result = await client.call_tool("multiply", {"a": 5})
    finally:
        set_fact_sink(None)
        assert not (await manager.shutdown(timeout=2)).stuck_execution_ids

    assert result == 20
    assert [fact["record_revision"] for fact in facts] == [1, 2]
    assert [fact["outcome"] for fact in facts] == ["started", "succeeded"]
    assert facts[0]["tool_name"] == "multiply"
    assert facts[0]["agent_run_id"] == "run-1"
    assert facts[0]["agent_id"] == 7
    assert facts[1]["fact_id"] == facts[0]["fact_id"]


@pytest.mark.asyncio
async def test_mcp_native_call_deadline_cancels_execution_and_closes_owner(caplog):
    manager = Mock()
    scope = RunCancellationScope()
    owner = JiuwenMCPCollection(authorized_tools=[], observe=Mock(), manager=manager,
        server_parameters=[], cancellation_scope=scope, tool_timeout_seconds=0.02, close_timeout_seconds=1)
    owner.request_close = Mock()
    execution = SimpleNamespace(future=Future(), execution_id=42)
    manager.submit.return_value = execution
    client = _ManagedNativeClient(owner, "session", "multiply", [], None)

    with pytest.raises(MCPToolTimeoutError):
        await client.call_tool("multiply", {"a": 5})

    assert isinstance(owner.terminal_error, MCPToolTimeoutError)
    owner.request_close.assert_called_once()
    manager.cancel.assert_called_once_with(42, reason="MCP tool deadline exceeded", wait_timeout=0,
                                           mark_stuck_on_timeout=False)
    assert [record.levelname for record in caplog.records if "event=mcp_tool_timeout" in record.getMessage()] == \
        ["WARNING"]
    execution.future.cancel()


@pytest.mark.asyncio
async def test_mcp_native_call_cancelled_await_closes_owner_without_cancel_submission():
    manager = Mock()
    scope = RunCancellationScope()
    owner = JiuwenMCPCollection(authorized_tools=[], observe=Mock(), manager=manager,
        server_parameters=[], cancellation_scope=scope, tool_timeout_seconds=1, close_timeout_seconds=1)
    owner.request_close = Mock()
    execution = SimpleNamespace(future=Future(), execution_id=7)
    manager.submit.return_value = execution
    client = _ManagedNativeClient(owner, "session", "multiply", [], None)
    task = asyncio.create_task(client.call_tool("multiply", {"a": 5}))
    while not manager.submit.called:
        await asyncio.sleep(0.001)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    owner.request_close.assert_called_once()
    manager.cancel.assert_not_called()
    execution.future.cancel()


@pytest.mark.asyncio
async def test_mcp_native_call_refuses_dispatch_after_run_cancellation():
    manager = Mock()
    scope = RunCancellationScope()
    scope.cancel()
    owner = JiuwenMCPCollection(authorized_tools=[], observe=Mock(), manager=manager,
        server_parameters=[], cancellation_scope=scope, tool_timeout_seconds=1, close_timeout_seconds=1)
    client = _ManagedNativeClient(owner, "session", "multiply", [], None)

    with pytest.raises(asyncio.CancelledError):
        await client.call_tool("multiply", {"a": 5})

    manager.submit.assert_not_called()
