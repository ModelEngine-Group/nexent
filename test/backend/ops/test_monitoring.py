# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Unit coverage for shared keys, collection and model statistics."""

import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Literal
from unittest.mock import Mock, call
from zoneinfo import ZoneInfo

import pytest

from nexent.monitor.facts import emit_fact, set_fact_sink
from nexent.monitor.model_fact import AttemptObservation
from nexent.monitor.monitoring import AgentRunMetadata, _MonitoredChatCompletions, agent_monitoring_context
from nexent.monitor.skill_usage import observe_skill_usage
from ops.monitoring.contracts import Fact, MonitoringKind, day_id
from ops.monitoring.model import MODEL_MONITORING, ModelFact, accumulate_model, summarize
from infrastructure.monitoring.runtime import Producer
from ops.monitoring.search import delete_documents, install_templates
from ops.monitoring.service import CLEANUP_INTERVAL_SECONDS, Monitoring, _apply_revision, _merge_skill_usage


def fact(**overrides):
    return ModelFact.model_validate({
        "tenant_id": "tenant", "fact_id": "attempt", "call_context_id": "request",
        "model_id": 7, "model_type": "llm", "started_at": "2026-10-31T17:00:00Z",
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

    producer = Producer(Mock(), ZoneInfo("Asia/Shanghai"), {"skill": SkillFact})
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


def test_skill_usage_reuses_agent_run_start_time():
    events = []
    set_fact_sink(events.append)
    try:
        with agent_monitoring_context(AgentRunMetadata(
                tenant_id="tenant", agent_id=7, monitoring_run_id="run",
                monitoring_root_run_id="run",
                monitoring_started_at=datetime(2026, 11, 23, 1, 2, 3, tzinfo=timezone.utc))):
            observe_skill_usage(17, "writer", "guide_read")
    finally:
        set_fact_sink(None)
    assert events[0]["started_at"] == "2026-11-23T01:02:03+00:00"
    assert events[0]["triggered_at"] != events[0]["started_at"]


def test_skill_usage_server_merge_keeps_earliest_trigger():
    later = {
        "tenant_id": "tenant", "fact_kind": "skill", "fact_id": "skill-use",
        "call_context_id": "run", "started_at": "2026-11-23T01:00:00Z",
        "triggered_at": "2026-11-23T01:05:00Z", "trigger_kind": "script_started",
        "record_revision": 1,
    }
    earlier = {**later, "triggered_at": "2026-11-23T01:04:00Z", "trigger_kind": "guide_read"}
    merged = _merge_skill_usage(later, earlier)
    assert merged["triggered_at"] == earlier["triggered_at"]
    assert merged["trigger_kind"] == "guide_read"
    assert merged["record_revision"] == 2
    assert _merge_skill_usage(merged, later) is None


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
