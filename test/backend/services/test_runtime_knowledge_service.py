# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime validates a fresh Management grant and model metadata before admission."""

import asyncio
from contextlib import contextmanager
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from contracts.agentos import ModelMetadata
from contracts.agentos_knowledge import (
    KnowledgeFileGrant,
    KnowledgeFileUpload,
    KnowledgeJobLookup,
)
from nexent.storage.errors import Conflict, DeadlineExceeded, ScopeDenied
from nexent.storage.models import OperationContext
from runtime.knowledge_base.service import KnowledgeService

from infrastructure.agentos_identity import ServicePrincipal


@pytest.fixture
def setup(mocker):
    async def direct(_name, fn, *args, lane, owner, **kwargs):
        return fn(*args, **kwargs)

    mocker.patch("runtime.knowledge_base.service.run_blocking", side_effect=direct)
    payload = KnowledgeFileUpload(
        knowledge_id=1,
        file_id="a" * 32,
        file_version=0,
        idempotency_key="upload",
        artifact={
            "space": "files",
            "key": "artifact",
            "version": "v1",
            "sha256": "b" * 64,
        },
        parser_version="v2",
        embedding_model={"model_id": 2, "revision": "model-v1"},
    )
    grant = KnowledgeFileGrant(source_display={"size_bytes":None,"created_at":None},
        action="upload",
        knowledge_id=1,
        file_id=payload.file_id,
        file_version=0,
        source=payload.artifact,
        filename="source.txt",
        collection="kb",
        embedding_model_id=2,
        artifact=payload.artifact,
        parser_version="v2",
    )
    client = SimpleNamespace(authorize_knowledge=AsyncMock(return_value=grant))
    models = SimpleNamespace(
        get=AsyncMock(
            return_value=ModelMetadata(
                model_id=2,
                model_type="embedding",
                display_name="model",
                revision="model-v1",
            )
        )
    )
    kernel = Mock()
    opened = []

    @contextmanager
    def jobs(actor, approved, *, context):
        opened.append((actor, approved))
        try:
            yield kernel
        finally:
            opened.append("closed")

    service = KnowledgeService(client, models, jobs=jobs)
    actor = ServicePrincipal("user", "tenant")
    return SimpleNamespace(**locals())


async def test_upload_checks_grant_and_revision_before_opening_jobs(setup):
    s = setup
    result = await s.service.upload(s.payload, s.actor)
    assert result == s.kernel.submit.return_value
    request, user, tenant = s.client.authorize_knowledge.call_args.args
    assert request.action == "upload" and user == "user" and tenant == "tenant"
    assert s.opened == [(s.actor, s.grant), "closed"]
    s.models.get.assert_awaited_once_with(2, s.actor)
    s.kernel.submit.assert_called_once()


@pytest.mark.parametrize(
    "change",
    [
        {"file_version": 1},
        {"file_id": "b" * 32},
        {"embedding_model_id": 3},
        {"source": None},
        {"parser_version": "other"},
    ],
)
async def test_wrong_grant_never_opens_jobs(setup, change):
    s = setup
    s.client.authorize_knowledge.return_value = s.grant.model_copy(update=change)
    with pytest.raises(ScopeDenied):
        await s.service.upload(s.payload, s.actor)
    assert s.opened == []
    s.kernel.submit.assert_not_called()


async def test_model_revision_mismatch_never_admits(setup):
    s = setup
    s.models.get.return_value = s.models.get.return_value.model_copy(
        update={"revision": "changed"}
    )
    with pytest.raises(Conflict):
        await s.service.upload(s.payload, s.actor)
    assert s.opened == []


async def test_inspection_uses_read_grant_and_never_looks_up_models(setup):
    s = setup
    lookup = KnowledgeJobLookup(
        knowledge_id=1, file_id=s.payload.file_id, file_version=0, job_id="c" * 32
    )
    s.client.authorize_knowledge.return_value = s.grant.model_copy(
        update={
            "action": "inspect",
            "source": None,
            "artifact": None,
            "parser_version": None,
        }
    )
    await s.service.inspect(lookup, s.actor)
    assert s.client.authorize_knowledge.call_args.args[0].action == "inspect"
    s.models.get.assert_not_awaited()
    s.kernel.inspect.assert_called_once()


async def test_authorization_timeout_cancels_call_without_retry_or_admission(
    setup, caplog
):
    s = setup
    closed = []

    async def hanging(*args):
        try:
            await asyncio.Event().wait()
        finally:
            closed.append(True)

    s.client.authorize_knowledge.side_effect = hanging
    context = OperationContext("short", monotonic() + 0.05)
    with pytest.raises(DeadlineExceeded):
        await s.service.upload(s.payload, s.actor, context=context)
    assert closed == [True] and s.client.authorize_knowledge.await_count == 1
    assert s.opened == []
    assert "knowledge_request_timeout" in caplog.text
