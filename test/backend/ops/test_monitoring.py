# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Unit coverage for shared keys, collection and model statistics."""

import json
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import Literal
from unittest.mock import Mock, call
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from nexent.monitor.facts import emit_fact, set_fact_sink
from nexent.monitor.model_fact import AttemptObservation
from nexent.monitor.monitoring import _MonitoredChatCompletions
from ops.monitoring.contracts import Fact, MonitoringKind, day_id
from ops.monitoring.mcp_tool import (
    MCP_TOOL_MONITORING,
    McpToolFact,
    accumulate_mcp_tool,
    summarize as summarize_mcp_tool,
)
from ops.monitoring.model import MODEL_MONITORING, ModelFact, accumulate_model, summarize
from ops.monitoring.runtime import MONITORING_KINDS, Producer
from ops.monitoring.search import delete_documents, install_templates
from ops.monitoring.service import CLEANUP_INTERVAL_SECONDS, Monitoring, _apply_revision


def fact(**overrides):
    return ModelFact.model_validate({
        "tenant_id": "tenant", "fact_id": "attempt", "call_context_id": "request",
        "model_id": 7, "model_type": "llm", "started_at": "2026-10-31T17:00:00Z",
        "record_revision": 1, "outcome": "started", **overrides,
    }).document(ZoneInfo("Asia/Shanghai"))


def tool_fact(**overrides):
    return McpToolFact.model_validate({
        "tenant_id": "tenant", "fact_id": "invocation", "call_context_id": "run",
        "tool_name": "search_docs", "mcp_server_type": "unknown",
        "started_at": "2026-10-31T17:00:00Z",
        "record_revision": 1, "outcome": "started", **overrides,
    }).document(ZoneInfo("Asia/Shanghai"))


def test_routing_and_scope_keys():
    item = fact(initiator_group_ids=[2, 1, 2])
    assert item["statistic_date"] == "2026-11-01"
    assert item["partition_anchor_at"].startswith("2026-10-31")
    assert item["initiator_group_ids"] == [1, 2]
    day = date(2026, 11, 1)
    assert day_id("tenant", "model", day) != day_id("tenant", "mcp_tool", day)


def test_producer_persists_distinct_dates_from_the_fact_contract():
    class SkillFact(Fact):
        fact_kind: Literal["skill"] = "skill"

        def statistic_day(self, zone):
            return super().statistic_day(zone) + timedelta(days=1)

    producer = Producer(Mock(), ZoneInfo("Asia/Shanghai"), {"skill": MonitoringKind(SkillFact, lambda _: ())})
    event = {
        "tenant_id": "tenant", "fact_kind": "skill", "fact_id": "attempt", "call_context_id": "request",
        "started_at": "2026-10-31T17:00:00Z", "record_revision": 1, "outcome": "started",
    }
    producer.emit(event)
    producer.emit({**event, "record_revision": 2, "outcome": "succeeded"})
    producer.emit({**event, "fact_id": "later", "started_at": "2026-11-02T17:00:00Z"})

    (_, tenant, kind, payload, days), = producer.drain()

    assert (tenant, kind) == ("tenant", "skill")
    assert len(json.loads(payload)) == 3
    assert days == [date(2026, 11, 2), date(2026, 11, 4)]


def test_template_mapping_conflicts_fail_before_updating_elasticsearch():
    es = Mock()
    tool = MonitoringKind(Fact, lambda _: (), daily_fields={"call_count": "long"})
    skill = MonitoringKind(Fact, lambda _: (), daily_fields={"call_count": "keyword"})

    with pytest.raises(ValueError, match="Incompatible monitoring mapping for call_count"):
        install_templates(es, 0, [tool, skill])

    assert es.mock_calls == []


def test_daily_cleanup_deletes_exact_documents_and_accepts_an_already_deleted_id():
    es = Mock()
    es.bulk.return_value = {"items": [{"delete": {"status": 200}}, {"delete": {"status": 404}}]}
    hits = [{"_index": "monitoring-daily-2026.11", "_id": doc_id} for doc_id in ("old", "already-deleted")]

    delete_documents(es, iter(hits))

    es.bulk.assert_called_once_with(operations=[{"delete": hit} for hit in hits])


