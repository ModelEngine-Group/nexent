# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Execution facts cross the real stream buffer and commit boundary privately."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from test.backend.services import test_agent_model_attempt_persistence as fixtures


@pytest.mark.asyncio
@pytest.mark.parametrize('invocation', [None, 'child-invocation'])
async def test_execution_fact_gets_real_index_and_is_committed_without_public_sse(monkeypatch, invocation):
    service = fixtures.agent_execution
    batches = []
    fixtures._configure_stream_mocks(monkeypatch, batches)
    info = fixtures._agent_run_info()
    record_keys = []

    async def source(*_args, **_kwargs):
        history = info.observer.execution_history
        key = history.register('actual-agent-owner', {'OUTPUT': 'masked *** result'})
        history.get(key).summary = 'safe summary'
        record_keys.append(key)
        yield json.dumps({'type': 'execution_result', 'content': json.dumps({'execution_key': key}),
                          'invocation_id': invocation, 'tool_call_id': 'actual-call'})
        yield json.dumps({'type': 'final_answer', 'content': 'done'})

    monkeypatch.setattr(service, 'agent_run', source)
    chunks = [chunk async for chunk in service._stream_agent_chunks(
        fixtures._agent_request(), 'user1', 'tenant1', info, MagicMock(),
        channel=SimpleNamespace(publish=AsyncMock()),
    )]
    assert len(batches) == 1
    units = batches[0]['message_units']
    assert [unit['type'] for unit in units] == ['execution_result', 'final_answer']
    fact = units[0]
    assert fact['unit_index'] == 0 and fact['invocation_id'] == invocation
    assert fact['tool_call_id'] == 'actual-call'
    assert json.loads(fact['unit_content']) == {
        'content': '<OUTPUT>masked *** result</OUTPUT>', 'summary': 'safe summary',
    }
    assert '_execution_key' not in fact
    assert all('execution_result' not in chunk and record_keys[0] not in chunk for chunk in chunks)
    record = info.observer.execution_history.get(record_keys[0])
    assert record.reference == 'message:4242/unit-index:0' and record.persisted


@pytest.mark.asyncio
async def test_unregistered_execution_key_cannot_create_or_publish_an_execution_fact(monkeypatch):
    service = fixtures.agent_execution
    batches = []
    fixtures._configure_stream_mocks(monkeypatch, batches)

    async def source(*_args, **_kwargs):
        yield json.dumps({'type': 'execution_result', 'content': {'execution_key': 'untrusted-key'}})
        yield json.dumps({'type': 'final_answer', 'content': 'done'})

    monkeypatch.setattr(service, 'agent_run', source)
    chunks = [chunk async for chunk in service._stream_agent_chunks(
        fixtures._agent_request(), 'user1', 'tenant1', fixtures._agent_run_info(), MagicMock(),
        channel=SimpleNamespace(publish=AsyncMock()),
    )]
    assert len(batches) == 1
    assert [unit['type'] for unit in batches[0]['message_units']] == ['final_answer']
    assert all('untrusted-key' not in chunk for chunk in chunks)


@pytest.mark.asyncio
async def test_batch_rollback_keeps_execution_fact_readable_from_buffer(monkeypatch):
    service = fixtures.agent_execution
    fixtures._configure_stream_mocks(monkeypatch, [])
    monkeypatch.setattr(service, 'persist_assistant_run_batch', MagicMock(side_effect=RuntimeError('DB offline')))
    monkeypatch.setattr(service, 'update_message_status', MagicMock())
    info = fixtures._agent_run_info()
    keys = []

    async def source(*_args, **_kwargs):
        key = info.observer.execution_history.register('owner', {'OUTPUT': 'preserved buffer'})
        keys.append(key)
        yield json.dumps({'type': 'execution_result', 'content': {'execution_key': key}})
        yield json.dumps({'type': 'final_answer', 'content': 'done'})

    monkeypatch.setattr(service, 'agent_run', source)
    chunks = [chunk async for chunk in service._stream_agent_chunks(
        fixtures._agent_request(), 'user1', 'tenant1', info, MagicMock(),
        channel=SimpleNamespace(publish=AsyncMock()),
    )]
    record = info.observer.execution_history.get(keys[0])
    assert not record.persisted and info.attempt_outcome == 'failed'
    assert json.loads(info.observer.execution_history.read('owner', record.reference))['text'] == record.text
    assert any('"type": "error"' in chunk for chunk in chunks)
