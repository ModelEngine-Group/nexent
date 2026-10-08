"""UT-SDK-TRACE-016..018: the main Agent owns the Langfuse trace name."""

import asyncio
from contextlib import nullcontext

import pytest
from opentelemetry import trace

from nexent.core.agents.subagent_wrapper import SubAgentToolWrapper
from nexent.monitor import AgentRunMetadata, get_agent_monitoring_context

from .conftest import assert_child, by_name


@pytest.mark.parametrize("with_http_parent", [False, True])
@pytest.mark.parametrize("fail", [False, True])
def test_ut_sdk_trace_016_named_run_preserves_operations_and_parent(spans, with_http_parent, fail):
    metadata = AgentRunMetadata(
        agent_name="knowledge_agent", agent_display_name="知识助手", user_id="account", user_email="user@example.com",
    )
    parent_scope = spans.tracer.start_as_current_span("POST /agent/run") if with_http_parent else nullcontext()
    with parent_scope:
        previous = trace.get_current_span()
        expected = pytest.raises(RuntimeError, match="run failed") if fail else nullcontext()
        with expected, spans.manager.start_agent_run(metadata):
            if fail:
                raise RuntimeError("run failed")
        assert trace.get_current_span() is previous
        assert get_agent_monitoring_context() is None

    tree = by_name(spans)
    run = tree["agent.run"]
    assert run.attributes["langfuse.trace.name"] == "知识助手"
    assert run.attributes["agent.name"] == "knowledge_agent"
    assert run.attributes["agent.display_name"] == "知识助手"
    assert run.attributes["user.id"] == "user@example.com"
    assert run.status.is_ok == (not fail)
    if with_http_parent:
        assert_child(run, tree["POST /agent/run"])
    else:
        assert run.parent is None


@pytest.mark.parametrize("display_name", [None, "子助手"])
def test_ut_sdk_trace_017_children_cannot_rename_the_trace(spans, mocker, display_name):
    def child():
        with spans.manager.start_agent_run(AgentRunMetadata(agent_name="nested-agent")):
            with spans.manager.trace_llm_request("model.generate", "model"):
                pass
            with spans.manager.trace_tool_call("search", "child", {"query": "test"}):
                pass
        return "done"

    child.display_name = display_name
    wrapped = SubAgentToolWrapper(child, mocker.Mock(), agent_name="child")
    with spans.manager.start_agent_run(AgentRunMetadata(agent_name="main-agent", agent_display_name="主助手")):
        assert wrapped() == "done"

    finished = spans.exporter.get_finished_spans()
    named = [s for s in finished if "langfuse.trace.name" in s.attributes]
    assert len(named) == 1
    run = named[0]
    assert run.name == "agent.run"
    assert run.attributes["langfuse.trace.name"] == "主助手"
    assert sum(s.name == "agent.run" for s in finished) == 1
    tree = by_name(spans)
    subagent = tree["agent.subagent.child"]
    assert subagent.attributes["agent.name"] == "child"
    assert subagent.attributes.get("agent.display_name") == display_name
    assert_child(subagent, run)
    assert_child(tree["model.generate"], subagent)
    assert_child(tree["agent.tool.search"], subagent)


@pytest.mark.parametrize("name", [None, "", " \t "])
def test_ut_sdk_trace_018_missing_name_preserves_default(spans, name):
    with spans.manager.start_agent_run(AgentRunMetadata(agent_name=name)):
        pass
    run, = spans.exporter.get_finished_spans()
    assert run.name == "agent.run"
    assert "langfuse.trace.name" not in run.attributes


@pytest.mark.asyncio
async def test_ut_sdk_trace_018_concurrent_names_are_isolated(spans):
    async def run(name):
        with spans.manager.start_agent_run(AgentRunMetadata(agent_name="variable", agent_display_name=name)):
            await asyncio.sleep(0)

    await asyncio.gather(run("agent-one"), run("agent-two"))
    await run(None)
    finished = spans.exporter.get_finished_spans()
    assert len({s.context.trace_id for s in finished}) == 3
    assert {s.attributes.get("langfuse.trace.name") for s in finished} == {"agent-one", "agent-two", "variable"}
    assert get_agent_monitoring_context() is None


def test_ut_sdk_trace_018_disabled_monitoring_preserves_execution(spans, monkeypatch):
    monkeypatch.setattr(spans.manager._config, "enable_telemetry", False)
    with spans.manager.start_agent_run(AgentRunMetadata(agent_name="main-agent")) as span:
        assert span is None
    assert not spans.exporter.get_finished_spans()
    assert get_agent_monitoring_context() is None
