# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Only explicit lifecycle phases survive technical-span filtering."""

import pytest

from ops.services.trajectory.nodes import build_nodes
from test.backend.services.trajectory.test_nodes import request, span


def test_lifecycle_phase_keeps_parent_and_does_not_inflate_tool_or_model_counts():
    phase = span(
        "prepare",
        "root",
        "CHAIN",
        **{
            "nexent.node.kind": "phase",
            "input.value": "input",
            "output.value": "output",
        },
    )
    nodes, _, coverage = build_nodes(
        request(
            span("root"),
            phase,
            span("noise", "prepare", "CHAIN"),
            span("memory", "prepare", "CHAIN", **{"nexent.node.kind": "phase"}),
            span(
                "model",
                "noise",
                "LLM",
                **{"llm.token_count.prompt": "2", "llm.token_count.completion": "3"},
            ),
        ),
        conversation_id="123",
    )
    indexed = {n["id"]: n for n in nodes}
    assert "prepare" in indexed and "memory" in indexed and "noise" not in indexed
    assert (
        indexed["prepare"]["kind"] == "phase"
        and indexed["prepare"]["parent_id"] == "root"
    )
    assert indexed["memory"]["parent_id"] == indexed["model"]["parent_id"] == "prepare"
    assert (
        indexed["prepare"]["duration_ms"] == 20 and indexed["prepare"]["usage"] is None
    )
    assert (
        indexed["root"]["model_call_count"] == 1
        and indexed["root"]["tool_call_count"] == 0
    )
    assert indexed["root"]["usage"]["total"] == 5 and coverage["complete"]


def test_existing_sandbox_warmup_is_visible_but_unknown_chain_is_hidden():
    warmup = span("warmup", "root", "CHAIN")
    warmup["name"] = "agent.sandbox.warmup"
    nodes, _, _ = build_nodes(
        request(span("root"), warmup, span("noise", "root", "CHAIN")),
        conversation_id="123",
    )
    assert [(n["id"], n["kind"]) for n in nodes] == [
        ("root", "agent"),
        ("warmup", "phase"),
    ]


def test_grouped_memory_phase_exposes_agent_name_without_changing_node_kind():
    phase = span(
        "memory", "root", "CHAIN",
        **{"nexent.node.kind": "phase", "agent.name": "子智能体", "agent.id": "2"},
    )
    phase["name"] = "memory.prepare"
    nodes, _, _ = build_nodes(request(span("root"), phase), conversation_id="123")
    memory = next(node for node in nodes if node["id"] == "memory")
    assert memory["attributes"]["agent.name"] == "子智能体"
    assert memory["kind"] == "phase" and memory["agent_version_no"] is None
    assert memory["parent_id"] == "root" and memory["usage"] is None


@pytest.mark.parametrize("native", [False, True])
def test_sandbox_initialization_collapses_internal_phases_and_keeps_code(native):
    def phase(identity, parent, name):
        value = span(identity, parent, "CHAIN", **{"nexent.node.kind": "phase"})
        value["name"] = name
        if native:
            value["attributes"] = [a for a in value["attributes"] if a["key"] != "nexent.parent_record_id"]
            value["parentSpanId"] = parent.ljust(16, "0")
        return value

    nodes, _, coverage = build_nodes(request(
        span("root"), span("python", "root", "TOOL"),
        phase("init", "python", "agent.sandbox.initialize"),
        phase("warm", "init", "agent.sandbox.warmup"),
        phase("workspace", "init", "agent.sandbox.workspace"),
        phase("code", "python", "code.execute"),
        span("tool", "code", "TOOL"),
    ), conversation_id="123")
    indexed = {node["id"]: node for node in nodes}
    assert "warm" not in indexed and "workspace" not in indexed
    assert indexed["init"]["parent_id"] == indexed["code"]["parent_id"] == "python"
    assert indexed["init"]["direct_child_count"] == 0
    assert indexed["python"]["direct_child_count"] == 2
    assert indexed["init"]["duration_ms"] == 20 and indexed["code"]["duration_ms"] == 20
    assert indexed["root"]["tool_call_count"] == 2 and coverage["complete"]