def test_daily_cleanup_reports_rejected_deletion():
    es = Mock()
    es.bulk.return_value = {"items": [{"delete": {"status": 403}}]}

    with pytest.raises(RuntimeError, match="Monitoring bulk deletion failed"):
        delete_documents(es, iter([{"_index": "monitoring-daily-2026.11", "_id": "old"}]))


def test_hourly_cleanup_retries_next_sweep_and_does_not_block_other_scopes(monkeypatch):
    now = 100
    monkeypatch.setattr("ops.monitoring.service.monotonic", lambda: now)
    store = Mock()
    store.batch_scopes.return_value = store.dirty_scopes.return_value = []
    store.published_scopes.return_value = [("first", "model"), ("second", "model")]
    service = Monitoring(store, Mock(), ZoneInfo("UTC"), {"model": MODEL_MONITORING})
    cleanup = Mock(side_effect=[RuntimeError("Temporary ES error"), None, None])
    cleanup.__name__ = "cleanup"
    monkeypatch.setattr(service, "cleanup", cleanup)

    service.tick()
    service.tick()
    service.tick()
    assert cleanup.call_args_list == [call("first", "model"), call("second", "model")]

    now += CLEANUP_INTERVAL_SECONDS
    service.tick()
    assert cleanup.call_args_list[-1] == call("first", "model")
    assert store.published_scopes.call_count == 2


def test_revision_replay_and_terminal_precedence():
    started = fact()
    completed = fact(record_revision=2, outcome="succeeded", total_tokens=0)
    assert _apply_revision(started, completed)
    assert not _apply_revision({**completed, "write_version": 3}, completed)
    assert not _apply_revision(completed, started)
    with pytest.raises(ValueError, match="Conflicting"):
        _apply_revision(completed, {**completed, "total_tokens": 5})


def test_rollup_preserves_known_zero_and_excludes_cancellation():
    rows = [
        fact(outcome="succeeded", total_tokens=0, duration_ms=40),
        fact(outcome="failed", duration_ms=60),
        fact(outcome="cancelled", duration_ms=200),
    ]
    result = summarize(row for _, row in accumulate_model(rows))
    assert result["request_count"] == 3
    assert result["error_eligible_count"] == 2
    assert result["error_rate"] == 0.5
    assert result["avg_duration_ms"] == 50
    assert result["total_tokens"]["value"] == "0"
    assert result["total_tokens"]["known_count"] == 1
    assert result["input_tokens"]["value"] is None


def test_dispatch_is_unique_per_attempt_and_probes_are_excluded():
    emitted = []
    profile = SimpleNamespace(outlet_id=7, identity=SimpleNamespace(tenant_id="tenant", model_type="llm"))
    request = SimpleNamespace(request_id="request", purpose="agent", run_id="run")
    set_fact_sink(emitted.append)
    try:
        failed = AttemptObservation(request, profile, 1)
        failed.finish()
        assert not emitted
        failed.dispatch()
        failed.dispatch()
        failed.finish(RuntimeError())
        success = AttemptObservation(request, profile, 2)
        success.dispatch()
        success.complete(None)
        success.finish()
        request.purpose = "connection_validation"
        AttemptObservation(request, profile, 1).dispatch()
    finally:
        set_fact_sink(None)
    assert [item["outcome"] for item in emitted] == ["started", "failed", "started", "succeeded"]
    assert emitted[0]["fact_id"] == emitted[1]["fact_id"]
    assert emitted[1]["fact_id"] != emitted[2]["fact_id"]
    assert all("trace_id" not in item and "span_id" not in item for item in emitted)


def test_shared_sink_accepts_a_non_model_fact():
    events = []
    payload = {"fact_kind": "skill"}
    set_fact_sink(events.append)
    try:
        emit_fact(payload)
    finally:
        set_fact_sink(None)
    emit_fact(payload)
    assert events == [payload]


