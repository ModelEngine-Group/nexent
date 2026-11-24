# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Model observations inherit actual main and child execution identity without telemetry."""

from unittest.mock import Mock

from nexent.core.agents.resources.subagents import SubAgentToolWrapper
from nexent.monitor import AgentRunMetadata, MonitoringConfig, agent_monitoring_context, get_monitoring_manager
from nexent.monitor.facts import get_fact_sink, set_fact_sink
from nexent.monitor.model_fact import AttemptObservation


def test_model_attempts_follow_main_and_independent_child_invocations(monkeypatch):
    events = []
    manager = get_monitoring_manager()
    monkeypatch.setattr(manager, "_config", MonitoringConfig(enable_telemetry=False))
    previous = get_fact_sink()
    set_fact_sink(events.append)

    def request(task=""):
        observation = AttemptObservation.for_client("tenant", 7, "llm")
        observation.dispatch()
        observation.record_provider_counts({"input_tokens": 0, "total_tokens": 4})
        observation.complete(None)
        observation.finish()
        observation.finish()

    child = SubAgentToolWrapper(request, Mock(), agent_id=22)
    metadata = AgentRunMetadata(tenant_id="tenant", agent_id=21, monitoring_run_id="root",
                                monitoring_root_run_id="root", monitoring_group_ids=(12, 13))
    try:
        with agent_monitoring_context(metadata):
            request()
            child(task="one")
            child(task="two")
            request()
    finally:
        set_fact_sink(previous)
    starts = events[::2]
    assert len(events) == 8 and len({event["fact_id"] for event in starts}) == 4
    assert [event["agent_id"] for event in starts] == [21, 22, 22, 21]
    assert starts[0]["agent_run_id"] == starts[-1]["agent_run_id"] == "root"
    assert len({event["agent_run_id"] for event in starts}) == 3
    for start, end in zip(events[::2], events[1::2]):
        assert start["fact_id"] == end["fact_id"] and start["agent_run_id"] == end["agent_run_id"]
        assert start["root_run_id"] == "root" and start["initiator_group_ids"] == (12, 13)
        assert end["input_tokens"] == 0 and end["total_tokens"] == 4 and "output_tokens" not in end
