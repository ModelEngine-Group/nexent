# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read projection cleans proven runtime text without mutating audit or tool records."""

import copy
import json

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
