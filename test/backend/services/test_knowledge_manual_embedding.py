# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Manual chunk preparation uses current SI edit scope and standard model invocation."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from management.services.knowledge_base.chunk_embedding import embed_manual_chunk
from nexent.storage.errors import ScopeDenied

from test.backend.services.test_cleanse_authorization import (
    resources as resources,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_file_reader import (
    reader as reader,  # noqa: PLC0414
)


def test_manual_embedding_selects_only_current_kb_model_and_actual_actor(reader):
    s = reader
    s.update('cleanse_knowledge', embedding_model_id=27)
    invoke = AsyncMock(return_value=[0.1, 0.2])
    model_id, vector = embed_manual_chunk('kb-one', 'original text', s.actor, reader=s.service, invoke=invoke)
    assert (model_id, vector) == (27, [0.1, 0.2])
    invoke.assert_awaited_once_with(model_id=27, query='original text', user_id=s.actor.user_id, tenant_id=s.actor.tenant_id)
    assert s.opened == [('tenant-a', 'user-a')]


def test_manual_embedding_missing_config_does_not_choose_another_model(reader):
    reader.update('cleanse_knowledge', embedding_model_id=None)
    invoke = AsyncMock()
    assert embed_manual_chunk('kb-one', 'text', reader.actor, reader=reader.service, invoke=invoke) == (None, None)
    invoke.assert_not_awaited()


@pytest.mark.parametrize('updates', [
    {'created_by': 'other', 'ingroup_permission': 'PRIVATE'},
    {'deletion_request': {'scope': 'full'}},
])
def test_manual_embedding_refuses_inaccessible_or_deleting_resource(reader, updates):
    reader.update('cleanse_knowledge', embedding_model_id=27, **updates)
    invoke = AsyncMock()
    with pytest.raises(ScopeDenied):
        embed_manual_chunk('kb-one', 'text', reader.actor, reader=reader.service, invoke=invoke)
    invoke.assert_not_awaited()


def test_shared_read_grant_does_not_authorize_manual_writes(reader):
    with pytest.raises(ScopeDenied):
        embed_manual_chunk('shared', 'text', reader.actor, reader=reader.service, invoke=AsyncMock())


def test_manual_embedding_total_deadline_cancels_once_and_redacts_content(reader, caplog):
    prepared = Mock()
    prepared.knowledge.return_value = {'embedding_model_id': 27, 'deletion_request': None}
    cancelled = []
    async def stalled(**kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)
    invoke = AsyncMock(side_effect=stalled)
    assert embed_manual_chunk('kb-one', 'private-fixture-content', reader.actor,
                             reader=prepared, invoke=invoke, operation_seconds=0.02) == (27, None)
    assert cancelled == [True] and invoke.await_count == 1
    assert 'knowledge_manual_chunk_embedding_timeout' in caplog.text
    assert 'private-fixture-content' not in caplog.text


def test_model_failure_preserves_original_plaintext_outcome_without_retry(reader, caplog):
    from contracts.errors.exceptions import RuntimeServiceUnavailableError
    reader.update('cleanse_knowledge', embedding_model_id=27)
    invoke = AsyncMock(side_effect=RuntimeServiceUnavailableError('private-provider-detail'))
    assert embed_manual_chunk('kb-one', 'text', reader.actor, reader=reader.service, invoke=invoke) == (27, None)
    invoke.assert_awaited_once()
    assert 'private-provider-detail' not in caplog.text


def test_resource_failure_cannot_downgrade_into_plaintext_creation(reader, monkeypatch):
    from nexent.storage.errors import Unavailable

    invoke = AsyncMock()
    monkeypatch.setattr(reader.service, 'knowledge', Mock(side_effect=Unavailable()))
    with pytest.raises(Unavailable):
        embed_manual_chunk('kb-one', 'text', reader.actor, reader=reader.service, invoke=invoke)
    invoke.assert_not_awaited()


def test_resource_timeout_blocks_model_and_emits_safe_phase(reader, caplog):
    from nexent.storage.errors import DeadlineExceeded

    prepared = Mock()
    prepared.knowledge.side_effect = DeadlineExceeded()
    invoke = AsyncMock()
    with pytest.raises(DeadlineExceeded):
        embed_manual_chunk('kb-one', 'private-resource-fixture', reader.actor, reader=prepared, invoke=invoke)
    invoke.assert_not_awaited()
    assert 'phase=resource' in caplog.text and 'private-resource-fixture' not in caplog.text


@pytest.mark.parametrize('stalled', [False, True])
def test_default_invoke_signs_actual_identity_and_closes_transport(reader, monkeypatch, stalled):
    import json

    import httpx
    from contracts.agentos import ModelOperation
    from contracts.constants import environment
    from management.clients import model

    from infrastructure.agentos_client import AgentOSClient
    from infrastructure.agentos_identity import verify_call

    monkeypatch.setattr(environment, 'JWT_SECRET', 'synthetic-manual-model-client-key')
    reader.update('cleanse_knowledge', embedding_model_id=27)
    clients, calls, cancelled = [], [], []
    async def handle(request):
        calls.append(True)
        assert request.url.path == '/api' + ModelOperation.INVOKE.value
        token = request.headers['Authorization'].removeprefix('Bearer ')
        assert verify_call(token, ModelOperation.INVOKE, request.content) == reader.actor
        assert json.loads(request.content)['input'] == ['original text']
        assert json.loads(request.content)['model_id'] == 27
        if stalled:
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(True)
        return httpx.Response(200, json={'revision': 'v1', 'output': [[0.1, 0.2]]})
    def create(**kwargs):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)
        clients.append(client)
        return client
    monkeypatch.setattr(model, '_model_client', lambda: AgentOSClient('http://runtime', create))
    selected = reader.service
    if stalled:
        selected = Mock()
        selected.knowledge.return_value = {'embedding_model_id': 27, 'deletion_request': None}
    result = embed_manual_chunk('kb-one', 'original text', reader.actor, reader=selected,
                                operation_seconds=0.03 if stalled else 1)
    assert result == (27, None if stalled else [0.1, 0.2])
    assert len(clients) == len(calls) == 1 and clients[0].is_closed
    assert cancelled == ([True] if stalled else [])
