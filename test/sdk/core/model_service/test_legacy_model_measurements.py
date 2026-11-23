# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Verify the legacy OpenAI client shares its physical measurements with Trace."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from nexent.core.models.openai_llm import OpenAIModel
from nexent.monitor.facts import set_fact_sink
from nexent.monitor.model_attempt import ModelAttemptSession
from nexent.monitor.monitoring import _MonitoredChatCompletions
from test_model_attempt_capture import capture as capture  # noqa: PLC0414 - Shared pytest fixture.


@pytest.mark.parametrize("stream", [False, True])
def test_legacy_client_publishes_the_same_physical_measurements(capture, stream):
    manager, local, _ = capture
    reply = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=0, completion_tokens=2, total_tokens=None))
    provider = Mock()
    provider.create.return_value = iter([reply]) if stream else reply
    completions = _MonitoredChatCompletions(provider, "model", "llm")
    completions.catalog_identity = ("tenant", 1, "llm")
    model = SimpleNamespace(
        explicit_sampling=False, model_id="model", model_factory="openai", _coerce_context_budget_snapshot=Mock(
            return_value=None,
        ),
        client=SimpleNamespace(chat=SimpleNamespace(completions=completions)),
    )
    facts = []
    with manager.tracer.start_as_current_span("logical") as logical:
        session = ModelAttemptSession(manager, "model", logical, "legacy", 1)
        set_fact_sink(facts.append)
        try:
            result = OpenAIModel._dispatch_chat_completion(model, stream=stream, _trajectory_capture=session)
            if stream:
                list(result)
            session.legacy_complete("answer", "stop")
            session.end()
        finally:
            set_fact_sink(None)

    physical = next(span for span in local.get_finished_spans() if span.name == "model.attempt")
    provider.create.assert_called_once_with(stream=stream)
    assert facts[-1]["fact_id"] == physical.attributes["nexent.model_attempt.fact_id"]
    assert facts[-1]["span_id"] == f"{physical.context.span_id:016x}"
    assert facts[-1]["input_tokens"] == physical.attributes["llm.token_count.prompt"] == 0
    assert "total_tokens" not in facts[-1] and "llm.token_count.total" not in physical.attributes
