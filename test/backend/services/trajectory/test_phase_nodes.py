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


@pytest.mark.parametrize("display,expected", [
    (" 通用助手 ", "通用助手"), (None, "general_assistant"),
    ("   ", "general_assistant"), (7, "general_assistant"),
])
def test_agent_node_prefers_captured_display_name(display, expected):
    nodes, _, _ = build_nodes(request(
        span("root", **{"agent.name": "general_assistant", "agent.display_name": display}),
        span("tool", "root", "TOOL", **{"tool.name": "python_interpreter", "agent.display_name": "工具所属智能体"}),
    ), conversation_id="123")
    assert nodes[0]["name"] == expected
    assert nodes[1]["name"] == "python_interpreter"


@pytest.mark.parametrize("display,expected", [(None, "通用助手"), ("  ", "通用助手"), ("记忆助手", "记忆助手")])
def test_memory_name_uses_own_display_or_unique_captured_agent(display, expected):
    memory = span("memory", "root", "CHAIN", **{
        "nexent.node.kind": "phase", "agent.id": "7", "agent.name": "general_assistant",
        "agent.display_name": display,
    })
    memory["name"] = "memory.prepare"
    nodes, _, _ = build_nodes(request(memory, span("root", **{
        "agent.id": "7", "agent.name": "general_assistant", "agent.display_name": "通用助手",
    })), conversation_id="123")
    phase = next(node for node in nodes if node["id"] == "memory")
    assert phase["attributes"]["agent.display_name"] == expected
    assert phase["attributes"]["agent.name"] == "general_assistant"


def test_legacy_memory_does_not_choose_between_conflicting_captured_names():
    memory = span("memory", "root", "CHAIN", **{
        "nexent.node.kind": "phase", "agent.id": "7", "agent.name": "general_assistant",
    })
    memory["name"] = "memory.prepare"
    nodes, _, _ = build_nodes(request(span("root"), memory,
        span("one", "root", **{"agent.id": "7", "agent.display_name": "名称一"}),
        span("two", "root", **{"agent.id": "7", "agent.display_name": "名称二"}),
    ), conversation_id="123")
    phase = next(node for node in nodes if node["id"] == "memory")
    assert "agent.display_name" not in phase["attributes"]
    assert phase["attributes"]["agent.name"] == "general_assistant"


def test_legacy_memory_can_use_the_captured_subagent_node_name():
    memory = span("memory", "root", "CHAIN", **{
        "nexent.node.kind": "phase", "agent.id": "7", "agent.name": "general_agent",
    })
    memory["name"] = "memory.prepare"
    nodes, _, _ = build_nodes(request(span("root"), memory,
        span("child", "root", **{"agent.id": "7", "agent.name": "通用子智能体"}),
    ), conversation_id="123")
    phase = next(node for node in nodes if node["id"] == "memory")
    assert phase["attributes"]["agent.display_name"] == "通用子智能体"


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
