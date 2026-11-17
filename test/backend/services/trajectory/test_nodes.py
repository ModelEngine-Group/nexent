# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Hierarchy and complete-subtree metric arithmetic, isolated from file I/O."""

import pytest
from infrastructure.observability.trajectory_io import TrajectoryCorrupt
from ops.services.trajectory.nodes import build_nodes

TRACE = "a" * 32


def span(identity, parent=None, kind="AGENT", **attrs):
    attrs = {"nexent.record_id": identity, "openinference.span.kind": kind, **attrs}
    if parent:
        attrs["nexent.parent_record_id"] = parent
    return {
        "traceId": TRACE,
        "spanId": identity.ljust(16, "0"),
        "name": identity,
        "startTimeUnixNano": "1000000000",
        "endTimeUnixNano": "1020000000",
        "attributes": [
            {"key": k, "value": {"stringValue": v}} for k, v in attrs.items()
        ],
    }


def request(*spans):
    return [{"resourceSpans": [{"scopeSpans": [{"spans": list(spans)}]}]}]


def test_nested_parallel_metrics_deduplicate_exports():
    model = span(
        "m",
        "sub",
        "LLM",
        **{
            "llm.model_name": "model-a",
            "llm.token_count.prompt": "4",
            "llm.token_count.completion": "2",
            "llm.ttft_ms": "0",
        },
    )
    nodes, root, coverage = build_nodes(
        request(
            span("root"),
            span("sub", "root"),
            model,
            model,
            span("tool", "root", "TOOL"),
        ),
        conversation_id="123",
    )
    nodes = {n["id"]: n for n in nodes}
    assert root == "root" and coverage["complete"]
    assert nodes[root]["display_trace_id"] == "123"
    assert nodes["m"]["display_trace_id"] == "m"
    assert nodes[root]["usage"]["total"] == 6
    assert nodes[root]["model_call_count"] == 1
    assert nodes[root]["tool_call_count"] == 1
    assert nodes[root]["direct_child_count"] == 2
    assert nodes["sub"]["usage"]["total"] == 6
    assert nodes["m"]["duration_ms"] == 20
    assert nodes["m"]["ttft_ms"] == 0
    assert nodes["m"]["throughput"] == 100
    assert nodes["tool"]["usage"] is None and nodes[root]["throughput"] is None


@pytest.mark.parametrize("version, expected", [
    (3, 3), (0, 0), ("0", 0), ("3", 3), (str(2**63 - 1), 2**63 - 1),
    (None, None), (True, None), (-1, None), (1.5, None), ("garbage", None), (str(2**63), None),
])
def test_agent_version_uses_otlp_integer_and_preserves_unknown(version, expected):
    root = span("root")
    if version is not None:
        root["attributes"].append({"key": "agent.version_no", "value": {"intValue": version}})
    root["attributes"].append({"key": "agent.version_name", "value": {"stringValue": "Frozen"}})
    nodes, _, _ = build_nodes(request(root), conversation_id="1")
    assert nodes[0]["agent_version_no"] == expected
    assert nodes[0]["agent_version_name"] == ("Frozen" if expected is not None else None)
    if expected is None:
        assert "nexent.availability.agent_version_no" in nodes[0]["attributes"]


def test_version_is_independent_for_children_and_absent_on_non_agents():
    items = [span("root"), span("child", "root"), span("model", "child", "LLM"), span("tool", "child", "TOOL")]
    for item, version in zip(items, (3, 2, 99, 99)):
        item["attributes"].append({"key": "agent.version_no", "value": {"intValue": str(version)}})
    nodes, _, _ = build_nodes(request(*items), conversation_id="1")
    assert [n["agent_version_no"] for n in nodes] == [3, 2, None, None]


def test_string_attribute_cannot_masquerade_as_integer_version():
    nodes, _, _ = build_nodes(request(span("root", **{"agent.version_no": "3"})), conversation_id="1")
    assert nodes[0]["agent_version_no"] is None


