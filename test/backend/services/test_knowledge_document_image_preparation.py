# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-DOC-IMAGE-READ-03 preserves document preparation and actor ownership."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from management.services.knowledge_base import management
from nexent.storage.errors import InvalidInput

from infrastructure.agentos_identity import ServicePrincipal


@pytest.fixture
def preparation(mocker):
    actor = ServicePrincipal("operator", "tenant-a")
    core = Mock()
    core.check_index_exists.return_value = True
    core.vectorize_documents.return_value = 2
    model = SimpleNamespace(model="model", model_type="embedding")
    mocker.patch.object(management, "get_knowledge_record", return_value={"tenant_id": actor.tenant_id})
    mocker.patch.object(management.tenant_config_manager, "get_model_config", return_value={"chunk_batch": 7})
    mocker.patch.object(management, "update_last_doc_update_time")
    read = mocker.patch.object(management, "read_document_image", side_effect=[b"first", b"second"])
    return SimpleNamespace(**locals())


def items():
    return [{"content": "caption", "filename": "image.png", "source_type": "minio", "path_or_url": "source.pdf",
             "file_size": 12, "metadata": {"image_url": f"images_in_attachments/{i}.png", "title": "original",
                                           "process_source": "UniversalImageExtractor"}} for i in (1, 2)]


def test_images_keep_original_bytes_and_share_actor_and_deadline(preparation):
    s = preparation
    data = items()
    result = management.KnowledgeBaseManagementService.index_documents(
        embedding_model=s.model, index_name="kb", data=data, vdb_core=s.core, actor=s.actor)
    assert result["success"] and result["total_indexed"] == result["total_submitted"] == 2
    assert [call.args[:2] for call in s.read.call_args_list] == [
        ("images_in_attachments/1.png", s.actor), ("images_in_attachments/2.png", s.actor)]
    assert s.read.call_args_list[0].kwargs["context"] is s.read.call_args_list[1].kwargs["context"]
    request = s.core.vectorize_documents.call_args.kwargs
    assert [row["image_bytes"] for row in request["documents"]] == [b"first", b"second"]
    assert all(row["content"] == "caption" and row["path_or_url"] == "source.pdf" and row["title"] == "original"
               for row in request["documents"])
    assert request["embedding_batch_size"] == 7 and request["embedding_model"] is s.model
    assert "image_bytes" not in data[0]


def test_image_failure_prevents_any_document_vectorization(preparation):
    s = preparation
    s.read.side_effect = [b"first", FileNotFoundError("image missing")]
    with pytest.raises(Exception, match="image missing"):
        management.KnowledgeBaseManagementService.index_documents(
            embedding_model=s.model, index_name="kb", data=items(), vdb_core=s.core, actor=s.actor)
    assert s.read.call_count == 2
    s.core.vectorize_documents.assert_not_called()


def test_missing_actor_is_rejected_before_index_or_object_operations(preparation):
    s = preparation
    with pytest.raises(InvalidInput):
        management.KnowledgeBaseManagementService.index_documents(
            embedding_model=s.model, index_name="kb", data=items(), vdb_core=s.core, actor=None)
    s.core.check_index_exists.assert_not_called()
    s.read.assert_not_called()
