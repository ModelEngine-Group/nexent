# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Only confirmed conversation deletions can request trajectory reclamation."""

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

# isort: split
from management.services.conversation import service


@pytest.fixture
def cleanup(monkeypatch):
    monkeypatch.setitem(sys.modules, "management.services.automation.service", SimpleNamespace(
        agent_automation_facade=SimpleNamespace(on_conversation_deleted=Mock()),
    ))
    hook = Mock(return_value=True)
    monkeypatch.setattr(service, "request_conversation_cleanup", hook, raising=False)
    return hook


def test_single_delete_submits_after_database_success(monkeypatch, cleanup):
    def deleted(conversation_id, user_id):
        cleanup.assert_not_called()
        return True

    monkeypatch.setattr(service, "delete_conversation", deleted)
    assert service.delete_conversation_service(123, "owner") is True
    cleanup.assert_called_once_with([123], "owner")


@pytest.mark.parametrize("outcome", [False, RuntimeError("database unavailable")])
def test_single_delete_failure_does_not_submit(monkeypatch, cleanup, outcome):
    monkeypatch.setattr(service, "delete_conversation", Mock(
        **({"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}),
    ))
    with pytest.raises(Exception, match="Conversation 123|database unavailable"):
        service.delete_conversation_service(123, "owner")
    cleanup.assert_not_called()


def test_batch_only_submits_confirmed_deleted_ids(monkeypatch, cleanup):
    monkeypatch.setattr(service, "delete_conversations_batch", Mock(return_value=[1, 2]))
    assert service.delete_conversations_batch_service([1, 2, 999], "owner") == {
        "deleted_count": 2, "failed_ids": [999],
    }
    cleanup.assert_called_once_with([1, 2], "owner")


def test_batch_database_failure_does_not_submit(monkeypatch, cleanup):
    monkeypatch.setattr(service, "delete_conversations_batch", Mock(side_effect=RuntimeError("database")))
    with pytest.raises(RuntimeError):
        service.delete_conversations_batch_service([1], "owner")
    cleanup.assert_not_called()


@pytest.mark.parametrize("failure", [False, OSError("sensitive filesystem error")])
def test_cleanup_submission_failure_preserves_committed_delete(monkeypatch, cleanup, caplog, failure):
    monkeypatch.setattr(service, "delete_conversation", Mock(return_value=True))
    if isinstance(failure, Exception):
        cleanup.side_effect = failure
    else:
        cleanup.return_value = failure
    assert service.delete_conversation_service(123, "owner") is True
    assert "trajectory.conversation_cleanup_deferred" in caplog.text
    assert "sensitive filesystem error" not in caplog.text


def test_batch_with_no_deletions_does_not_submit(monkeypatch, cleanup):
    monkeypatch.setattr(service, "delete_conversations_batch", Mock(return_value=[]))
    assert service.delete_conversations_batch_service([999], "owner") == {
        "deleted_count": 0, "failed_ids": [999],
    }
    cleanup.assert_not_called()
