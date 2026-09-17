"""UT-SDK-TRACE-005/007: real sub-agent hierarchy and context restoration."""

from types import SimpleNamespace

import pytest
from nexent.core.agents.a2a_agent_proxy import ExternalA2AAgentWrapper
from nexent.core.agents.subagent_wrapper import SubAgentToolWrapper
from nexent.monitor import (
    AgentRunMetadata,
    agent_monitoring_context,
    get_agent_monitoring_context,
)
from opentelemetry import trace

from .conftest import assert_child, by_name


@pytest.mark.parametrize("entry", ["__call__", "forward"])
@pytest.mark.parametrize("fails", [False, True])
def test_ut_sdk_trace_005_nested_agent_span_and_balanced_events(spans, mocker, entry, fails):
    observer = mocker.Mock()
    seen = []

    def child(task):
        seen.append(get_agent_monitoring_context())
        with spans.tracer.start_as_current_span("generation"):
            if fails:
                raise ValueError("controlled failure")
            return "answer"

    wrapped = SubAgentToolWrapper(child, observer, agent_id=2, agent_name="child")
    parent_metadata = AgentRunMetadata(agent_id=1, tenant_id="tenant", conversation_id=42, agent_name="parent")
    with spans.manager.start_agent_run(parent_metadata):
        parent_span = trace.get_current_span()
        if fails:
            with pytest.raises(ValueError, match="controlled failure"):
                getattr(wrapped, entry)(task="question")
        else:
            assert getattr(wrapped, entry)(task="question") == "answer"
        assert get_agent_monitoring_context() is parent_metadata
        assert trace.get_current_span() is parent_span

    tree = by_name(spans)
    child_span = tree["agent.subagent.child"]
    assert_child(child_span, tree["agent.run"])
    assert_child(tree["generation"], child_span)
    assert child_span.attributes["openinference.span.kind"] == "AGENT"
    assert child_span.attributes["agent.id"] == 2
    assert child_span.attributes["parent.agent.id"] == 1
    assert child_span.status.is_ok == (not fails)
    if not fails:
        assert "answer" in child_span.attributes["output.value"]
    assert [(m.agent_id, m.agent_name, m.tenant_id, m.conversation_id) for m in seen] == [
        (2, "child", "tenant", 42)
    ]
    start = observer.add_subagent_start.call_args.kwargs
    end = observer.add_subagent_end.call_args.kwargs
    assert start["invocation_id"] == end["invocation_id"] == child_span.attributes["subagent.invocation_id"]
    assert observer.add_subagent_start.call_count == observer.add_subagent_end.call_count == 1


def test_ut_sdk_trace_005_forward_delegation_and_nested_children(spans, mocker):
    inner = SimpleNamespace(forward=lambda **kwargs: "nested-result")
    grandchild = SubAgentToolWrapper(inner, mocker.Mock(), agent_id=3, agent_name="grandchild")
    child = SubAgentToolWrapper(
        lambda **kwargs: grandchild.forward(**kwargs), mocker.Mock(), agent_id=2, agent_name="child"
    )
    with spans.manager.start_agent_run(AgentRunMetadata(agent_id=1)):
        assert child(task="question") == "nested-result"
    tree = by_name(spans)
    assert_child(tree["agent.subagent.child"], tree["agent.run"])
    assert_child(tree["agent.subagent.grandchild"], tree["agent.subagent.child"])


def test_ut_sdk_trace_007_subagent_without_monitoring(spans, mocker, monkeypatch):
    monkeypatch.setattr(spans.manager, "_config", None)
    child = SubAgentToolWrapper(lambda **kwargs: 42, mocker.Mock(), agent_name="child")
    with agent_monitoring_context(AgentRunMetadata(agent_name="parent")):
        assert child(task="test") == 42
        assert get_agent_monitoring_context().agent_name == "parent"
    assert not spans.exporter.get_finished_spans()


def test_ut_sdk_trace_005_external_a2a_adapter_is_a_nested_agent(spans, mocker):
    def remote_call(query, history, context):
        with spans.tracer.start_as_current_span("a2a-client-operation"):
            assert get_agent_monitoring_context().agent_id == "remote-id"
            return "remote answer"

    remote = object.__new__(ExternalA2AAgentWrapper)
    remote.name = "remote"
    remote._runtime_metadata = {"attempt": "synthetic"}
    remote._proxy = SimpleNamespace(sync_call=remote_call)
    wrapper = SubAgentToolWrapper(remote, mocker.Mock(), agent_id="remote-id", agent_name="remote")
    with spans.manager.start_agent_run(AgentRunMetadata(agent_id=1)):
        assert wrapper(task="test") == "remote answer"
    tree = by_name(spans)
    assert_child(tree["agent.subagent.remote"], tree["agent.run"])
    assert_child(tree["a2a-client-operation"], tree["agent.subagent.remote"])
