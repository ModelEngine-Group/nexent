# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from unittest.mock import Mock

import pytest

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from management.services.evaluation import generation_budget


ARGS = dict(source="a" * 64, model_id=4, system_prompt="Rewrite", user_prompt="Input",
            user_id="editor", tenant_id="tenant")


@pytest.fixture
def calls(monkeypatch):
    reserve = Mock(return_value=42)
    invoke = Mock(return_value="output")
    complete = Mock(return_value=True)
    monkeypatch.setattr(generation_budget.generation_attempts, "reserve", reserve)
    monkeypatch.setattr(generation_budget.generation_attempts, "complete", complete)
    monkeypatch.setattr(generation_budget, "invoke_chat_prompt_in_worker", invoke)
    return reserve, invoke, complete


def test_reserves_before_call_and_forwards_output_and_time_limits(calls):
    reserve, invoke, complete = calls
    invoke.side_effect = lambda **kwargs: reserve.assert_called_once_with("tenant", "editor", ARGS["source"], 4) or "ok"
    assert generation_budget.invoke_candidate_model(**ARGS) == "ok"
    assert invoke.call_args.kwargs["max_output_tokens"] == generation_budget.environment.EVOLUTION_GENERATION_MAX_OUTPUT_TOKENS
    assert invoke.call_args.kwargs["timeout_seconds"] == generation_budget.environment.EVOLUTION_GENERATION_TIMEOUT_SECONDS
    complete.assert_called_once_with("tenant", 42)


def test_rate_limit_never_calls_model(calls):
    reserve, invoke, complete = calls
    reserve.side_effect = AppException(ErrorCode.COMMON_RATE_LIMIT_EXCEEDED)
    with pytest.raises(AppException) as caught:
        generation_budget.invoke_candidate_model(**ARGS)
    assert caught.value.error_code == ErrorCode.COMMON_RATE_LIMIT_EXCEEDED
    invoke.assert_not_called()
    complete.assert_not_called()


def test_uncertain_and_late_model_results(calls):
    _, invoke, complete = calls
    invoke.side_effect = TimeoutError
    with pytest.raises(AppException, match="time budget"):
        generation_budget.invoke_candidate_model(**ARGS)
    complete.assert_not_called()
    invoke.side_effect = None
    complete.return_value = False
    with pytest.raises(AppException, match="time budget"):
        generation_budget.invoke_candidate_model(**ARGS)
    complete.assert_called_once_with("tenant", 42)
