# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Internal context cannot enter public model deltas or confirmed answers."""

import json
from types import SimpleNamespace

import pytest
from nexent.core.agent_runtime_support.answer import (
    AnswerBoundaryError,
    PublicTextFilter,
    normalize_public_answer,
)
from nexent.core.agents.core_adapters.events import JiuwenEventAdapter
from nexent.core.model_service.contracts import AssistantMessage
from nexent.core.utils.observer import MessageObserver

HISTORY = '<completed_action_history read_only="true">PRIVATE_RECORD {"url":"s3://private/hidden"}</completed_action_history>'
ANSWER = '文件已生成：[下载](s3://nexent/workspace/report.docx)\n\n```python\nprint("example")\n```'
RAW = HISTORY + "\n<final_answer>" + ANSWER + "</final_answer>"


@pytest.mark.parametrize("split", range(len(RAW) + 1))
def test_every_fragment_boundary_hides_history_and_final_markers(split):
    public = PublicTextFilter()
    first = public.push(RAW[:split])
    assert "PRIVATE_RECORD" not in first and "s3://private" not in first
    assert "<final_answer" not in first and "completed_action" not in first
    result = first + public.push(RAW[split:])
    public.finish()
    assert result.strip() == ANSWER
    assert normalize_public_answer(RAW) == ANSWER
    assert normalize_public_answer(ANSWER) == ANSWER


@pytest.mark.parametrize("raw", [
    '<completed_action_history>PRIVATE', '<final_answer>missing close',
    '<final_answer>A</final_answer><final_answer>B</final_answer>',
    '<final_answer><final_answer>A</final_answer></final_answer>',
    'unexpected preface <final_answer>A</final_answer>',
    '<code>danger()</code><final_answer>done</final_answer>',
    '<final_answer><code>danger()</code></final_answer>',
    '<final_answer></final_answer>', '<final_answer>PRIVATE</final_answer', None,
])
def test_ambiguous_or_executable_final_never_confirms_success(raw):
    with pytest.raises(AnswerBoundaryError, match="JIUWEN_FINAL_OUTPUT_INVALID"):
        normalize_public_answer(raw)


def test_ordinary_markup_math_case_insensitive_history_and_attachment_echo():
    text = ('<HISTORICAL_ATTACHMENTS>PRIVATE</HISTORICAL_ATTACHMENTS>'
            '<COMPLETED_ACTION_HISTORY><completed_action>PRIVATE</completed_action></COMPLETED_ACTION_HISTORY>'
            '<final_answer><b>Answer</b>: x < 3, y > 2</final_answer>')
    assert normalize_public_answer(text) == '<b>Answer</b>: x < 3, y > 2'


def test_adapter_confirmed_final_and_block_match_clean_wire_content():
    observer = MessageObserver()
    adapter = JiuwenEventAdapter(observer, "agent", "turn")
    adapter.begin_step(None)
    for char in RAW:
        adapter.model_event(SimpleNamespace(type="text_delta", delta=char))
    adapter.model_event(SimpleNamespace(type="message_completed", message=AssistantMessage(
        content_parts=[{"type": "text", "text": RAW}], finish_reason="stop")))
    adapter.emit({"type": "answer", "payload": {"output": RAW}})
    result = adapter.finish()
    events = [json.loads(item) for item in observer.get_cached_message()]
    assert result.status == "completed" and result.final_content == ANSWER
    assert "PRIVATE_RECORD" not in json.dumps(events)
    assert "completed_action_history" not in json.dumps(events)
    assert "<final_answer>" not in json.dumps(events)
    selected = ''.join(e["content"] for e in events if e.get("block_id") in result.final_block_ids
                       and e["type"] == "model_output")
    assert selected.strip() == ANSWER
    assert sum(e["type"] == "final_answer" for e in events) == 1


def test_bad_terminal_returns_failed_result_without_exposing_rejected_answer():
    adapter = JiuwenEventAdapter(MessageObserver(), "agent", "turn")
    with pytest.raises(AnswerBoundaryError):
        adapter.emit({"type": "answer", "payload": {"output": '<final_answer>unfinished'}})
    result = adapter.finish()
    assert result.status == "failed" and result.end_reason == "JIUWEN_FINAL_OUTPUT_INVALID"
    assert result.final_content == "" and result.final_block_ids == []


def test_filters_are_per_block_and_tool_results_remain_exact():
    observer = MessageObserver()
    adapter = JiuwenEventAdapter(observer, "agent", "turn")
    adapter.begin_step(None)
    adapter.model_event(SimpleNamespace(type="text_delta", delta='<completed_action_history>PRIVATE'))
    adapter.begin_step(None)
    adapter.model_event(SimpleNamespace(type="text_delta", delta="Public new step"))
    adapter.tool_result("call", "provider", RAW)
    events = [json.loads(item) for item in observer.get_cached_message()]
    assert any(e["type"] == "model_output" and e["content"] == "Public new step" for e in events)
    assert next(e for e in events if e["type"] == "tool_result")["result"] == RAW
