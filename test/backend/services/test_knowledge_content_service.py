# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management content reads never release bytes after revocation or the deadline."""

import asyncio
from time import monotonic
from unittest.mock import Mock

import pytest
from contracts.agentos_knowledge import (
    KnowledgeContentGrant,
    KnowledgeContentRequest,
    ObjectReference,
)
from management.services.knowledge_base import content as module
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import OperationContext

from infrastructure.agentos_identity import ServicePrincipal


@pytest.mark.parametrize("changed", [False, True])
def test_management_reads_with_same_identity_and_withholds_replaced_source(mocker, changed):
    request = KnowledgeContentRequest(knowledge_id=1, file_id="a" * 32, file_version=0)
    ref = ObjectReference(space="files", key="source", version="v1", sha256="b" * 64)
    grant = KnowledgeContentGrant(**request.model_dump(), object_ref=ref, filename="source.txt")
    newer = grant.model_copy(update={"object_ref": ref.model_copy(update={"version": "v2"})}) if changed else grant
    authorize = mocker.patch.object(module, "authorize_knowledge_content", side_effect=[grant, newer])
    read = mocker.patch.object(module, "read_knowledge_content", return_value=b"content")
    actor = ServicePrincipal("user", "tenant")
    context = OperationContext("read", monotonic() + 1)
    if changed:
        with pytest.raises(ScopeDenied):
            module._fetch(request, actor, context=context)
    else:
        assert module._fetch(request, actor, context=context) == (b"content", "source.txt")
    assert authorize.call_count == 2 and read.call_count == 1
    assert read.call_args.args == (actor, grant)
    assert read.call_args.kwargs == {"role": "management", "context": context}


@pytest.mark.asyncio
async def test_management_queue_wait_is_included_in_deadline(mocker, caplog):
    closed = Mock()

    async def pending(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            closed()

    mocker.patch.object(module, "CONTENT_SECONDS", 0.02)
    worker = mocker.patch.object(module, "run_blocking", side_effect=pending)
    with pytest.raises(TimeoutError):
        await module.fetch_knowledge_content(KnowledgeContentRequest(knowledge_id=1, file_id="a" * 32, file_version=0),
                                              user_id="private-user", tenant_id="private-tenant")
    assert worker.await_count == 1
    closed.assert_called_once()
    records = [record for record in caplog.records if record.name == module.__name__]
    assert len(records) == 1 and records[0].levelname == "WARNING"
    assert "threshold_seconds=0.02" in records[0].message and "private-" not in records[0].message
