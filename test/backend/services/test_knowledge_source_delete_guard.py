# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Source-only deletion uses authorized durable state without a DP/Redis request."""

from unittest.mock import AsyncMock

import pytest
from management.services.knowledge_base import deletion as module

from infrastructure.agentos_identity import ServicePrincipal


@pytest.mark.parametrize("state", ["UPLOADING", "UPLOADED", "PROCESSING", "FORWARDING", "FAILED", "DELETE_REQUESTED", "DELETED"])
async def test_unfinished_or_hidden_source_cannot_be_deleted(monkeypatch, state):
    read = AsyncMock(return_value=[{"file_id": "f", "object_name": "a", "status": state}])
    monkeypatch.setattr(module, "read_knowledge_files", read)
    actor = ServicePrincipal("reader", "tenant")
    with pytest.raises(ValueError, match="Cannot delete source file"):
        await module.KnowledgeBaseDocumentDeletionService._assert_source_only_deletable("kb", "a", actor=actor)
    read.assert_awaited_once_with("kb", actor)


async def test_completed_source_is_allowed_and_id_never_falls_back_to_path(monkeypatch):
    read = AsyncMock(return_value=[{"file_id": "f", "object_name": "a", "status": "COMPLETED"}])
    monkeypatch.setattr(module, "read_knowledge_files", read)
    guard = module.KnowledgeBaseDocumentDeletionService._assert_source_only_deletable
    actor = ServicePrincipal("reader", "tenant")
    await guard("kb", "a", actor=actor, file_id="f")
    with pytest.raises(ValueError, match="Document not found"):
        await guard("kb", "a", actor=actor, file_id="other-kb-file")


async def test_storage_failure_stops_deletion(monkeypatch):
    from nexent.storage.errors import Unavailable

    read = AsyncMock(side_effect=Unavailable())
    monkeypatch.setattr(module, "read_knowledge_files", read)
    with pytest.raises(Unavailable):
        await module.KnowledgeBaseDocumentDeletionService._assert_source_only_deletable(
            "kb", "a", actor=ServicePrincipal("reader", "tenant"))
    assert read.await_count == 1
