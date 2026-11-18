# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""MCP tool-call capture emits content-free facts with a two-phase lifecycle."""

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest
from nexent.consts.mcp_errors import MCPToolTimeoutError
from nexent.core.concurrency.cancellation import RunTerminated
from nexent.monitor import mcp_fact
from nexent.monitor.facts import set_fact_sink
from nexent.monitor.mcp_fact import (
    McpToolCallObservation,
    observe_mcp_tool_call,
    resolve_mcp_server_identity,
    suppress_mcp_tool_calls,
)
from nexent.monitor.monitoring import AgentRunMetadata, agent_monitoring_context
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


def _metadata(**overrides):
    values = {
        "tenant_id": "tenant-1",
        "agent_id": 7,
        "monitoring_run_id": "run-1",
        "monitoring_root_run_id": "root-1",
        "monitoring_group_ids": (1, 2),
        "is_debug": False,
    }
    values.update(overrides)
    return AgentRunMetadata(**values)


def _record(facts, action):
    """Run ``action`` with a capturing sink that is always reset afterwards."""
    set_fact_sink(facts.append)
    try:
        return action()
    finally:
        set_fact_sink(None)


def test_dispatch_emits_one_started_revision():
    facts = []

    def run_call():
        with agent_monitoring_context(_metadata()):
            observation = McpToolCallObservation(
                "search", {"mcp_server_id": 3, "mcp_server_name": "docs", "mcp_server_type": "container"}
            )
            observation.dispatch()
            observation.dispatch()

    _record(facts, run_call)
    assert len(facts) == 1
    fact = facts[0]
    assert fact["record_revision"] == 1
    assert fact["outcome"] == "started"
    assert fact["fact_kind"] == "mcp_tool"
    assert fact["tool_name"] == "search"
    assert fact["mcp_server_id"] == 3
    assert fact["mcp_server_name"] == "docs"
    assert fact["mcp_server_type"] == "container"
    assert fact["tenant_id"] == "tenant-1"
    started = datetime.fromisoformat(fact["started_at"])
    assert started.tzinfo is not None
    assert len(fact["fact_id"]) == 64
    assert fact["fact_id"] != fact["call_context_id"]
    assert "ended_at" not in fact
    assert "duration_ms" not in fact


def test_finish_emits_single_terminal_revision():
    facts = []

    def run_call():
        with agent_monitoring_context(_metadata()):
            observation = McpToolCallObservation("search")
            observation.dispatch()
            observation.finish()
            observation.finish()
            observation.finish()

    _record(facts, run_call)
    assert [fact["record_revision"] for fact in facts] == [1, 2]
    started, terminal = facts
    assert terminal["fact_id"] == started["fact_id"]
    assert terminal["outcome"] == "succeeded"
    assert isinstance(terminal["duration_ms"], int)
    assert terminal["duration_ms"] >= 0
    assert datetime.fromisoformat(terminal["ended_at"]) >= datetime.fromisoformat(started["started_at"])
    assert "error_category" not in terminal


def test_finish_without_dispatch_emits_nothing():
    facts = []

    def run_call():
        with agent_monitoring_context(_metadata()):
            McpToolCallObservation("search").finish()

    _record(facts, run_call)
    assert facts == []


@pytest.mark.parametrize(
    ("error", "outcome", "category"),
    [
        (MCPToolTimeoutError("tool timed out"), "failed", "TIMEOUT"),
        (asyncio.CancelledError(), "cancelled", None),
        (RunTerminated(), "cancelled", None),
        (GeneratorExit(), "cancelled", None),
        (ValueError("boom"), "failed", "MCP_TOOL_FAILURE"),
    ],
)
def test_terminal_outcome_mapping(error, outcome, category):
    facts = []

    def run_call():
        with agent_monitoring_context(_metadata()):
            observation = McpToolCallObservation("search")
            observation.dispatch()
            observation.finish(error)

    _record(facts, run_call)
    assert len(facts) == 2
    assert facts[1]["outcome"] == outcome
    if category is None:
        assert "error_category" not in facts[1]
    else:
        assert facts[1]["error_category"] == category


def test_observe_context_manager_emits_both_revisions():
    facts = []

    def run_call():
        with agent_monitoring_context(_metadata()):
            with observe_mcp_tool_call({"mcp_server_id": 5}, "search") as observation:
                assert observation.payload["mcp_server_type"] == "unknown"

    _record(facts, run_call)
    assert [fact["record_revision"] for fact in facts] == [1, 2]
    assert facts[1]["outcome"] == "succeeded"


def test_observe_context_manager_maps_failure_and_reraises():
    facts = []

    def run_call():
        with agent_monitoring_context(_metadata()):
            with pytest.raises(ValueError):
                with observe_mcp_tool_call(None, "search"):
                    raise ValueError("boom")

    _record(facts, run_call)
    assert [fact["record_revision"] for fact in facts] == [1, 2]
    assert facts[1]["outcome"] == "failed"
    assert facts[1]["error_category"] == "MCP_TOOL_FAILURE"


