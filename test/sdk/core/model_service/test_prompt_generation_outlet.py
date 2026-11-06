# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Backend prompt generation consumes normalized outlet text without a second retry loop."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from nexent.core.concurrency.cancellation import RunTerminated
from nexent.core.model_errors import ModelErrorCode, ModelInvocationTerminalError


@pytest.fixture
def prompt(monkeypatch):
    modules = {
        "consts.const": {"MESSAGE_ROLE": {"SYSTEM": "system", "USER": "user"},
                         "THINK_END_PATTERN": "</think>", "THINK_START_PATTERN": "<think>"},
        "management.db.model.repository": {"get_model_by_model_id": Mock()},
        "management.services.model.adapter": {"get_llm_adapter_from_config": Mock()},
    }
    for name, values in modules.items():
        module = ModuleType(name)
        module.__dict__.update(values)
        monkeypatch.setitem(sys.modules, name, module)
    path = Path(__file__).resolve().parents[4] / "backend/management/services/model/invocation.py"
    spec = importlib.util.spec_from_file_location("_outlet_prompt_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.get_model_by_model_id.return_value = {"profile_schema_version": 1}
    return module


def test_saved_outlet_keeps_defaults_and_accumulated_callback(prompt):
    callback, closed = Mock(), Mock()

    def stream():
        try:
            for text in (None, "<think>hidden", "</think>Hello", " world"):
                yield SimpleNamespace(content=text)
        finally:
            closed()

    model = prompt.get_llm_adapter_from_config.return_value
    model.generate_stream.return_value = stream()
    assert prompt.call_llm_for_system_prompt(42, "user", "system", callback, "tenant") == "Hello world"
    assert [call.args[0] for call in callback.call_args_list] == ["Hello", "Hello world"]
    assert "temperature" not in prompt.get_llm_adapter_from_config.call_args.kwargs
    assert "top_p" not in prompt.get_llm_adapter_from_config.call_args.kwargs
    model.client.chat.completions.create.assert_not_called()
    model.generate_stream.assert_called_once_with([
        {"role": "system", "content": "system"}, {"role": "user", "content": "user"},
    ])
    closed.assert_called_once()


@pytest.mark.parametrize("code,expected", [
    (ModelErrorCode.AUTHENTICATION_ERROR, ErrorCode.MODEL_API_KEY_INVALID),
    (ModelErrorCode.NOT_FOUND, ErrorCode.MODEL_NOT_FOUND),
    (ModelErrorCode.RATE_LIMIT_EXHAUSTED, ErrorCode.MODEL_RATE_LIMIT_EXCEEDED),
    (ModelErrorCode.SERVICE_UNAVAILABLE, ErrorCode.MODEL_SERVICE_UNAVAILABLE),
    (ModelErrorCode.TIMEOUT, ErrorCode.MODEL_CONNECTION_ERROR),
    (ModelErrorCode.UNKNOWN_ERROR, ErrorCode.MODEL_PROMPT_GENERATION_FAILED),
])
def test_terminal_error_maps_once_without_replaying_visible_text(prompt, code, expected):
    closed, callback = Mock(), Mock()

    def stream():
        try:
            yield SimpleNamespace(content="partial")
            raise ModelInvocationTerminalError(code, 3)
        finally:
            closed()

    model = prompt.get_llm_adapter_from_config.return_value
    model.generate_stream.return_value = stream()
    with pytest.raises(AppException) as caught:
        prompt.call_llm_for_system_prompt(42, "user", "system", callback)
    assert caught.value.error_code == expected
    callback.assert_called_once_with("partial")
    model.generate_stream.assert_called_once()
    closed.assert_called_once()


def test_cancellation_propagates_and_closes_stream(prompt):
    closed = Mock()

    def stream():
        try:
            yield SimpleNamespace(content="partial")
            raise RunTerminated()
        finally:
            closed()

    prompt.get_llm_adapter_from_config.return_value.generate_stream.return_value = stream()
    with pytest.raises(RunTerminated):
        prompt.call_llm_for_system_prompt(42, "user", "system")
    closed.assert_called_once()


def test_callback_failure_closes_stream_without_request_replay(prompt):
    closed = Mock()

    def stream():
        try:
            yield SimpleNamespace(content="partial")
            yield SimpleNamespace(content="unconsumed")
        finally:
            closed()

    model = prompt.get_llm_adapter_from_config.return_value
    model.generate_stream.return_value = stream()
    callback = Mock(side_effect=RuntimeError("callback failure"))
    with pytest.raises(AppException) as caught:
        prompt.call_llm_for_system_prompt(42, "user", "system", callback)
    assert caught.value.error_code == ErrorCode.MODEL_PROMPT_GENERATION_FAILED
    closed.assert_called_once()
    callback.assert_called_once_with("partial")
    model.generate_stream.assert_called_once()
