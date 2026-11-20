# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Native AgentOS presentation must reuse the established stateful client mapper."""

import json
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from starlette.responses import StreamingResponse

from contracts.agentos import AgentResume
from management.services.agent import agentos_events as public

RUN = "a" * 32
REQUEST = AgentResume(conversation_id=42, run_id=RUN)


def native(kind, sequence, **fields):
    return {"schema_version": 1, "runtime_mode": "native_agent", "agent_core": "jiuwen",
            "turn_id": "root", "sequence": sequence, "type": kind, "content": "", **fields}


def complete(sequence, **fields):
    return native("run_terminal", sequence, status="completed", end_reason="runner_answer",
                  final_content="Answer", final_block_ids=["body"], **fields)


def observer(index, payload):
    return f"id: {RUN}:{index}\nevent: agentos_observer\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


def terminal(index, status="completed"):
    return f'id: {RUN}:{index}\nevent: agentos_terminal\ndata: {{"status":"{status}"}}\n\n'.encode()


def response(*chunks, background=None, status_code=200):
    async def source():
        for chunk in chunks:
            yield chunk
    return StreamingResponse(source(), status_code=status_code, background=background,
                             headers={"X-AgentOS-Run-ID": RUN})


async def collect(result):
    wire = b"".join([chunk.encode() if isinstance(chunk, str) else chunk async for chunk in result.body_iterator])
    rows = []
    for frame in wire.decode().split("\n\n"):
        data = next((line[6:] for line in frame.splitlines() if line.startswith("data: ")), None)
        if data is not None:
            rows.append((next((line[4:] for line in frame.splitlines() if line.startswith("id: ")), None),
                         json.loads(data)))
    return wire, rows


def chain():
    return [native("step_count", 1, content="1"),
            native("tool", 2, local_call_id="local", tool_call_id="local", tool_name="lookup",
                   tool_arguments={}, provider_call_id="provider-" + "z" * 260),
            native("tool_result", 3, local_call_id="local", tool_call_id="local", result="EXACT_RESULT",
                   provider_call_id="provider-" + "z" * 260, is_error=False),
            native("model_output", 4, block_id="body", content="Answer"), complete(5)]


@pytest.mark.parametrize("complete_mode", [False, True])
async def test_native_stream_retains_mapping_results_capacity_and_original_input(mocker, complete_mode):
    mocker.patch.object(public, "NEXENT_AGENT_CORE", "smolagents")
    events = chain()
    events.insert(3, native("step_observation", 4, step_number=1, duration=.2,
        usage={"input_tokens": None, "output_tokens": 0}, context_capacity={"context_window_tokens": 9000,
        "token_threshold": 8000, "effective_input_limit_tokens": 9000, "context_processing_mode": "passthrough"}))
    events[4]["sequence"], events[5]["sequence"] = 5, 6
    events[4]["content"] = events[5]["final_content"] = "Answer世界"
    before = deepcopy(events)
    raw = b"".join(observer(index, value) for index, value in enumerate(events, 1)) + terminal(7)
    boundary = raw.index("世".encode())
    result = public.present_public_resume(response(raw[:boundary + 1], raw[boundary + 1:boundary + 2],
                                                   raw[boundary + 2:]), REQUEST, "owner",
                                           complete_answer=complete_mode, on_terminal=AsyncMock(return_value=True))
    wire, rows = await collect(result)
    values = [value for _, value in rows if value.get("type")]
    assert not {"model_output", "tool_result", "step_observation", "run_terminal"} & {v["type"] for v in values}
    assert not any(v.get("runtime_mode") for v in values)
    call = next(v for v in values if v["type"] == "tool")
    output = next(v for v in values if v["type"] == "execution_logs")
    assert call["tool_call_id"] == output["tool_call_id"] and output["content"] == "EXACT_RESULT"
    assert output["provider_call_id"] == events[1]["provider_call_id"]
    usage = json.loads(next(v for v in values if v["type"] == "token_count")["content"])
    assert usage["step_input_tokens"] is None and usage["step_output_tokens"] == 0
    assert usage["context_window_tokens"] == 9000 and usage["context_processing_mode"] == "passthrough"
    assert [v["content"] for v in values if v["type"] == "final_answer"] == ["Answer世界"]
    assert events == before and b"agentos_terminal" in wire


