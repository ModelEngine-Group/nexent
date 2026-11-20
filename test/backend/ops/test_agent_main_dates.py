# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Complete main start timestamps do not move execution counts or ES partitions."""

from datetime import date, datetime, timezone
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from ops.monitoring.agent import AGENT_MONITORING, AgentFact, accumulate_agent
from ops.monitoring.runtime import MONITORING_KINDS, Producer


def event(**values):
    return dict(tenant_id="tenant", fact_kind="agent", fact_id="root", call_context_id="root",
                agent_run_id="root", root_run_id="root", agent_id=21, is_root=True,
                record_revision=1, outcome="started", started_at="2026-10-31T23:59:59Z", **values)


@pytest.mark.parametrize("child", [False, True])
def test_main_full_start_preserves_actual_execution_day_partition_and_batch_dates(child):
    payload = event(execution_started_at="2026-11-01T00:00:00Z")
    if child:
        payload.update(fact_id="child", agent_run_id="child", call_context_id="child",
                       parent_run_id="root", is_root=False)
    fact = AgentFact.model_validate(payload)
    assert fact.partition_anchor() == datetime(2026, 11, 1, tzinfo=timezone.utc)
    assert fact.statistic_day(ZoneInfo("UTC")) == date(2026, 11, 1)
    document = fact.document(ZoneInfo("UTC"))
    assert document["started_at"].startswith("2026-10-31")
    assert document["partition_anchor_at"].startswith("2026-11-01")
    assert document["statistic_date"] == "2026-11-01"
    producer = Producer(Mock(), ZoneInfo("UTC"), MONITORING_KINDS)
    producer.emit(payload)
    batch, = producer.drain()
    assert batch[-1] == [date(2026, 11, 1)]
    (_, row), = accumulate_agent([document])
    assert row["execution_count"] == 1 and row["statistic_date"] == "2026-11-01"
    assert AGENT_MONITORING.fact_fields["execution_started_at"] == "date"


def test_legacy_main_and_unchanged_child_keep_existing_date_rule():
    legacy = AgentFact.model_validate(event())
    child = AgentFact.model_validate({**event(), "fact_id": "child", "agent_run_id": "child",
                                      "is_root": False, "parent_run_id": "root"})
    for fact in (legacy, child):
        assert fact.partition_anchor().date() == fact.statistic_day(ZoneInfo("UTC")) == date(2026, 10, 31)