def test_sink_exception_is_isolated():
    def raising_sink(event):
        raise RuntimeError("sink down")

    set_fact_sink(raising_sink)
    try:
        with agent_monitoring_context(_metadata()):
            with observe_mcp_tool_call({"mcp_server_type": "remote"}, "search") as observation:
                pass
    finally:
        set_fact_sink(None)
    assert observation.started is not None
    assert observation.terminal is not None


def test_inert_when_sink_unbound_at_construction():
    facts = []
    set_fact_sink(None)
    try:
        with agent_monitoring_context(_metadata()):
            observation = McpToolCallObservation("search")
            set_fact_sink(facts.append)
            try:
                observation.dispatch()
                observation.finish()
            finally:
                set_fact_sink(None)
    finally:
        set_fact_sink(None)
    assert facts == []


def test_inert_without_context():
    facts = []

    def run_call():
        McpToolCallObservation("search").dispatch()

    _record(facts, run_call)
    assert facts == []


def test_inert_for_debug_runs():
    facts = []

    def run_call():
        with agent_monitoring_context(_metadata(is_debug=True)):
            McpToolCallObservation("search").dispatch()

    _record(facts, run_call)
    assert facts == []


def test_inert_when_suppressed():
    facts = []

    def run_call():
        with suppress_mcp_tool_calls():
            with agent_monitoring_context(_metadata()):
                McpToolCallObservation("search").dispatch()

    _record(facts, run_call)
    assert facts == []


def test_attribution_fields_come_from_context():
    facts = []

    def run_call():
        with agent_monitoring_context(_metadata()):
            observation = McpToolCallObservation("search")
            observation.dispatch()

    _record(facts, run_call)
    fact = facts[0]
    assert fact["agent_id"] == 7
    assert fact["agent_run_id"] == "run-1"
    assert fact["root_run_id"] == "root-1"
    assert fact["initiator_group_ids"] == (1, 2)


def test_trace_bound_from_current_recording_span():
    facts = []
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(SimpleSpanProcessor(InMemorySpanExporter()))
    try:
        with provider.get_tracer("test").start_as_current_span("agent.tool.search") as span:

            def run_call():
                with agent_monitoring_context(_metadata()):
                    observation = McpToolCallObservation("search")
                    observation.dispatch()
                    observation.finish()

            _record(facts, run_call)
    finally:
        provider.shutdown()
    context = span.get_span_context()
    assert facts[0]["trace_id"] == f"{context.trace_id:032x}"
    assert facts[0]["span_id"] == f"{context.span_id:016x}"
    assert facts[1]["trace_id"] == facts[0]["trace_id"]
    assert facts[1]["span_id"] == facts[0]["span_id"]


def test_no_trace_fields_without_current_span():
    facts = []

    def run_call():
        with agent_monitoring_context(_metadata()):
            observation = McpToolCallObservation("search")
            observation.dispatch()

    _record(facts, run_call)
    assert "trace_id" not in facts[0]
    assert "span_id" not in facts[0]


def test_server_identity_defaults_to_unknown():
    with agent_monitoring_context(_metadata()):
        observation = McpToolCallObservation("search")
    assert observation.payload["mcp_server_type"] == "unknown"
    assert observation.payload["mcp_server_id"] is None
    assert observation.payload["mcp_server_name"] is None


def test_server_identity_lookup_without_catalog_returns_none():
    assert resolve_mcp_server_identity("http://mcp.invalid/mcp", "search") is None
    with agent_monitoring_context(_metadata()):
        assert resolve_mcp_server_identity("http://mcp.invalid/mcp", "search") is None


def test_server_identity_lookup_matches_catalog_entry_by_url(monkeypatch):
    catalog = [{
        "url": "http://docs.invalid/mcp",
        "mcp_server_id": 3,
        "mcp_server_name": "docs",
        "mcp_server_type": "container",
    }]
    monkeypatch.setattr(mcp_fact, "get_agent_monitoring_context",
                        lambda: SimpleNamespace(monitoring_mcp_servers=catalog))
    identity = resolve_mcp_server_identity("http://docs.invalid/mcp", "search")
    assert identity == {"mcp_server_id": 3, "mcp_server_name": "docs", "mcp_server_type": "container"}
    assert resolve_mcp_server_identity("http://other.invalid/mcp", "search") is None


def test_server_identity_tool_override_takes_precedence(monkeypatch):
    catalog = [{
        "url": "http://local.invalid/mcp/tenant-1/sse",
        "mcp_server_id": None,
        "mcp_server_name": "outer-apis",
        "mcp_server_type": "builtin",
        "tool_types": {"search_docs": "api_convert"},
    }]
    monkeypatch.setattr(mcp_fact, "get_agent_monitoring_context",
                        lambda: SimpleNamespace(monitoring_mcp_servers=catalog))
    url = "http://local.invalid/mcp/tenant-1/sse"
    overridden = resolve_mcp_server_identity(url, "search_docs")
    assert overridden["mcp_server_type"] == "api_convert"
    assert overridden["mcp_server_name"] == "outer-apis"
    url_level = resolve_mcp_server_identity(url, "builtin_tool")
    assert url_level["mcp_server_type"] == "builtin"
    assert resolve_mcp_server_identity("http://other.invalid/mcp", "search_docs") is None
