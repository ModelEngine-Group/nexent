# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Per-agent memory preparation keeps detailed facts in one exported phase."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from nexent.monitor.phase_capture import (
    capture_preparation,
    emit_preparation,
    trace_phase,
)

from .test_phase_capture import local_spans as local_spans


def memory_steps(agent_id, name, *, error=None):
    attributes = {"agent.id": str(agent_id), "agent.name": name}
    for service in ("memory", "context"):
        with trace_phase(
            "memory.initialize", input_value={"service": service}, attributes=attributes
        ) as phase:
            phase.set_output({"ready": True})
    with trace_phase(
        "memory.external_search", input_value={"query": "问题"}, attributes=attributes
    ) as phase:
        phase.set_output([])
    with trace_phase("memory.load_context", attributes=attributes) as phase:
        phase.set_output({"preferences": [name]})
    try:
        with trace_phase(
            "memory.presearch",
            input_value={"query": "问题", "api_key": "private"},
            attributes=attributes,
        ) as phase:
            with trace_phase(
                "memory.retrieve", attributes={"agent.id": str(agent_id)}
            ) as nested:
                if error:
                    raise error("private failure message")
                nested.set_output({"matches": [name]})
            phase.set_output({"matches": [name]})
    except (RuntimeError, asyncio.CancelledError):
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,status",
    [
        (None, "success"),
        (RuntimeError, "failed"),
        (asyncio.CancelledError, "cancelled"),
    ],
)
async def test_memory_preparation_exports_one_node_per_agent(
    local_spans, error, status
):
    manager, exporter = local_spans

    @capture_preparation
    async def prepare():
        memory_steps(2, "子智能体", error=error)
        memory_steps(1, "主智能体")
        return SimpleNamespace()

    info = await prepare()
    original = list(info.preparation_trace)
    assert len(original) == 13
    with manager.start_agent_run():
        emit_preparation(info)
        emit_preparation(info)
    spans = exporter.get_finished_spans()
    grouped = [s for s in spans if s.name == "memory.prepare"]
    assert len(grouped) == 2
    assert not any(
        s.name in {"memory.initialize", "memory.retrieve", "memory.presearch"}
        for s in spans
    )
    parent = next(s for s in spans if s.name == "agent.prepare")
    for node in grouped:
        assert node.parent.span_id == parent.context.span_id
        source = [
            r
            for r in original
            if r["attributes"].get("agent.id") == node.attributes["agent.id"]
        ]
        assert node.start_time == min(r["started_at_ns"] for r in source)
        assert node.end_time == max(r["finished_at_ns"] for r in source)
        assert node.attributes["nexent.node.kind"] == "phase"
        output = json.loads(node.attributes["output.value"])
        assert len(output["steps"]) == 6
        assert [step["name"] for step in output["steps"]].count(
            "memory.initialize"
        ) == 2
        assert output["steps"][-1]["parent_step"] == 4
        assert output["steps"][0]["input"] == {"service": "memory"}
        assert output["steps"][1]["input"] == {"service": "context"}
        expected = status if node.attributes["agent.id"] == "2" else "success"
        assert node.attributes["nexent.business_status"] == expected
        assert output["steps"][-1]["status"] == expected
        assert "private" not in str(node.attributes)
        assert json.loads(node.attributes["input.value"])["query"] == "问题"
        if error and node.attributes["agent.id"] == "2":
            assert output["steps"][-1]["error_type"] == error.__name__
    assert info.preparation_trace == []


def record(name, parent, agent=None, *, start=0, duration=100, status="success"):
    attributes = {"nexent.node.kind": "phase", "nexent.duration_ms": duration}
    if agent:
        attributes.update({"agent.id": agent, "agent.name": agent})
    return {
        "name": name,
        "parent": parent,
        "started_at_ns": 1000000000 + int(start * 1000000000),
        "finished_at_ns": 1000000000 + int((start + duration / 1000) * 1000000000),
        "started_monotonic": 100 + start,
        "attributes": attributes,
        "status": status,
    }


def test_group_duration_uses_range_and_preserves_nonmemory_parents():
    from nexent.monitor.preparation_groups import group_memory_preparation

    records = [
        record("agent.prepare", None),
        record("memory.initialize", 0, "1", start=0, duration=100),
        record("memory.presearch", 0, "1", start=0.1, duration=200),
        record("memory.retrieve", 2, "1", start=0.12, duration=100),
        record("other.phase", 2, start=0.13, duration=10),
        record("agent.sandbox.initialize", 0, start=0.3),
    ]
    result = group_memory_preparation(records)
    assert [r["name"] for r in result] == [
        "agent.prepare",
        "memory.prepare",
        "other.phase",
        "agent.sandbox.initialize",
    ]
    assert result[1]["attributes"]["nexent.duration_ms"] == pytest.approx(300)
    assert result[2]["parent"] == 1 and result[3]["parent"] == 0
    assert records[1]["name"] == "memory.initialize"


@pytest.mark.parametrize(
    "separator", ["memory.load_context", "agent.sandbox.initialize"]
)
def test_distinct_agents_and_separate_batches_are_not_merged(separator):
    from nexent.monitor.preparation_groups import group_memory_preparation

    records = [record("agent.prepare", None), record("memory.initialize", 0, "1")]
    records += [record(separator, 0, "2"), record("memory.presearch", 0, "1")]
    result = group_memory_preparation(records)
    assert len(result) == 4
    assert [r["attributes"].get("agent.id") for r in result[1:]] == ["1", "2", "1"]


def test_unidentified_phases_and_missing_duration_remain_explicit():
    from nexent.monitor.preparation_groups import group_memory_preparation

    unknown = record("memory.presearch", 0)
    missing = record("memory.initialize", 0, "1")
    missing["attributes"].pop("nexent.duration_ms")
    missing["attributes"]["nexent.trajectory.gap"] = True
    missing["attributes"]["nexent.availability.output"] = "serialization_failed"
    result = group_memory_preparation([record("agent.prepare", None), unknown, missing])
    assert result[1] == unknown
    assert "nexent.duration_ms" not in result[2]["attributes"]
    assert result[2]["attributes"]["nexent.availability.duration_ms"] == "not_captured"
    assert result[2]["attributes"]["nexent.trajectory.gap"] is True
    assert "nexent.availability.output" not in result[2]["attributes"]
    steps = json.loads(result[2]["attributes"]["output.value"])["steps"]
    assert steps[0]["availability"]["output"] == "serialization_failed"


def test_grouping_failure_preserves_original_facts(local_spans, monkeypatch):
    from nexent.monitor import phase_capture

    manager, exporter = local_spans
    monkeypatch.setattr(
        phase_capture, "group_memory_preparation", lambda _records: 1 / 0
    )
    info = SimpleNamespace(preparation_trace=[record("memory.initialize", None, "1")])
    with manager.start_agent_run() as root:
        emit_preparation(info)
        assert root.attributes["nexent.trajectory.gap"] is True
    assert any(s.name == "memory.initialize" for s in exporter.get_finished_spans())
