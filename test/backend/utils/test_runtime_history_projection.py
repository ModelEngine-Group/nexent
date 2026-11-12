# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read projection cleans proven runtime text without mutating audit or tool records."""

import copy
import json

import pytest

from infrastructure.runtime_output import project_runtime_history

RAW = '<completed_action_history>PRIVATE</completed_action_history><final_answer>[doc](s3://owned/doc.docx)</final_answer>'
CLEAN = '[doc](s3://owned/doc.docx)'


def unit(kind, **kwargs):
    event = {"schema_version": 1, "runtime_mode": "native_agent", "agent_core": "jiuwen",
             "type": kind, "turn_id": "turn", "block_id": "block", **kwargs}
    return {"unit_type": kind, "unit_content": json.dumps(event), "invocation_id": kwargs.get("invocation_id")}


def test_dirty_saved_runtime_has_same_clean_terminal_final_and_block_without_db_mutation():
    units = [unit("model_output", content=RAW), unit("run_terminal", status="completed", final_content=RAW,
             content=json.dumps({"final_content": RAW}),
             final_block_ids=["block"]), {"unit_type": "final_answer", "unit_content": RAW},
             unit("tool_result", result=RAW, content=RAW)]
    before = copy.deepcopy(units)
    final, projected, invalid = project_runtime_history(RAW, units)
    assert not invalid and final == CLEAN and units == before
    assert json.loads(projected[0]["unit_content"])["content"] == CLEAN
    assert json.loads(projected[1]["unit_content"])["final_content"] == CLEAN
    assert "PRIVATE" not in projected[1]["unit_content"]
    assert projected[2]["unit_content"] == CLEAN
    assert projected[3] == before[3]


def test_plain_legacy_and_child_smol_content_are_preserved():
    legacy = [{"unit_type": "final_answer", "unit_content": RAW}]
    assert project_runtime_history(RAW, legacy) == (RAW, legacy, False)
    child = {"unit_type": "final_answer", "unit_content": "child result", "invocation_id": "smol"}
    units = [unit("model_output", content="root"), child]
    _, projected, _ = project_runtime_history("root", units)
    assert projected[-1] == child


def test_invalid_legacy_runtime_final_is_not_confirmed_and_partial_history_stays_hidden():
    raw = '<completed_action_history>PRIVATE'
    units = [unit("model_output", content=raw), unit("run_terminal", status="completed", final_content=raw,
             final_block_ids=["block"])]
    final, projected, invalid = project_runtime_history(raw, units)
    assert invalid and final == ""
    assert json.loads(projected[0]["unit_content"])["content"] == ""
    result = json.loads(projected[1]["unit_content"])
    assert result["status"] == "failed" and result["final_content"] == "" and not result["final_block_ids"]


@pytest.mark.parametrize("invocation", [None, "child"])
@pytest.mark.parametrize("kind", ["step_count", "tool", "tool_result", "step_observation", "run_terminal"])
def test_duplicate_saved_envelope_is_repaired_only_in_read_projection(kind, invocation):
    original = {"schema_version": 1, "runtime_mode": "native_agent", "agent_core": "jiuwen",
                "type": kind, "turn_id": "turn", "sequence": 1, "step_id": "step",
                "content": "**Step 1**", "invocation_id": invocation}
    wrapped = {**original, "content": json.dumps(original)}
    units = [{"unit_type": kind, "unit_content": json.dumps(wrapped), "unit_index": 2,
              "invocation_id": invocation}]
    before = copy.deepcopy(units)
    _, projected, invalid = project_runtime_history("Final", units)
    assert not invalid and units == before
    assert json.loads(projected[0]["unit_content"]) == original
    assert projected[0]["unit_index"] == 2


@pytest.mark.parametrize("field,value", [("turn_id", "other"), ("sequence", 9),
                                        ("type", "tool"), ("invocation_id", "other")])
