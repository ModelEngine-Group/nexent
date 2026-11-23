# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""RSR-004 coverage through LegacyChatModel and the real streaming adapter."""

import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from smolagents.tools import Tool

from nexent.core.model_errors import ModelInvocationTerminalError
from nexent.core.model_service.compatibility.legacy_chat_model import LegacyChatModel
from nexent.core.model_service.concurrency import ModelConcurrencyLimiter
from nexent.core.model_service.http_contracts import ModelTransportError
from nexent.core.model_service.service import ModelService
from nexent.core.model_service.sse import SSEEvent


class ProbeTool(Tool):
    name = "fixture_lookup"
    description = "A wire-only test tool"
    inputs = {}
    output_type = "string"

    def forward(self):
        raise AssertionError("Model transport must not execute the tool")


class RecordingSender:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = []

    def freeze_credentials(self, _request):
        return self

    @contextmanager
    def stream(self, request, **_kwargs):
        self.calls.append(request)
        outcome = next(self.outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        yield iter(outcome)


def frame(delta=None, finish=None):
    return SSEEvent(json.dumps({"choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish}]}))


@pytest.mark.parametrize("stop_owner,reasoning,first_finish,retry_outcome,expected_stops", [
    ("runtime", "thought <code>", "stop", "answer", [True, False]),
    ("runtime", "thought <code>", "stop", "empty", [True, False]),
    ("runtime", "thought <code>", "stop", "transport_error", [True, False, True]),
    ("runtime", "", "stop", "answer", [True, True]),
    ("runtime", "thought <code>", "stop", "budget_exhausted", [True]),
    ("runtime", "thought <code>", "length", "no_retry", [True]),
    ("runtime", "thought <code>", "stop", "refusal", [True]),
    ("runtime", "thought <code>", "tool_calls", "tool_call", [True]),
    ("saved", "thought <code>", "stop", "answer", [True, True]),
    ("explicit", "thought <code>", "stop", "answer", [True, True]),
    ("ordinary", "thought <code>", "stop", "answer", [True, True]),
])
def test_reasoning_only_can_omit_runtime_stop_for_one_existing_attempt(
    openai_profile, monkeypatch, stop_owner, reasoning, first_finish, retry_outcome, expected_stops,
):
    stops = ["<RESULT>", "</code>"]
    data = openai_profile.model_dump()
    data["capabilities"]["tools"]["status"] = "supported"
    if stop_owner == "saved":
        data["parameter_values"]["stop"] = stops
    profile = type(openai_profile).model_validate(data)
    delta = {"reasoning_content": reasoning} if reasoning else {}
    if retry_outcome == "refusal":
        delta["refusal"] = "declined"
    if retry_outcome == "tool_call":
        delta["tool_calls"] = [{
            "index": 0, "id": "call_1", "type": "function",
            "function": {"name": "fixture_lookup", "arguments": "{}"},
        }]
    first = [frame(delta), frame(finish=first_finish), SSEEvent("[DONE]")]
    answer = [frame({"content": "<code>print(1)</code>"}), frame(finish="stop"), SSEEvent("[DONE]")]
    outcomes = {
        "answer": [first, answer],
        "empty": [first, first],
        "transport_error": [first, ModelTransportError("HTTP_TIMEOUT"), answer],
    }.get(retry_outcome, [first])
    limiter = ModelConcurrencyLimiter()
    sender = RecordingSender(outcomes)
    service = ModelService(lambda _: sender, limiter=limiter, retry_policy=SimpleNamespace(
        max_attempts=1 if retry_outcome == "budget_exhausted" else 3, calculate_backoff=lambda _: 0,
    ))
    spans = []
    monkeypatch.setattr(service._monitoring, "add_span_event", lambda name, attrs: spans.append((name, attrs)))
    model = LegacyChatModel(profile, service)
    rollback = Mock(wraps=model.observer.rollback_model_attempt)
    monkeypatch.setattr(model.observer, "rollback_model_attempt", rollback)
    options = {"stop": stops} if stop_owner == "explicit" else {}
    if stop_owner != "ordinary":
        options["_retry_without_runtime_stop"] = True
    messages = [{"role": "user", "content": "hello"}]
    options.update(stop_sequences=stops, tools_to_call_from=[ProbeTool()])

    if retry_outcome in {"empty", "no_retry", "budget_exhausted"}:
        with pytest.raises(ModelInvocationTerminalError):
            model.generate(messages, **options)
    else:
        result = model.generate(messages, **options)
        if retry_outcome == "refusal":
            assert result.refusal == "declined"
        elif retry_outcome == "tool_call":
            assert result.tool_calls[0].function.name == "fixture_lookup"
        else:
            assert result.content == "<code>print(1)</code>" and not result.tool_calls
        assert result.runtime_stop_omitted is (not expected_stops[-1])

    assert [request.json_body.get("stop") for request in sender.calls] == [
        stops if expected else None for expected in expected_stops
    ]
    assert all(("stop" in request.json_body) is expected for request, expected in zip(sender.calls, expected_stops))
    baseline = {key: value for key, value in sender.calls[0].json_body.items() if key != "stop"}
    assert baseline["tools"][0]["function"]["name"] == "fixture_lookup"
    assert all({key: value for key, value in call.json_body.items() if key != "stop"} == baseline
               for call in sender.calls)
    events = [attrs for name, attrs in spans if name == "model_runtime_stop_compatibility_retry"]
    assert [attrs["attempt"] for attrs in events] == ([2] if False in expected_stops else [])
    if events:
        assert events[0] == {
            "request_id": sender.calls[0].request_id, "attempt": 2, "reason": "reasoning_only_stop",
        }
        assert rollback.call_args_list[0].args == (sender.calls[0].request_id, 1)
    assert not limiter._entries
