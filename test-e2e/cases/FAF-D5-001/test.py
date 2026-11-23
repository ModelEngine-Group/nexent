"""FAF-D5-001: repeated rollback and sibling isolation at the SSE boundary."""

import pytest
from importlib import import_module

_capture_events = import_module("test-e2e.cases.FAF-D2-001.test")._capture_events

pytestmark = [pytest.mark.case_id("FAF-D5-001"), pytest.mark.stage("D5")]


@pytest.mark.asyncio
@pytest.mark.parametrize("iteration", range(4))
async def test_faf_d5_001(monkeypatch, iteration):
    events = []
    for invocation in ("left", "right"):
        events.append({"type": "step_count", "content": "Step 1", "step_id": invocation,
                       "invocation_id": invocation})
        events.append({"type": "model_attempt_control", "content": "", "phase": "begin",
                       "attempt_id": invocation + "-bad", "invocation_id": invocation})
    for ordinal in range(8):
        for invocation in ("left", "right"):
            events.append({"type": "final_answer", "content": "rejected", "answer_phase": "delta",
                           "step_id": invocation, "invocation_id": invocation,
                           "attempt_id": invocation + "-bad"})
    for invocation in ("right", "left"):
        events.extend([
            {"type": "model_attempt_control", "content": "", "phase": "rollback",
             "attempt_id": invocation + "-bad", "invocation_id": invocation},
            {"type": "final_answer", "content": invocation + "-accepted", "answer_phase": "delta",
             "step_id": invocation, "invocation_id": invocation, "attempt_id": invocation + "-good"},
            {"type": "final_answer", "content": "", "answer_phase": "complete",
             "step_id": invocation, "invocation_id": invocation},
        ])
    payloads, batches = await _capture_events(monkeypatch, events)
    units = batches[0]["message_units"]
    answers = [unit for unit in units if unit["type"] == "final_answer"]
    assert sorted((unit["invocation_id"], unit["content"]) for unit in answers) == [
        ("left", "left-accepted"), ("right", "right-accepted")]
    assert not any(unit["type"] == "step_count" for unit in units)
    assert all("rejected" not in unit["content"] for unit in units)
    assert sum(event.get("phase") == "rollback" for event in payloads) == 2
