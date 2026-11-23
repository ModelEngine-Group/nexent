# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from ops.services.trajectory.evolution import observation
from management.db.conversation.evolution_review import summarize_batch


def test_evidence_minimization_and_incomplete_coverage():
    trace, span = "b" * 32, "a" * 16
    node = {"kind": "tool", "status": "failed", "name": "sensitive tool name",
            "source": {"trace_id": trace, "span_id": span}, "_bodies": {"output": "sensitive result"}}
    facts = observation({"request": "请导出 PDF", "file_receipt": False}, [node], "partial")
    assert facts == {"coverage": "partial", "signals": ["file_receipt_missing", "tool_error"],
                     "failed_tool_count": 1, "node_refs": [f"otel:{trace}:{span}"]}
    assert not observation({"request": "请导出 PDF", "file_receipt": True})["signals"]


def test_five_clean_runs_have_no_improvement_signal_and_revocation_hides_previous_findings():
    rows = [{"authorized": True, "observation_state": "observed", "turn_id": i,
             "observation": observation({}, coverage="complete")} for i in range(5)]
    assert summarize_batch(rows) == {"reviewed": 5, "excluded": 0, "missing": 0,
                                     "signals": {}, "no_signal_turn_ids": list(range(5))}
    rows[1].update(authorized=False, observation=observation({"opinion_flag": "N"}))
    rows[2].update(observation=observation({}))
    summary = summarize_batch(rows)
    assert summary["signals"] == {} and summary["excluded"] == summary["missing"] == 1
    assert summary["no_signal_turn_ids"] == [0, 3, 4]


def test_case_outline_retains_tool_identity_without_argument_or_result_bodies():
    trace, span = "b" * 32, "a" * 16
    node = {"kind": "tool", "status": "completed", "name": "private catalog entry",
            "source": {"trace_id": trace, "span_id": span}, "attributes": {"nexent.invocation_id": "call-24"},
            "_bodies": {"arguments": "private note", "output": "private result"}}
    facts = observation({"request": "private request"}, [node], "complete")
    assert facts["case_outline"] == {"tool_count": 1, "tools": [{"node": f"otel:{trace}:{span}", "invocation_id": "call-24"}]}
    assert "private" not in str(facts)
    facts = observation({}, [{**node, "attributes": {"nexent.invocation_id": "bad id with a private value"}}], "complete")
    assert "invocation_id" not in facts["case_outline"]["tools"][0]