@pytest.mark.parametrize("stream", [False, True])
def test_legacy_chat_shares_provider_usage_with_ops(mocker, stream):
    class ProviderReply:
        reads = 0

        @property
        def usage(self):
            self.reads += 1
            return SimpleNamespace(prompt_tokens=0, completion_tokens=None, total_tokens=7)

    reply = ProviderReply()
    legacy = mocker.patch("nexent.monitor.monitoring._enqueue_client_monitoring_record")
    client = _MonitoredChatCompletions(SimpleNamespace(create=lambda **_: iter([reply]) if stream else reply),
                                      "model", "llm")
    client.catalog_identity = ("tenant", 7, "llm")
    events = []
    set_fact_sink(events.append)
    try:
        result = client.create(stream=stream)
        if stream:
            assert list(result) == [reply]
        else:
            assert result is reply
    finally:
        set_fact_sink(None)

    assert reply.reads == 1
    assert legacy.call_args.kwargs["total_tokens"] == 0
    assert [fact["outcome"] for fact in events] == ["started", "succeeded"]
    assert events[-1]["input_tokens"] == 0
    assert events[-1].get("output_tokens") is None
    assert events[-1]["total_tokens"] == 7


def test_mcp_tool_fact_accepts_documented_fields():
    item = tool_fact(
        record_revision=2, outcome="failed", duration_ms=120, error_category="TIMEOUT",
        mcp_server_id=3, mcp_server_name="docs", mcp_server_type="container",
        agent_id=7, agent_run_id="run-1", root_run_id="root-1",
        initiator_group_ids=[1, 2], trace_id="a" * 32, span_id="b" * 16,
    )
    assert item["fact_kind"] == "mcp_tool"
    assert item["tool_name"] == "search_docs"
    assert item["mcp_server_type"] == "container"
    assert item["error_category"] == "TIMEOUT"
    assert item["trace_id"] == "a" * 32


def test_mcp_tool_fact_rejects_unknown_fields_and_invalid_enums():
    with pytest.raises(ValidationError):
        tool_fact(tool_arguments={"q": "secret"})
    with pytest.raises(ValidationError):
        tool_fact(mcp_server_type="bogus")
    with pytest.raises(ValidationError):
        tool_fact(outcome="started", duration_ms=10)
    with pytest.raises(ValidationError):
        tool_fact(error_category="not_upper")


def test_mcp_tool_accumulate_groups_by_server_tool_agent_and_group():
    common = dict(mcp_server_id=3, mcp_server_name="docs", mcp_server_type="container")
    rows = [
        tool_fact(outcome="succeeded", duration_ms=40, agent_id=7, agent_run_id="run-1", **common),
        tool_fact(outcome="failed", duration_ms=60, error_category="TIMEOUT", agent_id=7, agent_run_id="run-1", **common),
        tool_fact(outcome="cancelled", duration_ms=200, agent_id=7, agent_run_id="run-1", **common),
        tool_fact(outcome="started", agent_id=7, agent_run_id="run-1", **common),
        tool_fact(outcome="succeeded", duration_ms=10, agent_id=8, agent_run_id="run-2", **common),
        tool_fact(outcome="succeeded", duration_ms=5, agent_id=7, agent_run_id="run-1", initiator_group_ids=[9], **common),
        tool_fact(outcome="succeeded", duration_ms=7, mcp_server_id=4, mcp_server_name="other",
                  mcp_server_type="remote", agent_id=7, agent_run_id="run-1"),
        tool_fact(outcome="succeeded", duration_ms=3, **common),
    ]
    result = dict(accumulate_mcp_tool(rows))
    assert len(result) == 5
    # Rows only carry dimensions present on the group's facts (exclude_none documents).
    grouped = {
        (row.get("mcp_server_id"), row.get("agent_id"), row["has_agent_run"],
         tuple(row.get("initiator_group_ids") or ()), row.get("mcp_server_name"),
         row.get("mcp_server_type")): row
        for row in result.values()
    }
    main = grouped[(3, 7, True, (), "docs", "container")]
    assert main["request_count"] == 4
    assert main["error_count"] == 1
    assert main["error_eligible_count"] == 2
    assert main["duration_ms_sum"] == 100
    assert main["duration_ms_sample_count"] == 2
    assert grouped[(3, 8, True, (), "docs", "container")]["duration_ms_sum"] == 10
    assert grouped[(3, 7, True, (9,), "docs", "container")]["duration_ms_sum"] == 5
    assert grouped[(4, 7, True, (), "other", "remote")]["duration_ms_sum"] == 7
    unattributed = grouped[(3, None, False, (), "docs", "container")]
    assert unattributed["request_count"] == 1
    assert unattributed["duration_ms_sum"] == 3