def test_version_name_requires_string_attribute():
    root = span("root")
    root["attributes"].extend([
        {"key": "agent.version_no", "value": {"intValue": "3"}},
        {"key": "agent.version_name", "value": {"intValue": "99"}},
    ])
    nodes, _, _ = build_nodes(request(root), conversation_id="1")
    assert nodes[0]["agent_version_no"] == 3
    assert nodes[0]["agent_version_name"] is None


@pytest.mark.parametrize("ttft", ["-1", "21", "nan", "inf", "unknown"])
def test_unknown_usage_and_invalid_ttft_stay_null(ttft):
    nodes, _, _ = build_nodes(
        request(span("root"), span("m", "root", "LLM", **{"llm.ttft_ms": ttft})),
        conversation_id="1",
    )
    assert nodes[0]["usage"]["total"] is None
    assert nodes[0]["usage"]["complete"] is False
    assert nodes[1]["ttft_ms"] is None
    assert nodes[1]["throughput"] is None


def test_invocation_association_is_preserved_in_node_details():
    nodes, _, _ = build_nodes(
        request(
            span("root", **{"nexent.invocation_id": "root-call"}),
            span(
                "child",
                "root",
                **{
                    "nexent.invocation_id": "child-call",
                    "nexent.parent_invocation_id": "root-call",
                },
            ),
            span("tool", "child", "TOOL", **{"nexent.invocation_id": "child-call"}),
        ),
        conversation_id="1",
    )
    assert nodes[0]["attributes"]["nexent.invocation_id"] == "root-call"
    assert nodes[1]["attributes"]["nexent.parent_invocation_id"] == "root-call"
    assert nodes[2]["attributes"]["nexent.invocation_id"] == "child-call"


def test_missing_parent_and_cycle_are_explicit():
    nodes, _, coverage = build_nodes(request(span("root", "lost")), conversation_id="1")
    assert not coverage["complete"] and nodes[0]["attributes"]["missing_parent"]
    with pytest.raises(TrajectoryCorrupt):
        build_nodes(
            request(span("root", "sub"), span("sub", "root")), conversation_id="1"
        )


def test_technical_chain_is_collapsed_without_duplicate_call_counts():
    nodes, root, coverage = build_nodes(
        request(
            span("root"), span("chain", "root", "CHAIN"), span("model", "chain", "LLM")
        ),
        conversation_id="1",
    )
    assert len(nodes) == 2 and root == "root" and coverage["complete"]
    assert nodes[1]["parent_id"] == "root"
    assert nodes[0]["model_call_count"] == 1 and nodes[0]["direct_child_count"] == 1


def test_nanosecond_subtraction_precedes_float_conversion():
    record = span("root")
    record["startTimeUnixNano"] = "1794272400123456789"
    record["endTimeUnixNano"] = "1794272400143456789"
    nodes, _, _ = build_nodes(request(record), conversation_id="1")
    assert nodes[0]["duration_ms"] == 20


@pytest.mark.parametrize("wall_end", ["1020000000", "500000000"])
def test_observed_monotonic_duration_drives_ttft_and_throughput(wall_end):
    model = span(
        "model",
        "root",
        "LLM",
        **{
            "nexent.duration_ms": "200",
            "llm.ttft_ms": "100",
            "llm.token_count.completion": "10",
        },
    )
    model["endTimeUnixNano"] = wall_end
    nodes, _, _ = build_nodes(request(span("root"), model), conversation_id="1")
    assert nodes[1]["duration_ms"] == 200
    assert nodes[1]["ttft_ms"] == 100
    assert nodes[1]["throughput"] == 50
    assert nodes[1]["finished_at"] is not None


@pytest.mark.parametrize("duration", ["-1", "NaN", "Infinity", "unknown", True])
def test_explicit_invalid_duration_does_not_fall_back_to_wall_clock(duration):
    model = span(
        "model",
        "root",
        "LLM",
        **{
            "nexent.duration_ms": duration,
            "llm.ttft_ms": "0",
            "llm.token_count.completion": "10",
        },
    )
    nodes, _, _ = build_nodes(request(span("root"), model), conversation_id="1")
    assert nodes[1]["duration_ms"] is None
    assert nodes[1]["ttft_ms"] is None
    assert nodes[1]["throughput"] is None


