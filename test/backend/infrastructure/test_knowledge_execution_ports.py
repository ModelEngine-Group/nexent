# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Execution handles grant exact pinned reads and a tenant-qualified vector schema."""

from time import monotonic
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from contracts.agentos_knowledge import KnowledgeFileGrant
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import ObjectRef, OperationContext, Revision

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.knowledge_objects import bind_knowledge_objects
from infrastructure.knowledge_vectors import knowledge_index, vector_binding


def grant():
    return KnowledgeFileGrant(
        knowledge_id=1,
        file_id="a" * 32,
        file_version=0,
        action="execute",
        filename="source.txt",
        collection="kb",
        source={
            "space": "files",
            "key": "source",
            "version": "etag:source",
            "sha256": "a" * 64,
        },
        artifact={
            "space": "files",
            "key": "artifact",
            "version": "etag:artifact",
            "sha256": "b" * 64,
        },
        parser_version="v2",
    )


def test_source_and_artifact_have_separate_exact_physical_grants(mocker):
    source, artifact = Mock(), Mock()
    create = mocker.patch(
        "infrastructure.knowledge_objects.S3ObjectStore", side_effect=[source, artifact]
    )
    mocker.patch(
        "infrastructure.knowledge_objects._configured_environment",
        return_value=SimpleNamespace(MINIO_DEFAULT_BUCKET="owned-bucket"),
    )
    context = OperationContext("ports", monotonic() + 5)
    objects = bind_knowledge_objects(
        ServicePrincipal("user", "tenant"), grant(), context=context
    )
    ref = ObjectRef("files", "source", Revision("etag:source"))
    assert objects.stat(ref, context=context) == source.stat.return_value
    objects.open_read(
        ObjectRef("files", "artifact", Revision("etag:artifact")), context=context
    )
    assert artifact.open_read.call_count == 1
    first, second = [call.args for call in create.call_args_list]
    assert first[0].service_role == "runtime" and first[0].tenant_id == "tenant"
    assert first[1].exact_keys == {"source"} and first[1].prefix == ""
    assert second[1].exact_keys == {"artifact"} and second[1].prefix == "tenant/"
    assert not first[1].writable and not second[1].writable
    with pytest.raises(ScopeDenied):
        objects.stat(ObjectRef("files", "source", Revision("other")), context=context)
    objects.close()
    objects.close()
    source.close.assert_called_once()
    artifact.close.assert_called_once()
    with pytest.raises(ScopeDenied):
        objects.stat(ref, context=context)


def test_second_handle_failure_closes_first(mocker):
    source = Mock()
    mocker.patch(
        "infrastructure.knowledge_objects.S3ObjectStore",
        side_effect=[source, RuntimeError("controlled")],
    )
    mocker.patch(
        "infrastructure.knowledge_objects._configured_environment",
        return_value=SimpleNamespace(MINIO_DEFAULT_BUCKET="owned-bucket"),
    )
    with pytest.raises(RuntimeError):
        bind_knowledge_objects(
            ServicePrincipal("user", "tenant"),
            grant(),
            context=OperationContext("ports", monotonic() + 5),
        )
    source.close.assert_called_once()


def test_vector_schema_is_stable_tenant_qualified_and_does_not_reuse_legacy_index():
    first = knowledge_index("tenant", "kb")
    assert first == knowledge_index("tenant", "kb") and first.startswith("si-kb-")
    assert first != "kb" and first != knowledge_index("other", "kb")
    binding = vector_binding("tenant", "kb", 2)
    assert binding.index == first and binding.dimensions == 2 and binding.writable
    assert {
        "file_id",
        "file_version",
        "knowledge_id",
        "embedding_revision",
        "location",
    } <= set(binding.schema)