def test_mcp_tool_summarize_excludes_cancellation_from_duration():
    rows = [
        tool_fact(outcome="succeeded", duration_ms=40),
        tool_fact(outcome="failed", duration_ms=60),
        tool_fact(outcome="cancelled", duration_ms=200),
    ]
    result = summarize_mcp_tool(row for _, row in accumulate_mcp_tool(rows))
    assert result["request_count"] == 3
    assert result["error_eligible_count"] == 2
    assert result["error_rate"] == 0.5
    assert result["avg_duration_ms"] == 50


def test_mcp_tool_revision_replay_and_terminal_precedence():
    started = tool_fact()
    completed = tool_fact(record_revision=2, outcome="succeeded", duration_ms=50)
    assert _apply_revision(started, completed)
    assert not _apply_revision({**completed, "write_version": 3}, completed)
    assert not _apply_revision(completed, started)
    with pytest.raises(ValueError, match="Conflicting"):
        _apply_revision(completed, {**completed, "duration_ms": 999})


def test_mcp_tool_templates_merge_alongside_model_fields_without_conflict():
    es = Mock()
    es.indices.get.return_value = []
    install_templates(es, 0, [MODEL_MONITORING, MCP_TOOL_MONITORING])
    template_calls = [c for c in es.mock_calls if c[0] == "indices.put_index_template"]
    assert len(template_calls) == 2
    facts_fields, daily_fields = (
        c.kwargs["template"]["mappings"]["properties"] for c in template_calls
    )
    assert facts_fields["tool_name"]["type"] == "keyword"
    assert facts_fields["mcp_server_type"]["type"] == "keyword"
    assert facts_fields["model_type"]["type"] == "keyword"
    assert facts_fields["error_category"]["type"] == "keyword"
    assert daily_fields["mcp_server_id"]["type"] == "integer"
    assert daily_fields["has_agent_run"]["type"] == "boolean"
    assert daily_fields["duration_ms_sum"]["type"] == "long"

    conflicting = MonitoringKind(McpToolFact, accumulate_mcp_tool, fact_fields={"tool_name": "long"})
    with pytest.raises(ValueError, match="Incompatible monitoring mapping for tool_name"):
        install_templates(Mock(), 0, [MODEL_MONITORING, MCP_TOOL_MONITORING, conflicting])


def test_producer_drain_groups_mcp_tool_batches_separately_from_model():
    producer = Producer(Mock(), ZoneInfo("Asia/Shanghai"), MONITORING_KINDS)
    producer.emit({
        "tenant_id": "tenant", "fact_kind": "model", "fact_id": "attempt", "call_context_id": "request",
        "model_type": "llm", "started_at": "2026-10-31T17:00:00Z", "record_revision": 1, "outcome": "started",
    })
    producer.emit({
        "tenant_id": "tenant", "fact_kind": "mcp_tool", "fact_id": "invocation", "call_context_id": "run",
        "tool_name": "search_docs", "mcp_server_type": "unknown",
        "started_at": "2026-10-31T17:00:00Z", "record_revision": 1, "outcome": "started",
    })
    producer.emit({
        "tenant_id": "other", "fact_kind": "mcp_tool", "fact_id": "invocation", "call_context_id": "run",
        "tool_name": "search_docs", "mcp_server_type": "unknown",
        "started_at": "2026-10-31T17:00:00Z", "record_revision": 1, "outcome": "started",
    })

    batches = producer.drain()
    assert {kind for _, _, kind, _, _ in batches} == {"model", "mcp_tool"}
    grouped = {(tenant, kind): json.loads(payload) for _, tenant, kind, payload, _ in batches}
    assert [item["fact_kind"] for item in grouped[("tenant", "mcp_tool")]] == ["mcp_tool"]
    assert [item["fact_kind"] for item in grouped[("tenant", "model")]] == ["model"]


