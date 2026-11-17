# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Code-tree presentation preserves source data and precomputed subtree metrics."""

import pytest
from ops.services.trajectory.nodes import build_nodes

from test.backend.services.trajectory.test_nodes import request, span


def code_node(identity, parent, *, kind="phase", name="code.execute", **attrs):
    value = span(
        identity,
        parent,
        "CHAIN" if kind == "phase" else "TOOL",
        **{
            **(
                {"nexent.node.kind": "phase"}
                if kind == "phase"
                else {"tool.name": name}
            ),
            "input.value": f"{identity} input",
            "output.value": f"{identity} output",
            **attrs,
        },
    )
    value["name"] = name
    return value


def python_node(identity="python", parent="root", **attrs):
    return code_node(identity, parent, kind="tool", name="python_interpreter", **attrs)


def indexed(*values):
    nodes, root, coverage = build_nodes(request(*values), conversation_id="123")
    assert (
        coverage["complete"]
        and root == values[0]["attributes"][0]["value"]["stringValue"]
    )
    return {node["id"]: node for node in nodes}


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_code_groups_keep_sandbox_and_lift_nested_named_tool(native, reverse):
    values = [
        span("root"),
        python_node(),
        code_node("init", "python", name="agent.sandbox.initialize"),
        code_node("warm", "init", name="agent.sandbox.warmup"),
        code_node("code", "python"),
        code_node("parallel", "code", kind="tool", name="parallel_executor"),
        span("agent", "parallel"),
        span(
            "model",
            "agent",
            "LLM",
            **{
                "llm.model_name": "model",
                "llm.token_count.prompt": "2",
                "llm.token_count.completion": "3",
            },
        ),
        python_node("inner", "agent"),
        code_node("inner-code", "inner"),
        code_node("read", "inner-code", kind="tool", name="read_skill_md"),
    ]
    if native:
        for value in values:
            parent = next(
                (
                    a["value"]["stringValue"]
                    for a in value["attributes"]
                    if a["key"] == "nexent.parent_record_id"
                ),
                None,
            )
            value["attributes"] = [
                a for a in value["attributes"] if a["key"] != "nexent.parent_record_id"
            ]
            if parent:
                value["parentSpanId"] = parent.ljust(16, "0")
    root = values[0]
    nodes = indexed(root, *(list(reversed(values[1:])) if reverse else values[1:]))
    assert set(nodes) == {
        "root",
        "python",
        "init",
        "parallel",
        "agent",
        "model",
        "read",
    }
    assert nodes["init"]["parent_id"] == nodes["parallel"]["parent_id"] == "python"
    assert nodes["agent"]["parent_id"] == "parallel"
    assert nodes["read"]["parent_id"] == nodes["model"]["parent_id"] == "agent"
    assert (
        nodes["python"]["direct_child_count"]
        == nodes["agent"]["direct_child_count"]
        == 2
    )
    assert nodes["read"]["name"] == "read_skill_md"
    assert nodes["read"]["_bodies"] == {"input": "read input", "output": "read output"}
    assert nodes["read"]["source"]["span_id"] == "read".ljust(16, "0")
    assert nodes["read"]["duration_ms"] == 20
    assert nodes["root"]["model_call_count"] == 1
    assert nodes["root"]["tool_call_count"] == 4
    assert nodes["root"]["usage"]["total"] == 5


def test_generated_python_keeps_code_phase_source_time_and_body():
    nodes = indexed(
        span("root"),
        python_node(),
        code_node("code", "python", **{"nexent.duration_ms": "125"}),
    )
    assert set(nodes) == {"root", "code"}
    assert nodes["code"]["parent_id"] == "root"
    assert nodes["code"]["kind"] == "phase" and nodes["code"]["name"] == "code.execute"
    assert nodes["code"]["duration_ms"] == 125
    assert nodes["code"]["_bodies"]["input"] == "code input"
    assert nodes["code"]["source"]["span_id"] == "code".ljust(16, "0")
    assert nodes["root"]["direct_child_count"] == nodes["root"]["tool_call_count"] == 1


def test_sandbox_group_keeps_generated_python_as_sibling():
    nodes = indexed(
        span("root"),
        python_node(),
        code_node("init", "python", name="agent.sandbox.initialize"),
        code_node("code", "python", **{"nexent.duration_ms": "125"}),
    )
    assert set(nodes) == {"root", "python", "init", "code"}
    assert nodes["python"]["direct_child_count"] == 2
    assert nodes["code"]["parent_id"] == nodes["init"]["parent_id"] == "python"
    assert nodes["code"]["duration_ms"] == 125 and nodes["python"]["duration_ms"] == 20


def test_multiple_named_tools_keep_independent_sources_and_parents():
    nodes = indexed(
        span("root"),
        python_node(),
        code_node("code", "python"),
        code_node("one", "code", kind="tool", name="read_skill_md"),
        code_node("two", "code", kind="tool", name="search"),
    )
    assert set(nodes) == {"root", "one", "two"}
    assert nodes["root"]["direct_child_count"] == 2
    assert nodes["root"]["tool_call_count"] == 3
    for identity in ("one", "two"):
        assert nodes[identity]["parent_id"] == "root"
        assert nodes[identity]["_bodies"]["output"] == f"{identity} output"


@pytest.mark.parametrize("status", ["failed", "cancelled", "interrupted"])
@pytest.mark.parametrize("target", ["python", "code", "read"])
def test_unsuccessful_code_subtree_keeps_diagnostic_wrappers(status, target):
    values = [
        span("root"),
        python_node(),
        code_node("code", "python"),
        code_node("read", "code", kind="tool", name="read_skill_md"),
    ]
    value = next(
        item
        for item in values
        if any(
            a["key"] == "nexent.record_id" and a["value"]["stringValue"] == target
            for a in item["attributes"]
        )
    )
    value["attributes"].append(
        {"key": "nexent.business_status", "value": {"stringValue": status}}
    )
    nodes = indexed(*values)
    assert target in nodes
    assert nodes[target]["status"] == status
    assert nodes[target]["_bodies"]["output"] == f"{target} output"
    if target in {"code", "read"}:
        assert nodes["code"]["parent_id"] == "python"
        assert nodes["python"]["parent_id"] == "root"


def test_execution_root_and_legacy_unrelated_phases_remain_available():
    nodes = indexed(
        python_node(parent=None),
        code_node("code", "python"),
        code_node("tool", "code", kind="tool", name="read_skill_md"),
    )
    assert set(nodes) == {"python", "tool"} and nodes["tool"]["parent_id"] == "python"
    nodes = indexed(
        span("root"), python_node(), code_node("other", "python", name="custom.prepare")
    )
    assert set(nodes) == {"root", "python", "other"}
    assert nodes["other"]["parent_id"] == "python"


def test_other_tools_do_not_lose_their_code_execution_phase():
    nodes = indexed(
        span("root"), code_node("executor", "root", kind="tool", name="custom_executor"),
        code_node("code", "executor"),
        code_node("read", "code", kind="tool", name="read_skill_md"),
    )
    assert set(nodes) == {"root", "executor", "code", "read"}
    assert nodes["read"]["parent_id"] == "code"


def test_legacy_python_without_phase_or_children_keeps_its_source():
    nodes = indexed(span("root"), python_node())
    assert set(nodes) == {"root", "python"}
    assert nodes["python"]["parent_id"] == "root"
    assert nodes["python"]["_bodies"]["input"] == "python input"
