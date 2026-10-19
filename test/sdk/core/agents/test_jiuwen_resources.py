"""Resource bridge validation, loop ownership and captured MCP parameters."""

import asyncio
from concurrent.futures import Future
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from jsonschema import ValidationError
from nexent.core.agents.core_adapters.jiuwen import JiuwenAdapter
from nexent.core.agents.core_adapters.jiuwen_resources import JiuwenResourceBridge
from nexent.core.agents.core_adapters.mcp import (
    JiuwenMCPCollection,
    _ManagedNativeClient,
)
from nexent.core.concurrency import (
    LanePolicy,
    ManagedTaskSpec,
    RunCancellationScope,
    ThreadManager,
)
from nexent.core.concurrency.cancellation import RunTerminated


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
    from nexent.core.agents.core_adapters.skills import NexentSkillRail

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
