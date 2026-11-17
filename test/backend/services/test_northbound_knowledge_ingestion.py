# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Northbound retains its public task envelopes while internal file identities change."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from contracts.file import UploadFilesResult
from management.services.northbound import process_uploaded_knowledge_for_northbound


@pytest.fixture
def adapter(monkeypatch):
    from management.services.knowledge_base import ingestion

    submit = AsyncMock()
    monkeypatch.setattr(ingestion, "submit_knowledge_files", submit)
    ctx = SimpleNamespace(user_id="asset-owner", tenant_id="asset-tenant")
    upload = UploadFilesResult(
        [],
        ["kb/a", "kb/b"],
        ["a.txt", "b.txt"],
        file_records=[
            {"object_name": "kb/a", "file_id": "a" * 32},
            {"object_name": "kb/b", "file_id": "b" * 32},
        ],
    )
    return submit, ctx, upload


async def test_batch_adapter_preserves_existing_shape_without_new_public_identity_fields(
    adapter,
):
    submit, ctx, upload = adapter
    submit.return_value = {
        "status": "partial_success",
        "task_ids": ["opaque-task"],
        "submitted_count": 1,
        "failed_count": 1,
        "results": [
            {
                "file_id": "a" * 32,
                "source": "kb/a",
                "original_filename": "a.txt",
                "status": "SUBMITTED",
                "task_id": "opaque-task",
            },
            {
                "file_id": "b" * 32,
                "source": "kb/b",
                "original_filename": "b.txt",
                "status": "FAILED",
                "error_code": "060108",
                "error_message": None,
            },
        ],
    }
    result = await process_uploaded_knowledge_for_northbound(
        ctx=ctx, index_name="kb", upload_result=upload
    )
    assert result == {
        "status": "partial_success",
        "task_ids": ["opaque-task"],
        "submitted_count": 1,
        "failed_count": 1,
        "results": [
            {
                "file_id": None,
                "source": "kb/a",
                "original_filename": "a.txt",
                "status": "SUBMITTED",
                "task_id": "opaque-task",
            },
            {
                "file_id": None,
                "source": "kb/b",
                "original_filename": "b.txt",
                "status": "FAILED",
                "error_code": "060108",
                "error_message": None,
            },
        ],
    }
    files, index, actor = submit.call_args.args
    assert (
        index == "kb"
        and actor.user_id == ctx.user_id
        and actor.tenant_id == ctx.tenant_id
    )
    assert [item["file_id"] for item in files] == ["a" * 32, "b" * 32]
    assert "authorization" not in submit.call_args.kwargs


async def test_single_adapter_keeps_task_id_only(adapter):
    submit, ctx, _ = adapter
    submit.return_value = {"task_id": "opaque-task"}
    upload = UploadFilesResult([], ["kb/a"], ["a.txt"])
    assert await process_uploaded_knowledge_for_northbound(
        ctx=ctx, index_name="kb", upload_result=upload
    ) == {"task_id": "opaque-task"}


async def test_single_failure_keeps_the_existing_northbound_error_message(adapter):
    submit, ctx, _ = adapter
    submit.return_value = {
        "status": "failed",
        "results": [{"error_code": "060108"}],
        "task_ids": [],
        "submitted_count": 0,
        "failed_count": 1,
    }
    upload = UploadFilesResult([], ["kb/a"], ["a.txt"])
    result = await process_uploaded_knowledge_for_northbound(
        ctx=ctx, index_name="kb", upload_result=upload
    )
    assert (
        result["status"] == "error"
        and result["message"] == "Data process service failed"
    )
    submit.assert_awaited_once()


async def test_file_list_adapter_passes_actual_actor_and_preserves_service_payload(monkeypatch):
    from management.services import northbound as module

    payload = {"files": [{"file": "a.txt", "status": "FORWARDING"}]}
    listing = AsyncMock(return_value=payload)
    monkeypatch.setattr(module.ElasticSearchService, "list_files", listing)
    ctx, core = SimpleNamespace(user_id="reader", tenant_id="asset-tenant"), object()
    result = await module.list_knowledge_files_for_northbound(ctx=ctx, index_name="kb", vdb_core=core)
    assert result is payload
    listing.assert_awaited_once_with("kb", include_chunks=False, vdb_core=core, user_id="reader", tenant_id="asset-tenant")


async def test_delete_adapter_passes_actor_without_new_public_parameters(monkeypatch):
    from management.services import northbound as module

    payload = {"status": "success", "deleted_minio": True}
    deletion = AsyncMock(return_value=payload)
    monkeypatch.setattr(module.ElasticSearchService, "delete_document_by_scope", deletion)
    ctx, core = SimpleNamespace(user_id="editor", tenant_id="asset-tenant"), object()
    result = await module.delete_knowledge_document_for_northbound(
        ctx=ctx, index_name="kb", path_or_url="a", scope="source_only", vdb_core=core)
    assert result is payload
    deletion.assert_awaited_once_with("kb", "a", "source_only", core, requested_by="editor", tenant_id="asset-tenant")
