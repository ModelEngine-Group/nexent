# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Only confirmed conversation deletions can request trajectory reclamation."""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

# isort: split
from management.services.conversation import service


@pytest.fixture
def cleanup(monkeypatch):
    monkeypatch.setitem(sys.modules, "management.services.automation.service", SimpleNamespace(
        agent_automation_facade=SimpleNamespace(on_conversation_deleted=AsyncMock()),
    ))
    hook = Mock(return_value=True)
    monkeypatch.setattr(service, "request_conversation_cleanup", hook, raising=False)
    return hook


@pytest.mark.asyncio
async def test_single_delete_submits_after_database_success(monkeypatch, cleanup):
    def deleted(conversation_id, user_id):
        cleanup.assert_not_called()
        return True

    monkeypatch.setattr(service, "delete_conversation", deleted)
    assert await service.delete_conversation_service(123, "owner", "tenant") is True
    cleanup.assert_called_once_with([123], "owner")


@pytest.mark.parametrize("outcome", [False, RuntimeError("database unavailable")])
@pytest.mark.asyncio
async def test_single_delete_failure_does_not_submit(monkeypatch, cleanup, outcome):
    monkeypatch.setattr(service, "delete_conversation", Mock(
        **({"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}),
    ))
    with pytest.raises(Exception, match="Conversation 123|database unavailable"):
        await service.delete_conversation_service(123, "owner", "tenant")
    cleanup.assert_not_called()


@pytest.mark.asyncio
async def test_batch_only_submits_confirmed_deleted_ids(monkeypatch, cleanup):
    monkeypatch.setattr(service, "delete_conversations_batch", Mock(return_value=[1, 2]))
    assert await service.delete_conversations_batch_service([1, 2, 999], "owner", "tenant") == {
        "deleted_count": 2, "failed_ids": [999],
    }
    cleanup.assert_called_once_with([1, 2], "owner")


@pytest.mark.asyncio
async def test_batch_database_failure_does_not_submit(monkeypatch, cleanup):
    monkeypatch.setattr(service, "delete_conversations_batch", Mock(side_effect=RuntimeError("database")))
    with pytest.raises(RuntimeError):
        await service.delete_conversations_batch_service([1], "owner", "tenant")
    cleanup.assert_not_called()


@pytest.mark.parametrize("failure", [False, OSError("sensitive filesystem error")])
@pytest.mark.asyncio
async def test_cleanup_submission_failure_preserves_committed_delete(monkeypatch, cleanup, caplog, failure):
    monkeypatch.setattr(service, "delete_conversation", Mock(return_value=True))
    if isinstance(failure, Exception):
        cleanup.side_effect = failure
    else:
        cleanup.return_value = failure
    assert await service.delete_conversation_service(123, "owner", "tenant") is True
    assert "trajectory.conversation_cleanup_deferred" in caplog.text
    assert "sensitive filesystem error" not in caplog.text


@pytest.mark.asyncio
async def test_batch_with_no_deletions_does_not_submit(monkeypatch, cleanup):
    monkeypatch.setattr(service, "delete_conversations_batch", Mock(return_value=[]))
    assert await service.delete_conversations_batch_service([999], "owner", "tenant") == {
        "deleted_count": 0, "failed_ids": [999],
    }
    cleanup.assert_not_called()