def test_nested_event_with_different_identity_is_not_unwrapped(field, value):
    original = {"schema_version": 1, "runtime_mode": "native_agent", "agent_core": "jiuwen",
                "type": "step_count", "turn_id": "turn", "sequence": 1, "content": "Step"}
    wrapped = {**original, "content": json.dumps({**original, field: value})}
    units = [{"unit_type": "step_count", "unit_content": json.dumps(wrapped)}]
    _, projected, _ = project_runtime_history("Final", units)
    assert projected == units


def test_model_json_content_is_not_interpreted_as_another_envelope():
    original = {"schema_version": 1, "runtime_mode": "native_agent", "agent_core": "jiuwen",
                "type": "model_output_deep_thinking", "turn_id": "turn", "sequence": 1,
                "content": "Literal JSON"}
    wrapped = {**original, "content": json.dumps(original)}
    units = [{"unit_type": original["type"], "unit_content": json.dumps(wrapped)}]
    _, projected, _ = project_runtime_history("Final", units)
    assert projected == units


@pytest.mark.parametrize("content", [None, "{broken", "[]", '"plain JSON"'])
def test_malformed_or_non_event_json_content_is_preserved(content):
    units = [unit("step_count", content=content)]
    _, projected, invalid = project_runtime_history("Final", units)
    assert not invalid and projected == units


@pytest.mark.parametrize("invocation", [None, "child"])
def test_waiting_terminal_from_real_event_adapter_survives_history_without_db_mutation(invocation):
    from nexent.core.agents.cores.jiuwen.events import JiuwenEventAdapter
    from nexent.core.utils.observer import MessageObserver

    events = JiuwenEventAdapter(MessageObserver(), "fixture", "waiting-turn")
    events.waiting_for_input = True
    result = events.finish()
    original = {**result.model_dump(), "schema_version": 1, "runtime_mode": "native_agent",
                "agent_core": "jiuwen", "type": "run_terminal", "sequence": 2,
                "invocation_id": invocation, "content": result.model_dump_json()}
    units = [{"unit_type": "run_terminal", "unit_content": json.dumps(original), "unit_index": 4,
              "invocation_id": invocation}]
    before = copy.deepcopy(units)
    final, projected, invalid = project_runtime_history("", units)
    assert not invalid and final == "" and units == before
    restored = json.loads(projected[0]["unit_content"])
    assert restored["status"] == "completed" and restored["end_reason"] == "awaiting_input"
    assert restored["final_content"] == "" and restored["final_block_ids"] == [] and restored["error"] is None
    assert json.loads(restored["content"]) == result.model_dump()
    assert restored["invocation_id"] == invocation and projected[0]["unit_index"] == 4


@pytest.mark.parametrize("reason,content,blocks,error", [
    ("runner_answer", "", [], None),
    ("awaiting_input", "<completed_action_history>PRIVATE", [], None),
    ("awaiting_input", "", ["phantom-final"], None),
    ("awaiting_input", "", [], {"category": "original-error"}),
    ("awaiting_input", None, [], None),
])
def test_waiting_marker_does_not_bypass_invalid_final_answer_validation(reason, content, blocks, error):
    units = [unit("run_terminal", status="completed", end_reason=reason, final_content=content,
                  final_block_ids=blocks, error=error, content="{}")]
    before = copy.deepcopy(units)
    _, projected, invalid = project_runtime_history("", units)
    restored = json.loads(projected[0]["unit_content"])
    assert invalid and restored["status"] == "failed"
    assert restored["end_reason"] == "JIUWEN_FINAL_OUTPUT_INVALID" and units == before
    assert json.loads(restored["content"])["status"] == "failed"


@pytest.mark.parametrize("status", ["failed", "stopped"])
def test_unsuccessful_clarification_terminal_is_not_promoted(status):
    units = [unit("run_terminal", status=status, end_reason="awaiting_input", final_content="",
                  final_block_ids=[], error={"category": "original-error"}, content="{}")]
    assert project_runtime_history("", units) == ("", units, False)
