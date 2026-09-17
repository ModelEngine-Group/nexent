"""UT-SDK-TRACE-006: preserve existing thread and asyncio call ancestry."""

import asyncio
import importlib
from contextlib import asynccontextmanager

import mcp.types
import pytest
from nexent.core.agents.managed_mcp import ManagedMCPToolCollection
from nexent.core.agents.nexent_agent import _wrap_tool_with_monitoring
from nexent.core.concurrency import (
    ManagedTaskSpec,
    RunCancellationScope,
    get_current_thread_manager,
)
from nexent.core.ext_components.aidp.aidp_search_tool import AidpSearchTool
from nexent.core.tools.ind_aidp_search_tool import IndependentAidpSearchTool
from nexent.monitor import (
    AgentRunMetadata,
    agent_monitoring_context,
    get_agent_monitoring_context,
)

from .conftest import assert_child, by_name


def test_ut_sdk_trace_006_mcp_worker_and_event_loop_inherit_tool_span(spans, threads):
    class Session:
        async def call_tool(self, name, arguments):
            await asyncio.sleep(0)
            with spans.tracer.start_as_current_span("mcp-operation"):
                assert get_agent_monitoring_context().conversation_id == 42
                assert get_current_thread_manager() is threads
                return mcp.types.CallToolResult(content=[mcp.types.TextContent(type="text", text="done")])

    @asynccontextmanager
    async def connection(*args, **kwargs):
        yield Session(), [mcp.types.Tool(
            name="probe", description="test", inputSchema={"type": "object", "properties": {}},
        )]

    with ManagedMCPToolCollection(
        manager=threads, server_parameters=[{"url": "http://mcp.invalid/mcp"}],
        cancellation_scope=RunCancellationScope(), tool_timeout_seconds=2, close_timeout_seconds=1,
        session_context_factory=connection,
    ) as collection:
        tool = _wrap_tool_with_monitoring(collection.tools[0], "parent")
        with spans.manager.start_agent_run(AgentRunMetadata(conversation_id=42)):
            assert tool.forward() == "done"
    tree = by_name(spans)
    assert_child(tree["agent.tool.probe"], tree["agent.run"])
    assert_child(tree["mcp-operation"], tree["agent.tool.probe"])


@pytest.mark.parametrize("module_name", ["search_memory_tool", "store_memory_tool"])
@pytest.mark.parametrize("active_loop", [False, True])
def test_ut_sdk_trace_006_memory_coroutine_preserves_tool_context(spans, threads, module_name, active_loop):
    module = importlib.import_module(f"nexent.core.tools.{module_name}")

    async def operation():
        await asyncio.sleep(0)
        with spans.tracer.start_as_current_span("memory-operation"):
            assert get_current_thread_manager() is threads
            assert get_agent_monitoring_context().conversation_id == 42
            return "memory"

    async def caller():
        return module._run_coroutine(operation())

    def run():
        return asyncio.run(caller()) if active_loop else module._run_coroutine(operation())

    with spans.tracer.start_as_current_span("memory-tool"), agent_monitoring_context(
        AgentRunMetadata(conversation_id=42)
    ):
        execution = threads.submit("agent-run", ManagedTaskSpec("memory", "test"), run)
        assert execution.future.result(timeout=2) == "memory"
    tree = by_name(spans)
    assert_child(tree["memory-operation"], tree["memory-tool"])


@pytest.mark.parametrize("tool_class", [AidpSearchTool, IndependentAidpSearchTool])
def test_ut_sdk_trace_006_aidp_wrapper_preserves_parent_and_nested_operations(spans, mocker, tool_class):
    # Search response behavior belongs to the existing AIDP unit suites. Here
    # the real tool type and monitoring wrapper cross an isolated forward boundary.
    tool = object.__new__(tool_class)

    def search(query):
        with spans.tracer.start_as_current_span("aidp-operation"):
            return '{"results": []}'

    mocker.patch.object(tool, "forward", side_effect=search)
    tool = _wrap_tool_with_monitoring(tool, "parent")
    with spans.tracer.start_as_current_span("python"):
        assert tool.forward(query="test") == '{"results": []}'
    tree = by_name(spans)
    tool_span = tree[f"agent.tool.{tool.name}"]
    assert_child(tool_span, tree["python"])
    assert_child(tree["aidp-operation"], tool_span)