def _tool_service(states, documents=()):
    """Fake the Monitoring read surface used by read_mcp_tools."""
    captured = {}
    store = Mock()
    store.has_failed_batches.return_value = False
    store.coverage_starts.return_value = {}

    @contextmanager
    def fake_snapshot(tenant, kind, start, end):
        captured["snapshot_args"] = (tenant, kind, start, end)
        point = None
        if any(row["publish_id"] for row in states):
            def read_documents(constraints):
                captured["constraints"] = constraints
                return iter(documents)

            point = SimpleNamespace(documents=read_documents)
        yield states, point

    return SimpleNamespace(store=store, zone=ZoneInfo("UTC"), publication_snapshot=fake_snapshot), store, captured


def test_read_mcp_tools_scopes_the_query_to_the_requested_tenant_and_kind():
    from ops.monitoring.query import read_mcp_tools

    states = [{"tenant_id": "tenant-a", "statistic_date": date(2026, 11, 17), "source_revision": 2,
               "published_source_revision": 2, "publish_id": "pub-1", "source_snapshot_at": "t1"}]
    documents = [{"tenant_id": "tenant-a", "statistic_date": "2026-11-17", "mcp_server_id": 3,
                  "mcp_server_name": "docs", "mcp_server_type": "container", "tool_name": "search_docs",
                  "request_count": 5, "error_count": 0, "error_eligible_count": 5,
                  "duration_ms_sum": 100, "duration_ms_sample_count": 5}]
    service, store, captured = _tool_service(states, documents)
    store.coverage_starts.return_value = {"tenant-a": datetime(2026, 11, 1, tzinfo=ZoneInfo("UTC"))}

    rows, available, status = read_mcp_tools(service, tenant="tenant-a", start=date(2026, 11, 17),
                                             end=date(2026, 11, 17), groups=[1], server_id=3,
                                             server_type=None, tool_name=None)

    assert captured["snapshot_args"] == ("tenant-a", "mcp_tool", date(2026, 11, 17), date(2026, 11, 17))
    assert store.has_failed_batches.call_args.args[1] == "mcp_tool"
    assert store.coverage_starts.call_args.args[1] == "mcp_tool"
    constraints = captured["constraints"]["bool"]["filter"]
    assert {"term": {"fact_kind": "mcp_tool"}} in constraints
    selection = json.dumps(constraints[-1])
    assert "tenant-a" in selection and "tenant-b" not in selection and "pub-1" in selection
    assert rows == documents
    assert available == [date(2026, 11, 17)]
    assert status["coverage_state"] == "covered"


def test_read_mcp_tools_reports_uncovered_days_and_staleness():
    from ops.monitoring.query import read_mcp_tools

    states = [
        {"tenant_id": "tenant-a", "statistic_date": date(2026, 11, 17), "source_revision": 3,
         "published_source_revision": 2, "publish_id": "pub-1", "source_snapshot_at": None},
        {"tenant_id": "tenant-a", "statistic_date": date(2026, 11, 16), "source_revision": 1,
         "published_source_revision": None, "publish_id": None, "source_snapshot_at": None},
    ]
    service, store, _ = _tool_service(states)
    store.has_failed_batches.return_value = True

    rows, available, status = read_mcp_tools(service, tenant="tenant-a", start=date(2026, 11, 16),
                                             end=date(2026, 11, 17), groups=[], server_id=None,
                                             server_type=None, tool_name=None)

    assert rows == []
    assert available == [date(2026, 11, 17)]
    assert status == {"data_as_of": None, "coverage_state": "partial", "is_stale": True}


def test_read_mcp_tools_reports_uncovered_window_without_zeroing():
    from ops.monitoring.query import read_mcp_tools

    states = [{"tenant_id": "tenant-a", "statistic_date": date(2026, 11, 17), "source_revision": 1,
               "published_source_revision": None, "publish_id": None, "source_snapshot_at": None}]
    service, _, _ = _tool_service(states)

    rows, available, status = read_mcp_tools(service, tenant="tenant-a", start=date(2026, 11, 17),
                                             end=date(2026, 11, 17), groups=[], server_id=None,
                                             server_type=None, tool_name=None)

    assert rows == [] and available == []
    assert status["coverage_state"] == "uncovered"


