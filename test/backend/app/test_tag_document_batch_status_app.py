
import asyncio

import pytest
from apps import tag_management_app as tag_app
from consts.model import TagDocumentBatchStatusRequest

AUTHORIZATION = "Bearer auth-token"


async def test_document_batch_status_endpoint_forwards_call_context(monkeypatch):
    monkeypatch.setattr(
        tag_app,
        "get_current_user_context",
        lambda authorization: ("user-from-auth", "tenant-from-auth", "ADMIN"),
    )

    async def fake_service(*args, **kwargs):
        return [{"document_id": "doc-a", "assignment_count": 1}]

    monkeypatch.setattr(
        tag_app.TagManagementService, "get_document_tag_batch_status", fake_service
    )
    request = TagDocumentBatchStatusRequest(document_ids=["doc-a", "doc-b"])

    result = await tag_app.get_document_tag_batch_status(request, AUTHORIZATION, "local", "kb-1")

    assert result == [{"document_id": "doc-a", "assignment_count": 1}]


def test_document_batch_status_model_rejects_empty_document_ids():
    with pytest.raises(Exception):
        TagDocumentBatchStatusRequest(document_ids=["doc-a", "  "])
    assert TagDocumentBatchStatusRequest(document_ids=["doc-a", "doc-a"]).document_ids == ["doc-a"]
