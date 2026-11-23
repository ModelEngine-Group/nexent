# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime reads only a matching signed grant, with one deadline and no replay."""

import asyncio
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from contracts.agentos_knowledge import (
    KnowledgeContentGrant,
    KnowledgeContentRequest,
    KnowledgeLegacyImageRequest,
    ObjectReference,
)
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import OperationContext
from runtime.knowledge_base import content as module

from infrastructure.agentos_identity import ServicePrincipal


@pytest.fixture
def setup(mocker):
    request = KnowledgeContentRequest(knowledge_id=1, file_id="a" * 32, file_version=0)
    ref = ObjectReference(
        space="files", key="source.txt", version="v1", sha256="b" * 64
    )
    grant = KnowledgeContentGrant(
        **request.model_dump(), object_ref=ref, filename="source.txt"
    )
    client = SimpleNamespace(authorize_knowledge_content=AsyncMock(return_value=grant))
    read = mocker.patch.object(
        module, "read_knowledge_content", return_value=b"content"
    )

    async def blocking(name, method, *args, **kwargs):
        return method(*args, context=kwargs["context"])

    mocker.patch.object(module, "run_blocking", side_effect=blocking)
    service = module.KnowledgeContentReader(client, ServicePrincipal("user", "tenant"))
    return service, request, grant, client, read


@pytest.mark.asyncio
async def test_reader_rechecks_grant_and_reuses_caller_deadline(setup):
    service, request, _, client, read = setup
    context = OperationContext("read", monotonic() + 1)
    assert await service.read(request, context=context) == (b"content", "source.txt")
    assert read.call_count == 1
    bound = read.call_args.kwargs["context"]
    assert bound.deadline == context.deadline and bound.operation_id == context.operation_id
    assert bound.cancelled.is_set()
    assert client.authorize_knowledge_content.await_count == 2
    assert all(
        call.args == (request, "user", "tenant")
        for call in client.authorize_knowledge_content.await_args_list
    )


@pytest.mark.asyncio
async def test_reader_rejects_mismatched_grant_before_storage(setup):
    service, request, grant, client, read = setup
    client.authorize_knowledge_content.return_value = grant.model_copy(
        update={"file_version": 1}
    )
    with pytest.raises(ScopeDenied):
        await service.read(request, context=OperationContext("read", monotonic() + 1))
    read.assert_not_called()


@pytest.mark.asyncio
async def test_reader_withholds_bytes_when_permission_revoked_after_read(setup):
    service, request, grant, client, read = setup
    client.authorize_knowledge_content.side_effect = [grant, ScopeDenied()]
    with pytest.raises(ScopeDenied):
        await service.read(request, context=OperationContext("read", monotonic() + 1))
    read.assert_called_once()


@pytest.mark.asyncio
async def test_reader_timeout_cancels_http_without_retry(setup):
    service, request, _, client, read = setup
    closed = Mock()

    async def pending(*args):
        try:
            await asyncio.Event().wait()
        finally:
            closed()

    client.authorize_knowledge_content.side_effect = pending
    with pytest.raises(TimeoutError):
        await service.read(
            request, context=OperationContext("read", monotonic() + 0.02)
        )
    closed.assert_called_once()
    assert client.authorize_knowledge_content.await_count == 1
    read.assert_not_called()


@pytest.mark.parametrize("changed", [False, True])
async def test_runtime_legacy_attachment_read_checks_signed_reference_before_and_after(setup, mocker, changed):
    service, _, _, client, _ = setup
    request = KnowledgeLegacyImageRequest(knowledge_id=1, chunk_key="old", index_uuid="index", sequence=4, primary_term=1,
        image_ref=ObjectReference(space="files", key="images_in_attachments/old.png", version="etag:v1", sha256="a" * 64))
    client.authorize_legacy_knowledge_image = AsyncMock(side_effect=[
        request, request.model_copy(update={"sequence": 5}) if changed else request])
    read = mocker.patch.object(module, "read_legacy_attachment", return_value=b"legacy")
    context = OperationContext("legacy-read", monotonic() + 5)
    if changed:
        with pytest.raises(ScopeDenied):
            await service.read(request, context=context)
    else:
        assert await service.read(request, context=context) == (b"legacy", "old.png")
    read.assert_called_once()
    assert client.authorize_legacy_knowledge_image.await_count == 2
    assert client.authorize_legacy_knowledge_image.await_args.args == (request, "user", "tenant")