def test_mcp_tool_rows_group_by_tenant_server_and_tool():
    from ops.monitoring.query import mcp_tool_rows

    def row(**overrides):
        return {"tenant_id": "tenant-a", "mcp_server_id": 3, "mcp_server_name": "docs",
                "mcp_server_type": "container", "tool_name": "search_docs", "statistic_date": "2026-11-17",
                "request_count": 1, "error_count": 0, "error_eligible_count": 1,
                "duration_ms_sum": 10, "duration_ms_sample_count": 1, **overrides}

    rows = [
        row(request_count=2, duration_ms_sum=50, duration_ms_sample_count=2),
        row(request_count=3, duration_ms_sum=40, duration_ms_sample_count=1),
        row(tenant_id="tenant-b", tool_name="translate"),
        {"tenant_id": "tenant-a", "mcp_server_name": "outer-apis", "mcp_server_type": "builtin",
         "tool_name": "search_docs", "statistic_date": "2026-11-17", "request_count": 4,
         "error_count": 0, "error_eligible_count": 4, "duration_ms_sum": 8, "duration_ms_sample_count": 4},
    ]
    items = mcp_tool_rows(rows)
    assert len(items) == 3
    by_tool = {(item["tenant_id"], item.get("mcp_server_id"), item["tool_name"]): item for item in items}
    docs = by_tool[("tenant-a", 3, "search_docs")]
    assert docs["metrics"]["request_count"] == 5
    assert docs["metrics"]["avg_duration_ms"] == 30
    assert by_tool[("tenant-b", 3, "translate")]["metrics"]["request_count"] == 1
    local = by_tool[("tenant-a", None, "search_docs")]
    assert local["mcp_server_type"] == "builtin"
    assert local["metrics"]["request_count"] == 4


def test_mcp_server_rows_aggregate_tools_per_server():
    from ops.monitoring.query import mcp_server_rows

    def doc(**overrides):
        return {"tenant_id": "tenant-a", "mcp_server_id": 3, "mcp_server_name": "docs",
                "mcp_server_type": "container", "tool_name": "search_docs", "statistic_date": "2026-11-17",
                "request_count": 2, "error_count": 0, "error_eligible_count": 2,
                "duration_ms_sum": 20, "duration_ms_sample_count": 2, **overrides}

    rows = [
        doc(request_count=2, duration_ms_sum=20, duration_ms_sample_count=2),
        doc(tool_name="translate", request_count=3, error_count=1, error_eligible_count=3,
            duration_ms_sum=30, duration_ms_sample_count=1),
        doc(mcp_server_id=4, mcp_server_name="outer-apis", mcp_server_type="builtin",
            tool_name="local_tool", request_count=1, duration_ms_sum=5, duration_ms_sample_count=1),
        doc(mcp_server_id=None, mcp_server_name="outer-apis", mcp_server_type="unknown",
            tool_name="local_tool", request_count=4, duration_ms_sum=8, duration_ms_sample_count=4),
    ]
    servers = mcp_server_rows(rows)
    assert len(servers) == 3
    by_server = {(s["tenant_id"], s.get("mcp_server_id")): s for s in servers}
    docs = by_server[("tenant-a", 3)]
    assert docs["mcp_server_name"] == "docs"
    assert docs["mcp_server_type"] == "container"
    assert docs["active_tools"] == 2
    assert docs["metrics"]["request_count"] == 5
    assert docs["metrics"]["error_count"] == 1
    assert docs["metrics"]["avg_duration_ms"] == 50 / 3
    local_db = by_server[("tenant-a", 4)]
    assert local_db["active_tools"] == 1
    assert local_db["mcp_server_type"] == "builtin"
    unattributed = by_server[("tenant-a", None)]
    assert unattributed["active_tools"] == 1
    assert unattributed["metrics"]["request_count"] == 4