@pytest.mark.parametrize("status,end,final,blocks,expected", [
    ("failed", "mcp_auth_failed", "", [], "error"),
    ("completed", "awaiting_input", "", [], None),
    ("stopped", "cancelled", "", [], None),
])
async def test_native_terminal_preserves_specific_error_stop_and_waiting(status, end, final, blocks, expected):
    value = native("run_terminal", 1, status=status, end_reason=end, final_content=final, final_block_ids=blocks,
                   error={"category": "mcp_auth_failed", "scope": "protocol", "retryable": False,
                          "safe_message": "安全的具体错误", "request_id": "actual-request"} if status == "failed" else None)
    result = public.present_public_resume(response(observer(1, value), terminal(2, status)), REQUEST, "owner",
                                          on_terminal=AsyncMock(return_value=True))
    _, rows = await collect(result)
    values = [value for _, value in rows if value.get("type")]
    assert [value["type"] for value in values] == ([expected] if expected else [])
    if expected:
        assert values[0]["content"] == "安全的具体错误" and values[0]["error_code"] == "mcp_auth_failed"
        assert values[0]["request_id"] == "actual-request" and values[0]["retryable"] is False


@pytest.mark.parametrize("fault", ["missing_outer", "confirmation_false"])
async def test_native_completion_requires_outer_terminal_and_confirmation(fault):
    frames = [observer(1, native("model_output", 1, block_id="body", content="Answer")), observer(2, complete(2))]
    if fault != "missing_outer":
        frames.append(terminal(3))
    result = public.present_public_resume(response(*frames), REQUEST, "owner",
                                          on_terminal=AsyncMock(return_value=False))
    _, rows = await collect(result)
    assert not any(value.get("type") == "final_answer" for _, value in rows)
    assert any(value.get("type") == "error" for _, value in rows)


async def test_raw_fanout_only_acknowledges_last_public_event_and_zero_output_does_not_advance():
    frames = [observer(1, native("step_count", 1, content="1")),
              observer(2, native("model_output", 2, block_id="body", content="Answer")),
              observer(3, complete(3)), terminal(4)]
    _, rows = await collect(public.present_public_resume(response(*frames), REQUEST, "owner"))
    thought = next(index for index, (_, value) in enumerate(rows) if value.get("type") == "model_output_thinking")
    assert rows[thought - 1][0] is None and rows[thought - 1][1]["type"] == "step_count"
    assert rows[thought][0] == f"{RUN}:2"
    assert not any(cursor == f"{RUN}:3" for cursor, _ in rows)
    assert next(cursor for cursor, value in rows if value.get("type") == "final_answer") is None
    assert rows[-1] == (f"{RUN}:4", {"status": "completed"})


async def test_child_and_root_with_identical_local_ids_do_not_cross_pair():
    events = [native("step_count", 1),
              native("tool", 2, local_call_id="same", tool_name="root_tool", provider_call_id="root-provider"),
              native("tool", 1, turn_id="child", invocation_id="child", local_call_id="same",
                     tool_name="child_tool", provider_call_id="child-provider"),
              native("tool_result", 2, turn_id="child", invocation_id="child", local_call_id="same",
                     provider_call_id="child-provider", result="CHILD", is_error=False),
              native("tool_result", 3, local_call_id="same", provider_call_id="root-provider",
                     result="ROOT", is_error=False),
              native("run_terminal", 3, turn_id="child", invocation_id="child", status="completed",
                     end_reason="awaiting_input", final_content="", final_block_ids=[], error=None),
              {"type": "subagent_end", "invocation_id": "child", "content": '{"invocation_id":"child"}'},
              native("model_output", 4, block_id="body", content="Answer"), complete(5)]
    frames = [observer(index, value) for index, value in enumerate(events, 1)] + [terminal(10)]
    _, rows = await collect(public.present_public_resume(response(*frames), REQUEST, "owner"))
    values = [value for _, value in rows]
    calls = {v["provider_call_id"]: v["tool_call_id"] for v in values if v.get("type") == "tool"}
    assert calls["root-provider"] != calls["child-provider"]
    outputs = {v["content"]: v["tool_call_id"] for v in values if v.get("type") == "execution_logs"}
    assert outputs == {"CHILD": calls["child-provider"], "ROOT": calls["root-provider"]}
    assert len([v for v in values if v.get("type") == "final_answer"]) == 1


@pytest.mark.parametrize("entry", ["ephemeral", "legacy_journal"])
async def test_other_public_native_seams_use_the_existing_mapper(entry):
    values = chain()
    if entry == "ephemeral":
        frames = [b"data: " + json.dumps(value).encode() + b"\n\n" for value in values]
        result = public.present_ephemeral_stream(response(*frames), "owner", RUN)
    else:
        frames = [observer(index, value) for index, value in enumerate(values, 1)] + [terminal(6)]
        result = public.present_legacy_journal(response(*frames), RUN, 0, 5)
    _, rows = await collect(result)
    assert not any(value.get("runtime_mode") for _, value in rows)
    assert any(value.get("type") == "execution_logs" for _, value in rows)
    assert [value["content"] for _, value in rows if value.get("type") == "final_answer"] == ["Answer"]
