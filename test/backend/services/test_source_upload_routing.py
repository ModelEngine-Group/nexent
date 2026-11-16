# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Only KB lifecycle uploads use source pinning; unknown uploads retain their intent."""

from unittest.mock import AsyncMock, Mock

import pytest
from nexent.storage.errors import OutcomeUnknown


@pytest.mark.asyncio
async def test_kb_upload_uses_publisher_and_preserves_response(mocker):
    from management.services.file import service

    upload = Mock(
        filename="source.txt", read=AsyncMock(return_value=b"source"), seek=AsyncMock()
    )
    record = {
        "file_id": "a" * 32,
        "object_name": "planned/source.txt",
        "bucket_name": "files",
    }
    publish = mocker.patch.object(service, "upload_knowledge_source", new=AsyncMock())
    legacy = mocker.patch.object(service, "upload_fileobj")
    result = await service.upload_to_minio([upload], "folder", file_records={0: record})
    publish.assert_awaited_once_with(
        record, b"source", service.get_content_type("source.txt")
    )
    legacy.assert_not_called()
    assert result[0]["success"] and result[0]["object_name"] == record["object_name"]
    assert result[0]["url"] == "/files/planned/source.txt"


@pytest.mark.asyncio
async def test_unknown_upload_is_explicit_and_never_uses_legacy_fallback(mocker):
    from management.services.file import service

    upload = Mock(
        filename="source.txt", read=AsyncMock(return_value=b"source"), seek=AsyncMock()
    )
    mocker.patch.object(
        service, "upload_knowledge_source", new=AsyncMock(side_effect=OutcomeUnknown())
    )
    legacy = mocker.patch.object(service, "upload_fileobj")
    result = await service.upload_to_minio(
        [upload], "folder", file_records={0: {"file_id": "a" * 32}}
    )
    assert result[0]["outcome_unknown"] is True and result[0]["success"] is False
    legacy.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_batch_retains_uploading_intent(mocker):
    import sys
    from types import SimpleNamespace

    from management.services.file import service
    from management.services.knowledge_base import storage

    record = {
        "file_id": "a" * 32,
        "object_name": "planned/source.txt",
        "status": "UPLOADING",
    }
    context = SimpleNamespace(
        tenant_id="tenant-a",
        knowledge_id=1,
        index_name="kb",
        bucket_name="files",
        ingroup_permission="EDIT",
    )
    mocker.patch.object(storage, "resolve_storage_context", return_value=context)
    quota = Mock()
    quota.check_hard_limit.return_value = {}
    mocker.patch.dict(
        sys.modules,
        {
            "management.services.knowledge_base.quota": SimpleNamespace(
                QuotaService=Mock(return_value=quota)
            )
        },
    )
    mocker.patch.object(service, "_validate_knowledge_file_sizes", new=AsyncMock())
    mocker.patch.object(
        service, "_get_complete_upload_batch_size", new=AsyncMock(return_value=6)
    )
    mocker.patch.object(service, "create_file_records", return_value=[record])
    mocker.patch.object(
        service, "generate_object_name", return_value=record["object_name"]
    )
    mocker.patch.object(
        service,
        "upload_to_minio",
        new=AsyncMock(
            return_value=[
                {
                    "success": False,
                    "file_id": record["file_id"],
                    "file_name": "source.txt",
                    "outcome_unknown": True,
                    "error": "requires reconciliation",
                }
            ]
        ),
    )
    mocker.patch.object(service, "get_vector_db_core")
    mocker.patch.object(
        service.ElasticSearchService,
        "list_files",
        new=AsyncMock(return_value={"files": []}),
    )
    transition = mocker.patch.object(service, "transition_file_record")
    result = await service.upload_files_impl(
        "minio",
        [Mock(filename="source.txt")],
        folder="knowledge_base",
        index_name="kb",
        user_id="user-a",
        uploader_tenant_id="tenant-a",
    )
    transition.assert_not_called()
    errors, paths, names = result
    assert errors and not paths and not names