@pytest.mark.parametrize("duration", [None, "200"])
def test_explicit_unavailable_duration_does_not_fall_back_to_wall_clock(duration):
    attributes = {"nexent.availability.duration_ms": "not_captured"}
    if duration is not None:
        attributes["nexent.duration_ms"] = duration
    record = span("root", **attributes)
    nodes, _, _ = build_nodes(request(record), conversation_id="1")
    assert nodes[0]["duration_ms"] is None


def test_measured_zero_duration_remains_distinct_from_unknown():
    model = span(
        "model",
        "root",
        "LLM",
        **{
            "nexent.duration_ms": "0",
            "llm.ttft_ms": "0",
            "llm.token_count.completion": "0",
        },
    )
    nodes, _, _ = build_nodes(request(span("root"), model), conversation_id="1")
    assert nodes[1]["duration_ms"] == 0
    assert nodes[1]["ttft_ms"] == 0
    assert nodes[1]["throughput"] is None


def test_unfinished_operation_has_no_terminal_duration():
    record = span("root", **{"nexent.duration_ms": "200"})
    record["endTimeUnixNano"] = None
    nodes, _, _ = build_nodes(request(record), conversation_id="1")
    assert nodes[0]["duration_ms"] is None
    assert nodes[0]["status"] == "interrupted"


def test_unclassified_transport_span_is_not_an_agent_call():
    technical = span("http", "root", "")
    nodes, root, coverage = build_nodes(
        request(span("root"), technical, span("model", "http", "LLM")),
        conversation_id="1",
    )
    assert root == "root" and coverage["complete"]
    assert [n["id"] for n in nodes] == ["root", "model"]
    assert nodes[1]["parent_id"] == "root" and nodes[0]["direct_child_count"] == 1


def test_inherited_agent_name_does_not_replace_model_or_tool_name():
    nodes, _, _ = build_nodes(
        request(
            span("root", **{"agent.name": "Report Agent"}),
            span(
                "m",
                "root",
                "LLM",
                **{"agent.name": "Report Agent", "llm.model_name": "deepseek"},
            ),
            span(
                "t",
                "root",
                "TOOL",
                **{"agent.name": "Report Agent", "tool.name": "search"},
            ),
        ),
        conversation_id="1",
    )
    assert [node["name"] for node in nodes] == ["Report Agent", "deepseek", "search"]


def test_duplicate_large_bodies_compare_full_content_not_preview(tmp_path):
    import json
    import os

    from infrastructure.observability.trajectory_reader import JSONReader

    def parsed_requests(*records):
        path = tmp_path / "duplicate.otlp.jsonl"
        path.write_text(json.dumps(request(*records)[0]))
        fd = os.open(path, os.O_RDONLY)
        try:
            return list(JSONReader(fd, path.stat().st_size).requests())
        finally:
            os.close(fd)

    first = span("root", **{"output.value": "a" * 20_000 + "original"})
    repeated = span("root", **{"output.value": "a" * 20_000 + "original"})
    changed = span("root", **{"output.value": "a" * 20_000 + "modified"})
    assert (
        len(build_nodes(parsed_requests(first, repeated), conversation_id="1")[0]) == 1
    )
    with pytest.raises(TrajectoryCorrupt, match="Conflicting duplicate"):
        build_nodes(parsed_requests(first, changed), conversation_id="1")


@pytest.mark.parametrize(
    "dropped", ["droppedAttributesCount", "droppedEventsCount", "droppedLinksCount"]
)
def test_dropped_otlp_facts_make_subtree_metrics_partial(dropped):
    record = span("root")
    record[dropped] = 1
    nodes, _, coverage = build_nodes(
        request(record, span("m", "root", "LLM")), conversation_id="1"
    )
    assert not coverage["complete"] and coverage["capture_gap"]
    assert nodes[0]["model_call_count"] is None and not nodes[0]["usage"]["complete"]
