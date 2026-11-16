# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Only explicit lifecycle phases survive technical-span filtering."""

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
