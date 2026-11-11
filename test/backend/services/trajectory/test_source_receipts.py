# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""User-controlled history cannot replace a server-owned message receipt."""

import importlib
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from contracts.agent import AgentRequest
from management.services.agent import context


@pytest.fixture
def agent_request():
    value = AgentRequest(conversation_id=123, query="query", history=[])
    value.__dict__["_trajectory_message_receipt"] = {
        "message_id": "11",
        "tenant_id": "t",
        "user_id": "u",
        "conversation_id": "123",
    }
    return value


def test_saved_receipt_is_bound_to_current_trusted_identity(agent_request):
    assert context.trajectory_source_message_id(agent_request, "u", "t") == "11"


@pytest.mark.parametrize(
    "key,value",
    [
        ("tenant_id", "other"),
        ("user_id", "other"),
        ("conversation_id", "124"),
        ("message_id", True),
        ("message_id", 11),
        ("message_id", "01"),
        ("message_id", "2147483648"),
    ],
)
def test_wrong_or_invalid_receipt_cannot_be_used(agent_request, key, value):
    agent_request.__dict__["_trajectory_message_receipt"][key] = value
    assert context.trajectory_source_message_id(agent_request, "u", "t") is None


def test_debug_and_missing_receipts_remain_unknown(agent_request):
    agent_request.is_debug = True
    assert context.trajectory_source_message_id(agent_request, "u", "t") is None
    del agent_request.__dict__["_trajectory_message_receipt"]
    agent_request.is_debug = False
    assert context.trajectory_source_message_id(agent_request, "u", "t") is None


def test_json_payload_cannot_create_private_source_receipt():
    value = AgentRequest.model_validate(
        {
            "conversation_id": 123,
            "query": "query",
            "history": [],
            "_trajectory_message_receipt": {
                "message_id": "11",
                "tenant_id": "t",
                "user_id": "u",
                "conversation_id": "123",
            },
        }
    )
    assert context.trajectory_source_message_id(value, "u", "t") is None


@pytest.mark.parametrize("receipt", [None, [], SimpleNamespace(message_id="11")])
def test_malformed_receipt_is_ignored(agent_request, receipt):
    agent_request.__dict__["_trajectory_message_receipt"] = receipt
    assert context.trajectory_source_message_id(agent_request, "u", "t") is None


def test_user_save_records_only_actual_committed_message_id(agent_request, mocker):
    service = importlib.import_module("management.services.conversation.service")
    save = mocker.patch.object(service, "save_message", return_value=42)
    assert service.save_conversation_user(agent_request, "u", "t") is None
    assert agent_request.__dict__["_trajectory_message_receipt"] == {
        "message_id": "42",
        "tenant_id": "t",
        "user_id": "u",
        "conversation_id": "123",
    }
    save.assert_called_once()


@pytest.mark.parametrize("result", [None, True, "42"])
def test_unknown_save_receipt_clears_earlier_request_binding(
    agent_request, mocker, result
):
    service = importlib.import_module("management.services.conversation.service")
    mocker.patch.object(service, "save_message", return_value=result)
    service.save_conversation_user(agent_request, "u", "t")
    assert "_trajectory_message_receipt" not in agent_request.__dict__


def test_failed_save_cannot_leave_a_stale_receipt(agent_request, mocker):
    service = importlib.import_module("management.services.conversation.service")
    save = mocker.patch.object(
        service, "save_message", side_effect=RuntimeError("controlled write failure")
    )
    with pytest.raises(RuntimeError, match="controlled write failure"):
        service.save_conversation_user(agent_request, "u", "t")
    assert "_trajectory_message_receipt" not in agent_request.__dict__
    save.assert_called_once()


@pytest.mark.parametrize("sink", ["otlp", "local_file"])
def test_context_uses_server_receipt_only_for_local_capture(
    agent_request, monkeypatch, sink
):
    manager = SimpleNamespace(
        is_enabled=True,
        _config=SimpleNamespace(provider=sink, export_traces=True),
        bind_agent_context=lambda value: value,
    )
    monkeypatch.setitem(
        sys.modules,
        "infrastructure.observability.bootstrap",
        SimpleNamespace(monitoring_manager=manager),
    )
    monkeypatch.setitem(
        sys.modules,
        "management.services.configuration.user.memory",
        SimpleNamespace(
            build_memory_context=Mock(
                return_value=SimpleNamespace(
                    user_config=SimpleNamespace(memory_switch=False)
                )
            ),
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "management.services.monitor.identity",
        SimpleNamespace(
            resolve_monitoring_user_email=Mock(return_value="owner@example.test"),
        ),
    )
    result = context.build_agent_run_context(
        agent_request,
        "u",
        "t",
        "en",
        extra_metadata={"trajectory_source_message_id": "forged"},
    )
    extra = result.metadata.extra_metadata
    if sink == "otlp":
        assert "trajectory_source_message_id" not in extra
        assert "app_version" not in extra
    else:
        assert extra["trajectory_source_message_id"] == "11"
        assert extra["app_version"] == context.APP_VERSION
