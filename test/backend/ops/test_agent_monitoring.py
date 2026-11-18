# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Unit coverage for the Agent fact contract and its writer registration."""

import json
from datetime import date
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from nexent.monitor.facts import emit_fact, get_fact_sink, set_fact_sink
from ops.monitoring.agent import AgentFact, accumulate_agent
from ops.monitoring.contracts import MonitoringKind
from ops.monitoring.model import accumulate_model
from ops.monitoring.runtime import MONITORING_KINDS, Producer
from ops.monitoring.service import Monitoring, _apply_revision


@pytest.fixture
def started():
    return {
        "tenant_id": "t1", "fact_kind": "agent", "fact_id": "run", "call_context_id": "request",
        "root_run_id": "run", "agent_run_id": "run", "agent_id": 21, "agent_version_no": 3,
        "is_root": True, "started_at": "2026-10-31T23:59:59.800Z",
        "record_revision": 1, "outcome": "started",
    }


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"fact_id": "bad"}, "Agent fact ID must match"),
        ({"root_run_id": "bad"}, "Invalid root Agent identity"),
        ({"parent_run_id": "parent"}, "Invalid root Agent identity"),
        ({"is_root": False, "root_run_id": "root"}, "Invalid child Agent identity"),
        ({"is_root": False, "root_run_id": "root", "parent_run_id": "run"}, "Invalid child Agent identity"),
        ({"agent_id": 0}, "greater than 0"),
    ],
)
def test_agent_fact_rejects_invalid_identity(started, overrides, message):
    with pytest.raises(ValidationError, match=message):
        AgentFact.model_validate({**started, **overrides})


def test_agent_fact_accepts_child_with_distinct_identity(started):
    fact = AgentFact.model_validate(
        dict(started, is_root=False, root_run_id="root", parent_run_id="parent")
    )
    assert (fact.agent_run_id, fact.parent_run_id, fact.root_run_id) == ("run", "parent", "root")


def test_registered_agent_fact_keeps_start_partition_on_finish_and_replay(started):
    producer = Producer(Mock(), ZoneInfo("UTC"), MONITORING_KINDS)
    finished = dict(
        started, record_revision=2, outcome="succeeded", ended_at="2026-11-01T00:00:00.150Z", duration_ms=350
    )
    previous_sink = get_fact_sink()
    set_fact_sink(producer.emit)
    try:
        for event in (started, finished, finished):
            emit_fact(event)
    finally:
        set_fact_sink(previous_sink)

    (_, tenant, kind, payload, days), = producer.drain()
    assert (tenant, kind, days) == ("t1", "agent", [date(2026, 10, 31)])
    documents = [AgentFact.model_validate(event).document(producer.zone) for event in json.loads(payload)]
    first, terminal, replay = documents
    assert first["partition_anchor_at"] == terminal["partition_anchor_at"] == "2026-10-31T23:59:59.800000+00:00"
    assert terminal["duration_ms"] == 350 and terminal["outcome"] == "succeeded"
    assert _apply_revision(first, terminal)
    assert not _apply_revision(terminal, replay)
    assert not _apply_revision(terminal, first)


def test_kind_without_a_reducer_does_not_publish():
    store = Mock()
    es = Mock()
    service = Monitoring(store, es, ZoneInfo("UTC"), {"agent": MonitoringKind(AgentFact)})
    service.publish("t1", "agent")
    assert store.mock_calls == es.mock_calls == []
    assert MONITORING_KINDS["model"].aggregate is accumulate_model


def _document(started, run_id, **overrides):
    return AgentFact.model_validate({
        **started, "fact_id": run_id, "agent_run_id": run_id, "root_run_id": run_id, **overrides,
    }).document(ZoneInfo("UTC"))


@pytest.mark.parametrize("outcome", ["succeeded", "failed", "cancelled", "timed_out", "unknown"])
def test_daily_duration_counts_each_valid_ended_sample(started, outcome):
    duration = 2**53 + 9
    end = "2026-11-01T00:00:00.150Z"
    documents = [
        _document(started, "in-progress"),
        _document(started, "ended", outcome=outcome, ended_at=end, duration_ms=duration),
        _document(started, "zero", outcome=outcome, ended_at=end, duration_ms=0),
        _document(started, "unmeasured", outcome=outcome, ended_at=end),
        _document(started, "unconfirmed-end", outcome=outcome, duration_ms=30),
    ]
    (_, row), = accumulate_agent(documents)
    assert row["statistic_date"] == "2026-10-31"
    assert row["execution_count"] == 5
    assert row["duration_sum_ms"] == duration
    assert row["duration_sample_count"] == 2


def test_daily_dimensions_preserve_tenant_day_group_and_agent_scope(started):
    documents = [
        _document(started, "first", initiator_group_ids=[2, 1, 2]),
        _document(started, "new-version", agent_version_no=4, initiator_group_ids=[1, 2]),
        _document(started, "other-group", initiator_group_ids=[2, 3]),
        _document(started, "no-group", initiator_group_ids=[]),
        _document(started, "unknown-group"),
        _document(started, "next-day", started_at="2026-11-01T00:00:00Z", initiator_group_ids=[1, 2]),
        _document(started, "other-agent", agent_id=22, initiator_group_ids=[1, 2]),
        _document(started, "other-tenant", tenant_id="t2", initiator_group_ids=[1, 2]),
    ]
    aggregate = MONITORING_KINDS["agent"].aggregate
    rows = {
        (row["tenant_id"], row["statistic_date"], row["group_snapshot_state"],
         tuple(row["initiator_group_ids"]), row["agent_id"]): row["execution_count"]
        for _, row in aggregate(documents)
    }
    assert rows == {
        ("t1", "2026-10-31", "known", (1, 2), 21): 2,
        ("t1", "2026-10-31", "known", (2, 3), 21): 1,
        ("t1", "2026-10-31", "known", (), 21): 1,
        ("t1", "2026-10-31", "unknown", (), 21): 1,
        ("t1", "2026-11-01", "known", (1, 2), 21): 1,
        ("t1", "2026-10-31", "known", (1, 2), 22): 1,
        ("t2", "2026-10-31", "known", (1, 2), 21): 1,
    }
