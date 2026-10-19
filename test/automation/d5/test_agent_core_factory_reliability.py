"""AGENT-CORE-D5-001: Cancellation, MCP deadlines and native resource isolation."""

import asyncio
import json
import time
from threading import Event

import httpx
import pytest

from nexent.core.agents.agent_model import AgentConfig, AgentRunInfo, ModelConfig, ToolConfig
from nexent.core.agents.core_adapters.jiuwen import JiuwenAdapter
from nexent.core.agents.run_agent import agent_run
from nexent.core.concurrency import RunCancellationScope
from nexent.core.utils.observer import MessageObserver

from test.automation.d3.test_agent_core_factory_native import native_manager, native_provider  # noqa: F401


def make_run(manager, url, query="block_model"):
    stop = Event()
    return AgentRunInfo(query=query, observer=MessageObserver(lang="en"), stop_event=stop,
                        cancellation_scope=RunCancellationScope(stop), thread_manager=manager,
                        model_config_list=[ModelConfig(cite_name="fixture", model_name="fixture-model", url=url + "/v1",
                                                       timeout_seconds=5)],
                        agent_config=AgentConfig(agent_core="jiuwen", name="same-name", description="Fixture",
                                                 model_name="fixture", tools=[]))


@pytest.mark.parametrize("status,attempts", [(400, 1), (503, 2)])
def test_native_provider_failure_is_bounded(native_manager, native_provider, status, attempts):
    info = make_run(native_manager, native_provider, f"FAIL_MODEL_{status}")

    async def consume():
        return [message async for message in agent_run(info, thread_manager=native_manager)]

    output = asyncio.run(consume())
    state = httpx.get(native_provider + "/state", trust_env=False).json()
    assert info.attempt_outcome == "failed"
    assert state["model_calls"] == attempts and state["mcp_calls"] == 0
    assert not any("native_result_20" in message for message in output)


def test_AGENT_CORE_D5_001_cancellation_deadline_and_isolation(native_manager, native_provider):  # noqa: F811
    from openjiuwen.core.foundation.tool import LocalFunction, ToolCard
    from openjiuwen.core.runner import Runner

    from nexent.consts.mcp_errors import MCPToolTimeoutError
    from nexent.core.agents.core_adapters.mcp import JiuwenMCPCollection

    info = make_run(native_manager, native_provider)

    async def cancel_blocked_model():
        async def consume():
            return [message async for message in agent_run(info, thread_manager=native_manager)]

        consumer = asyncio.create_task(consume())
        async with httpx.AsyncClient(trust_env=False) as client:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if (await client.get(native_provider + "/state")).json()["model_calls"]:
                    break
                await asyncio.sleep(0.05)
            else:
                raise AssertionError("Native model never started")
        started = time.monotonic()
        info.cancellation_scope.cancel()
        output = await asyncio.wait_for(consumer, 5)
        assert time.monotonic() - started < 5
        assert info.attempt_outcome == "stopped"
        assert not any(json.loads(message).get("type") == "final_answer" for message in output)

    asyncio.run(cancel_blocked_model())
    first, second = JiuwenAdapter(make_run(native_manager, native_provider, "fixture")), JiuwenAdapter(
        make_run(native_manager, native_provider, "fixture"))
    try:
        for adapter in [first, second]:
            adapter.validate()
            adapter.prepare()
        for index, adapter in enumerate([first, second]):
            card = ToolCard(name="same_tool", description="Isolated tool", input_params={"type": "object"})

            async def value(_index=index):
                return _index

            adapter.native_agent.ability_manager.add_ability(card, LocalFunction(card, value))
        first_card = first.native_agent.ability_manager.get("same_tool")
        second_card = second.native_agent.ability_manager.get("same_tool")
        assert first_card.id != second_card.id
        assert asyncio.run(Runner.resource_mgr.get_tool(first_card.id).invoke({})) == 0
        assert asyncio.run(Runner.resource_mgr.get_tool(second_card.id).invoke({})) == 1
        first.close()
        assert Runner.resource_mgr.get_tool(first_card.id) is None
        assert Runner.resource_mgr.get_tool(second_card.id) is not None
    finally:
        first.close()
        second.close()

    collection = JiuwenMCPCollection(
        authorized_tools=[ToolConfig(name="multiply", class_name="multiply", source="mcp", params={})],
        observe=lambda *args: None, manager=native_manager, server_parameters=[native_provider + "/mcp"],
        cancellation_scope=RunCancellationScope(), tool_timeout_seconds=0.2, close_timeout_seconds=2,
        connect_timeout_seconds=5, user_context={"user_id": "fixture-user"},
    )
    with collection as connected:
        async def timeout_call():
            with pytest.raises(Exception):
                await connected.tools[0].invoke({"a": 2, "b": 2, "user_id": "forged-user"})
            assert collection.terminal_error is None
            try:
                await connected.tools[0].invoke({"a": 999, "b": 2})
            except Exception:
                assert isinstance(collection.terminal_error, MCPToolTimeoutError)
            else:
                raise AssertionError("Stalled MCP call did not time out")

        asyncio.run(timeout_call())
    assert not collection._active_calls
    assert collection._execution.future.done()
    assert collection._loop is None
    state = httpx.get(native_provider + "/state", trust_env=False).json()
    assert state["user_id"] == "fixture-user"
