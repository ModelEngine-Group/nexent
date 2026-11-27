# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""FAF-D2-001 public AgentOS stream and history projection with SDK events."""

import json

import pytest

from nexent.core.utils.observer import MessageObserver, ProcessType
from shared.attempt_journal import capture_attempt_journal


pytestmark = [pytest.mark.case_id("FAF-D2-001"), pytest.mark.stage("D2")]


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["", "Thought. ", "<think>Deep.</think>"])
@pytest.mark.parametrize("invocation", [None, "child"])
async def test_faf_d2_001(monkeypatch, prefix, invocation):
    observer = MessageObserver()
    if invocation:
        observer.add_subagent_start(2, "Child", invocation_id=invocation)
    observer.add_message("agent", ProcessType.STEP_COUNT, 1)
    observer.begin_model_attempt("a", 1)
    for fragment in [prefix + "<final_ans", "wer>Final ", "report</final_answer>"]:
        observer.add_model_new_token(fragment)
    observer.flush_remaining_tokens()
    observer.commit_model_attempt("a", 1)
    observer.complete_final_answer("agent", "Final report")
    events = [json.loads(raw) for raw in observer.get_cached_message()]
    payloads, batch = await capture_attempt_journal(monkeypatch, events)

    units = batch["message_units"]
    assert [unit["content"] for unit in units if unit["type"] == "final_answer"] == ["Final report"]
    assert len([unit for unit in units if unit["type"] == "step_count"]) == bool(prefix)
    answers = [item for item in payloads if item.get("type") == "final_answer"]
    assert "".join(item["content"] for item in answers) == "Final report"
    assert all(item.get("invocation_id") == invocation for item in answers)
    assert not any("Final report" in item["content"] for item in units if item["type"].startswith("model_output"))


@pytest.mark.asyncio
async def test_faf_d2_001_legacy_body_is_moved_without_retransmission(monkeypatch):
    observer = MessageObserver()
    observer.add_message("agent", ProcessType.STEP_COUNT, 1)
    observer.add_model_new_token("Legacy answer")
    observer.flush_remaining_tokens()
    observer.mark_direct_final_answer()
    observer.complete_final_answer("agent", "Legacy answer")
    payloads, batch = await capture_attempt_journal(
        monkeypatch, [json.loads(raw) for raw in observer.get_cached_message()],
    )

    assert sum(event.get("content") == "Legacy answer" for event in payloads) == 1
    assert [(item["type"], item["content"]) for item in batch["message_units"]] == [
        ("final_answer", "Legacy answer"),
    ]
    assert batch["message_content"] == "Legacy answer"
