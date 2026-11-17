# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Unit coverage for the Agent fact contract and its writer registration."""

import json
from datetime import date
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from nexent.monitor.facts import emit_fact, get_fact_sink, set_fact_sink
from ops.monitoring.agent import AgentFact
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


def test_fact_only_agent_does_not_publish():
    store = Mock()
    es = Mock()
    service = Monitoring(store, es, ZoneInfo("UTC"), MONITORING_KINDS)
    service.publish("t1", "agent")
    assert store.mock_calls == es.mock_calls == []
    assert MONITORING_KINDS["model"].aggregate is accumulate_model
