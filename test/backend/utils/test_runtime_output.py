# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Explicit native result and lossless envelope persistence unit contracts."""

import json
import pytest
from infrastructure.runtime_output import RuntimeOutputState
from management.services.agent.stream import finalize_buffered_unit_fragments, serialize_stream_unit_content, is_stream_unit_continuation


def terminal(**kwargs):
    return {"schema_version":1,"runtime_mode":"native_agent","agent_core":"jiuwen","type":"run_terminal",
            "turn_id":"turn","sequence":3,"content":"", "status":"completed","end_reason":"runner_answer",
            "final_content":"Final","final_block_ids":["block"],**kwargs}


def test_root_terminal_is_required_and_child_cannot_complete_parent():
    state=RuntimeOutputState(required=True)
    state.observe(terminal(invocation_id="child"))
    assert state.status=="failed" and not state.final_content
    state.observe(terminal())
    assert state.status=="completed" and state.final_content=="Final"
    state.observe(terminal(status="failed",final_content="",final_block_ids=[]))
    assert state.status=="failed" and not state.final_content


@pytest.mark.parametrize("status",["failed","stopped","invalid"])
def test_invalid_or_unsuccessful_terminal_never_confirms_later_content(status):
    state=RuntimeOutputState()
    state.observe(terminal(status=status))
    assert state.status=="failed" and not state.final_content


def test_fragment_join_preserves_native_envelope_and_block_boundaries():
    data={**terminal(),"type":"model_output","block_id":"a","content":"First "}
    unit={"type":"model_output","content":"","unit_content":"","_runtime_envelope":data,
          "_content_fragments":["First ","second"],"_block_id":"a"}
    assert is_stream_unit_continuation(unit,True,"model_output",data)
    assert not is_stream_unit_continuation(unit,True,"model_output",{**data,"block_id":"b"})
    finalize_buffered_unit_fragments([unit])
    restored=json.loads(unit["unit_content"])
    assert restored["content"]=="First second" and restored["block_id"]=="a"
    assert restored["runtime_mode"]=="native_agent"
    assert json.loads(serialize_stream_unit_content(terminal(),""))["final_block_ids"]==["block"]


@pytest.mark.parametrize("kind", ["step_count", "tool", "tool_result", "step_observation", "run_terminal"])
def test_non_mergeable_native_units_are_serialized_once(kind):
    event = {**terminal(), "type": kind, "content": "**Step 1**", "local_call_id": "call"}
    serialized = serialize_stream_unit_content(event, event["content"])
    unit = {"type": kind, "content": serialized, "unit_content": serialized,
            "_runtime_envelope": dict(event), "unit_index": 2}
    assert finalize_buffered_unit_fragments([unit]) == len(serialized.encode("utf-8"))
    assert json.loads(unit["unit_content"]) == event
    assert unit["content"] == unit["unit_content"]
    assert "_runtime_envelope" not in unit


def test_plain_units_and_intentional_json_text_remain_unchanged():
    raw = json.dumps(terminal())
    plain = {"content": raw, "unit_content": raw}
    event = {**terminal(), "type": "model_output", "block_id": "literal", "content": raw}
    streamed = {"content": "", "unit_content": "", "_runtime_envelope": dict(event),
                "_content_fragments": [raw[:10], raw[10:]]}
    finalize_buffered_unit_fragments([plain, streamed])
    assert plain == {"content": raw, "unit_content": raw}
    assert json.loads(streamed["unit_content"]) == event


def test_native_human_form_roundtrips_without_wrapping_its_schema():
    from infrastructure.runtime_output import project_runtime_history

    form = {"schema_version": 1, "questions": [{"id": "birth", "type": "text", "title": "Birth date?"}]}
    event = {**terminal(), "type": "human_interaction", "content": json.dumps(form)}
    serialized = serialize_stream_unit_content(event, event["content"])
    unit = {"type": "human_interaction", "content": serialized, "unit_content": serialized,
            "_runtime_envelope": event, "unit_index": 7}
    finalize_buffered_unit_fragments([unit])
    _, restored, invalid = project_runtime_history("", [{"unit_type": "human_interaction",
        "unit_content": unit["unit_content"], "unit_index": 7}])
    assert not invalid
    assert json.loads(json.loads(restored[0]["unit_content"])["content"]) == form
    assert json.loads(unit["unit_content"])["sequence"] == event["sequence"]
