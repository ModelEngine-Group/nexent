# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-DOC-IMAGE-READ-03 now prepares pinned images through AgentOS."""

import pytest
from management.services.knowledge_base import documents
from nexent.storage.errors import InvalidInput

from test.backend.services.test_knowledge_documents_preparation import (
    preparation as preparation,  # noqa: PLC0414
)


def items():
    return [{"content": "caption", "filename": "image.png", "source_type": "minio", "path_or_url": "source.pdf",
             "file_size": 12, "metadata": {"image_url": f"images_in_attachments/{i}.png", "title": "original",
                                           "process_source": "UniversalImageExtractor"}} for i in (1, 2)]


async def test_images_keep_original_references_and_share_actor_and_deadline(preparation):
    s = preparation
    refs = [s.ref.model_copy(update={"key": f"images_in_attachments/{i}.png"}) for i in (1, 2)]
    s.pin.side_effect = refs
    data = items()
    result = await documents.index_documents("kb", data, s.actor, reader=s.reader, client=s.client)
    assert result["success"] and result["total_indexed"] == result["total_submitted"] == 2
    assert [call.args[:2] for call in s.pin.call_args_list] == [
        ("images_in_attachments/1.png", s.actor), ("images_in_attachments/2.png", s.actor)]
    assert s.pin.call_args_list[0].kwargs["context"] is s.pin.call_args_list[1].kwargs["context"]
    prepared = s.append.await_args.args[1]
    assert [doc.image_ref for doc in prepared] == refs
    assert all(doc.content == "caption" and doc.metadata["path_or_url"] == "source.pdf"
               and doc.metadata["title"] == "original" for doc in prepared)
    assert not any("image_bytes" in doc.metadata for doc in prepared)
    assert "image_bytes" not in data[0]


async def test_image_failure_prevents_any_document_append(preparation):
    s = preparation
    s.pin.side_effect = [s.ref, FileNotFoundError("image missing")]
    with pytest.raises(FileNotFoundError, match="image missing"):
        await documents.index_documents("kb", items(), s.actor, reader=s.reader, client=s.client)
    assert s.pin.call_count == 2
    s.append.assert_not_awaited()


async def test_missing_actor_is_rejected_before_index_or_object_operations(preparation):
    s = preparation
    with pytest.raises(InvalidInput):
        await documents.index_documents("kb", items(), None, reader=s.reader, client=s.client)
    s.client.ensure_knowledge_collection.assert_not_awaited()
    s.pin.assert_not_called()
