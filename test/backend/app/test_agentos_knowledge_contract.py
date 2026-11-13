# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""DPR-P0: serializable cleansing and KB contracts reject unsafe boundaries."""

import hashlib

import pytest
from pydantic import ValidationError

from contracts.agentos_knowledge import (
    CleanseArtifact,
    CleanseBlock,
    KnowledgeFileUpload,
    ObjectReference,
)


def reference():
    return ObjectReference(
        space="knowledge", key="tenant/file.txt", version="v1", sha256="a" * 64
    )


def test_artifact_round_trip_and_order():
    block = CleanseBlock(
        ordinal=0,
        kind="text",
        content="正文",
        sha256=hashlib.sha256("正文".encode()).hexdigest(),
    )
    value = CleanseArtifact(
        source=reference(), parser_version="parser-1", blocks=[block]
    )
    assert CleanseArtifact.model_validate_json(value.model_dump_json()) == value
    with pytest.raises(ValidationError):
        CleanseArtifact.model_validate(
            {**value.model_dump(), "blocks": [{**block.model_dump(), "ordinal": 1}]}
        )


@pytest.mark.parametrize(
    "key",
    ["../secret", "/tmp/file", "tenant/../file", "https://minio/file", "tenant\\file"],
)
def test_object_reference_rejects_local_paths_and_endpoints(key):
    with pytest.raises(ValidationError):
        ObjectReference(space="knowledge", key=key, version="v1", sha256="a" * 64)


def test_text_checksum_is_verified():
    with pytest.raises(ValidationError):
        CleanseBlock(ordinal=0, kind="text", content="changed", sha256="0" * 64)


def test_upload_requires_versioned_models_and_rejects_credentials():
    payload = dict(
        knowledge_id=1,
        file_id="b" * 32,
        file_version=1,
        artifact=reference().model_dump(),
        parser_version="1",
        idempotency_key="upload-1",
        embedding_model={"model_id": 2, "revision": "r1"},
    )
    assert KnowledgeFileUpload.model_validate(payload).embedding_model.model_id == 2
    with pytest.raises(ValidationError):
        KnowledgeFileUpload.model_validate({**payload, "api_key": "forbidden"})
    with pytest.raises(ValidationError):
        KnowledgeFileUpload.model_validate(
            {**payload, "embedding_model": {"model_id": 2}}
        )


@pytest.mark.parametrize("reverse", [False, True])
def test_operations_use_existing_direction_and_body_bound_signature(
    monkeypatch, reverse
):
    from contracts.agentos import OPERATIONS_BY_PATH, ManagementOperation
    from contracts.agentos_knowledge import KnowledgeOperation
    from contracts.constants import environment
    from infrastructure.agentos_identity import (
        AgentOSIdentityError,
        ServicePrincipal,
        sign_call,
        verify_call,
    )

    monkeypatch.setattr(environment, "JWT_SECRET", "synthetic-dpr-contract-key")
    operation = (
        ManagementOperation.FILE_CLEANSE if reverse else KnowledgeOperation.UPLOAD
    )
    actor = ServicePrincipal("user", "tenant")
    token = sign_call(operation, b"{}", actor)
    assert verify_call(token, operation, b"{}") == actor
    if not reverse:
        assert OPERATIONS_BY_PATH[operation.value] is operation
    with pytest.raises(AgentOSIdentityError):
        verify_call(token, operation, b'{"modified":true}')
