"""CMSR-D1-004: correlated protocol diagnostics and opt-in preview privacy."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from nexent.core.agents.core_agent import CoreAgent
from nexent.core.agents.output_protocol import (
    ModelOutputProtocolError,
    ProtocolErrorReason,
)


def _agent(*, finish_reason: str, output_tokens: int, reasoning_chars: int) -> CoreAgent:
    agent = object.__new__(CoreAgent)
    agent.step_number = 1
    agent.output_protocol = "code_action"
    agent._consecutive_protocol_errors = 1
    agent.model = SimpleNamespace(
        model_id="glm-test",
        model_factory="provider-test",
        last_attempt_id="attempt-reasoning-only",
        last_attempt_number=1,
        last_finish_reason=finish_reason,
        last_reasoning_preview="PRIVATE_REASONING\n" * 30,
        last_response_diagnostics={
            "finish_reason": finish_reason,
            "requested_output_tokens": 4096,
            "input_tokens": 4584,
            "output_tokens": output_tokens,
            "reasoning_chunk_count": 4092 if reasoning_chars else 0,
            "reasoning_char_count": reasoning_chars,
            "content_chunk_count": 1 if reasoning_chars else 4,
            "content_char_count": 0 if reasoning_chars else 800,
            "reasoning_only_budget_exhausted": (
                finish_reason == "length" and reasoning_chars > 0
            ),
        },
    )
    return agent


def test_cmsr_d1_004(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    monkeypatch.delenv("NEXENT_PROTOCOL_DIAGNOSTIC_CONTENT", raising=False)
    agent = _agent(finish_reason="length", output_tokens=4096, reasoning_chars=8542)
    error = ModelOutputProtocolError(
        ProtocolErrorReason.EMPTY_VISIBLE_CONTENT, "code_action"
    )
    agent._log_protocol_rejection(error, SimpleNamespace(model_output=None, model_output_message=None))
    first = caplog.text
    assert "reason=empty_visible_content" in first
    assert "model_id=glm-test" in first
    assert "attempt_id=attempt-reasoning-only" in first
    assert "requested_output_tokens=4096" in first
    assert "output_tokens=4096" in first
    assert "reasoning_char_count=8542" in first
    assert "reasoning_only_budget_exhausted=True" in first
    assert "PRIVATE_REASONING" not in first

    caplog.clear()
    agent.model.last_attempt_id = "attempt-malformed"
    agent.model.last_response_diagnostics.update(
        finish_reason="stop",
        output_tokens=25,
        reasoning_chunk_count=0,
        reasoning_char_count=0,
        content_chunk_count=4,
        content_char_count=800,
        reasoning_only_budget_exhausted=False,
    )
    invalid_content = "PRIVATE_CONTENT\n" + "x" * 800 + "SECRET_TAIL"
    malformed = ModelOutputProtocolError(
        ProtocolErrorReason.MALFORMED_ACTION, "code_action"
    )
    agent._log_protocol_rejection(
        malformed,
        SimpleNamespace(model_output=invalid_content, model_output_message=None),
    )
    second = caplog.text
    assert "reason=malformed_action" in second
    assert "attempt_id=attempt-malformed" in second
    assert "reasoning_only_budget_exhausted=False" in second
    assert invalid_content not in second
    assert "PRIVATE_CONTENT" not in second

    caplog.clear()
    monkeypatch.setenv("NEXENT_PROTOCOL_DIAGNOSTIC_CONTENT", "1")
    agent._log_protocol_rejection(
        malformed,
        SimpleNamespace(model_output=invalid_content, model_output_message=None),
    )
    preview = caplog.text
    assert "event=rejected_model_output_preview" in preview
    assert "PRIVATE_CONTENT\\n" in preview
    assert "PRIVATE_REASONING\\n" in preview
    assert "SECRET_TAIL" not in preview
    assert "x" * 257 not in preview
