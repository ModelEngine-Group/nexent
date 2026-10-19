"""Explicit native result and lossless envelope persistence unit contracts."""

import json
import pytest
from utils.runtime_output import RuntimeOutputState
from utils.agent_stream_utils import finalize_buffered_unit_fragments, serialize_stream_unit_content, is_stream_unit_continuation


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
