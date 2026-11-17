# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Pinned content grants bind exact read-only logical keys and tenant prefixes."""

from time import monotonic
from types import SimpleNamespace

import pytest
from contracts.agentos_knowledge import KnowledgeContentGrant, ObjectReference
from nexent.storage.errors import InvalidInput, ScopeDenied
from nexent.storage.models import OperationContext

from infrastructure import knowledge_content as module
from infrastructure.agentos_identity import ServicePrincipal


@pytest.mark.parametrize(
    "role,image",
    [
        ("management", False),
        ("runtime", False),
        ("management", True),
        ("runtime", True),
    ],
)
def test_port_grants_one_versioned_key_and_closes_after_read(mocker, role, image):
    ref = ObjectReference(
        space="files",
        key="selected.png" if image else "source.txt",
        version="etag:v1",
        sha256="a" * 64,
    )
    grant = KnowledgeContentGrant(
        knowledge_id=1,
        file_id="b" * 32,
        file_version=0,
        object_ref=ref,
        image_ref=ref if image else None,
        filename="source.txt",
    )
    mocker.patch.object(
        module,
        "_configured_environment",
        return_value=SimpleNamespace(MINIO_DEFAULT_BUCKET="bucket"),
    )
    factory = mocker.patch.object(module, "S3ObjectStore")
    read = mocker.patch.object(module, "read_verified_object", return_value=b"content")
    context = OperationContext("read", monotonic() + 1)
    assert (
        module.read_knowledge_content(
            ServicePrincipal("user", "tenant"), grant, role=role, context=context
        )
        == b"content"
    )
    scope, binding, _ = factory.call_args.args
    assert (scope.service_role, scope.tenant_id, scope.actor_id, scope.system) == (
        role,
        "tenant",
        "user",
        False,
    )
    assert binding.exact_keys == {ref.key} and binding.prefix == (
        "tenant/" if image else ""
    )
    assert binding.writable is False and binding.roles == {role}
    assert read.call_args.args[1].version.value == ref.version
    assert (
        read.call_args.kwargs["sha256"] == ref.sha256
        and read.call_args.kwargs["context"] is context
    )
    factory.return_value.close.assert_called_once()


def test_content_port_closes_when_verified_read_fails(mocker):
    mocker.patch.object(
        module,
        "_configured_environment",
        return_value=SimpleNamespace(MINIO_DEFAULT_BUCKET="bucket"),
    )
    factory = mocker.patch.object(module, "S3ObjectStore")
    mocker.patch.object(module, "read_verified_object", side_effect=InvalidInput())
    ref = ObjectReference(
        space="files", key="source", version="etag:v1", sha256="a" * 64
    )
    grant = KnowledgeContentGrant(
        knowledge_id=1,
        file_id="b" * 32,
        file_version=0,
        object_ref=ref,
        filename="source",
    )
    with pytest.raises(InvalidInput):
        module.read_knowledge_content(
            ServicePrincipal("user", "tenant"),
            grant,
            context=OperationContext("read", monotonic() + 1),
        )
    factory.return_value.close.assert_called_once()


def test_content_port_refuses_untrusted_role_before_factory(mocker):
    factory = mocker.patch.object(module, "_configured_environment")
    ref = ObjectReference(space="files", key="source", version="v1", sha256="a" * 64)
    grant = KnowledgeContentGrant(
        knowledge_id=1,
        file_id="b" * 32,
        file_version=0,
        object_ref=ref,
        filename="source",
    )
    with pytest.raises(ScopeDenied):
        module.read_knowledge_content(
            ServicePrincipal("user", "tenant"),
            grant,
            role="gateway",
            context=OperationContext("read", monotonic() + 1),
        )
    factory.assert_not_called()
