from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.services.fa_memory_extractor import ExtractionResult, FaMemoryExtractor
from nexent.memory.models import MemoryLayer, MemoryType


def _make_extractor(model_client=None, memory_service=None):
    return FaMemoryExtractor(
        tenant_id='t-1',
        user_id='u-1',
        agent_id='a-1',
        conversation_id='c-1',
        memory_service=memory_service,
        model_client=model_client,
    )


@pytest.mark.case_id('UT-BE-AUTO-4E549AE901758D36')
@pytest.mark.stage('D1')
@pytest.mark.asyncio
async def test_fa_memory_extractor_full_contract(caplog):
    mem1 = SimpleNamespace(memory_id='mem-1', event='ADD')
    mem2 = SimpleNamespace(memory_id='mem-2', event='ADD')
    memory_service = AsyncMock()
    memory_service.store_memory.side_effect = [mem1, mem2]
    model_client = AsyncMock()
    model_client.chat.return_value = (
        '<memory-item>User prefers Python</memory-item>'
        '<memory-item>Project uses PostgreSQL</memory-item>'
    )
    extractor = _make_extractor(model_client=model_client, memory_service=memory_service)
    result = await extractor.extract_and_store('final answer', 'which db?')
    assert isinstance(result, ExtractionResult)
    assert result.reason == 'ok'
    assert [i['content'] for i in result.items] == ['User prefers Python', 'Project uses PostgreSQL']
    assert [i['memory_id'] for i in result.items] == ['mem-1', 'mem-2']
    assert memory_service.store_memory.call_count == 2
    for call, expected_content in zip(
        memory_service.store_memory.call_args_list,
        ['User prefers Python', 'Project uses PostgreSQL'],
    ):
        kw = call.kwargs
        assert kw['content'] == expected_content
        assert kw['tenant_id'] == 't-1'
        assert kw['user_id'] == 'u-1'
        assert kw['agent_id'] == 'a-1'
        assert kw['conversation_id'] == 'c-1'
        assert kw['layer'] == MemoryLayer.AGENT
        assert kw['memory_type'] == MemoryType.SHORT_TERM

    for empty in ('', '   '):
        mc = AsyncMock()
        ms = AsyncMock()
        ex = _make_extractor(model_client=mc, memory_service=ms)
        r = await ex.extract_and_store(empty)
        assert r.reason == 'empty_final_answer'
        assert r.items == []
        mc.chat.assert_not_awaited()
        ms.store_memory.assert_not_awaited()

    ms = AsyncMock()
    ex = _make_extractor(model_client=None, memory_service=ms)
    r = await ex.extract_and_store('some answer')
    assert r.reason == 'no_llm_configured'
    assert r.items == []
    ms.store_memory.assert_not_awaited()

    mc = AsyncMock()
    mc.chat.side_effect = RuntimeError('model call failed')
    ms = AsyncMock()
    ex = _make_extractor(model_client=mc, memory_service=ms)
    r = await ex.extract_and_store('some answer')
    assert r.reason == 'llm_error'
    assert r.items == []
    ms.store_memory.assert_not_awaited()

    mc = AsyncMock()
    mc.chat.return_value = '<no-memory/>'
    ms = AsyncMock()
    ex = _make_extractor(model_client=mc, memory_service=ms)
    r = await ex.extract_and_store('some answer')
    assert r.reason == 'no_items'
    assert r.items == []
    ms.store_memory.assert_not_awaited()

    prefix = 'P' * FaMemoryExtractor.MAX_INPUT_CHARS
    tail = 'TAIL_SHOULD_BE_CUT'
    mc = AsyncMock()
    mc.chat.return_value = '<memory-item>kept</memory-item>'
    ms = AsyncMock()
    ms.store_memory.return_value = SimpleNamespace(memory_id='mem-t', event='ADD')
    ex = _make_extractor(model_client=mc, memory_service=ms)
    await ex.extract_and_store(prefix + tail, 'query')
    user_content = mc.chat.await_args.args[0][1]['content']
    assert prefix in user_content
    assert tail not in user_content

    good = SimpleNamespace(memory_id='mem-good', event='ADD')
    ms = AsyncMock()
    ms.store_memory.side_effect = [RuntimeError('store failed'), good]
    mc = AsyncMock()
    mc.chat.return_value = '<memory-item>item one</memory-item><memory-item>item two</memory-item>'
    ex = _make_extractor(model_client=mc, memory_service=ms)
    with caplog.at_level(logging.WARNING, logger='fa_memory_extractor'):
        r = await ex.extract_and_store('answer')
    assert r.reason == 'ok'
    assert [i['content'] for i in r.items] == ['item two']
    assert r.items[0]['memory_id'] == 'mem-good'
    assert ms.store_memory.call_count == 2
    assert 'Failed to store memory item' in caplog.text

    ex = _make_extractor()
    messages = ex._build_messages('the answer', 'the query')
    assert [m['role'] for m in messages] == ['system', 'user']
    assert messages[0]['content']
    assert 'the answer' in messages[1]['content']
    assert 'the query' in messages[1]['content']

    assert FaMemoryExtractor._parse_items('<no-memory/>') == []
    assert FaMemoryExtractor._parse_items('<memory-item>a</memory-item><memory-item>b</memory-item>') == ['a', 'b']
    assert FaMemoryExtractor._parse_items('no tags here') == []

    caplog.clear()
    mc = AsyncMock()
    mc.chat.side_effect = RuntimeError('model call failed')
    ms = AsyncMock()
    ex = _make_extractor(model_client=mc, memory_service=ms)
    with caplog.at_level(logging.ERROR, logger='fa_memory_extractor'):
        r = await ex.extract_and_store('answer')
    assert r.reason == 'llm_error'
    assert any('LLM call failed during memory extraction' in rec.getMessage() for rec in caplog.records)
    secret_words = ('api_key', 'apikey', 'password', 'secret', 'token', 'access_key')
    for rec in caplog.records:
        if rec.name == 'fa_memory_extractor':
            assert not any(word in rec.getMessage().lower() for word in secret_words)
