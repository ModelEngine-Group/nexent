# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""PREVIEW-PREP-03 proves managed preparation, lock deadlines and cancellation."""

import asyncio
from time import monotonic
from unittest.mock import AsyncMock, Mock

import pytest
from nexent.storage.errors import DeadlineExceeded
from nexent.storage.models import OperationContext


@pytest.fixture
def preview(mocker):
    from management.services.file import preview

    store = Mock()
    store.size.return_value = 3
    store.cache_valid.return_value = True
    mocker.patch.object(preview, 'PreviewObjects', return_value=store)
    captured = []
    async def run(name, action, *args, **kwargs):
        assert kwargs['lane'] == 'control-io' and kwargs['owner'] == 'management.file.preview'
        captured.append(kwargs['context'])
        return action(*args, context=kwargs['context'])
    mocker.patch.object(preview, 'run_blocking', side_effect=run)
    preview._conversion_locks.clear()
    return preview, store, captured


@pytest.mark.asyncio
async def test_direct_preview_uses_si_and_cancels_root_after_completion(preview):
    module, store, captured = preview
    assert await module.resolve_preview_file('knowledge_base/source.pdf') == ('knowledge_base/source.pdf', 'application/pdf', 3)
    store.size.assert_called_once()
    assert captured[0].cancelled.is_set()
    store.cache_valid.assert_not_called()


@pytest.mark.asyncio
async def test_office_cache_hit_keeps_stable_key_and_same_root(preview):
    module, store, captured = preview
    store.size.side_effect = [4, 5]
    result = await module.resolve_preview_file('knowledge_base/source.docx')
    assert result == (module.build_preview_pdf_object_key('knowledge_base/source.docx'), 'application/pdf', 5)
    assert all(ctx is captured[0] for ctx in captured)
    assert captured[0].cancelled.is_set()


@pytest.mark.asyncio
async def test_existing_cache_miss_conversion_uses_remaining_root(preview, mocker):
    module, store, captured = preview
    store.cache_valid.return_value = False
    convert = mocker.patch.object(module, 'convert_preview', new_callable=AsyncMock)
    await module.resolve_preview_file('knowledge_base/source.docx')
    convert.assert_awaited_once()
    assert 0 < convert.await_args.kwargs['timeout'] <= 120
    assert all(ctx is captured[0] for ctx in captured)


@pytest.mark.asyncio
async def test_conversion_deadline_reaches_one_root_warning(preview, mocker, caplog):
    module, store, captured = preview
    store.cache_valid.return_value = False
    mocker.patch.object(module, 'convert_preview', new_callable=AsyncMock, side_effect=TimeoutError('owned timeout'))
    with pytest.raises(DeadlineExceeded):
        await module.resolve_preview_file('knowledge_base/source.docx')
    assert captured[0].cancelled.is_set()
    assert len([r for r in caplog.records if r.levelname == 'WARNING' and 'file_preview_timeout' in r.message]) == 1
    assert not [r for r in caplog.records if r.levelname == 'ERROR']


@pytest.mark.asyncio
async def test_waiting_for_existing_conversion_expires_without_starting_another(preview, mocker, caplog):
    module, store, captured = preview
    store.cache_valid.return_value = False
    lock = asyncio.Lock()
    await lock.acquire()
    module._conversion_locks['knowledge_base/source.docx'] = lock
    original = OperationContext
    mocker.patch.object(module, 'OperationContext', side_effect=lambda ident, deadline, cancelled:
        original(ident, monotonic()+.02, cancelled=cancelled))
    convert = mocker.patch.object(module, 'convert_preview', new_callable=AsyncMock)
    try:
        with pytest.raises(DeadlineExceeded):
            await module.resolve_preview_file('knowledge_base/source.docx')
    finally:
        lock.release()
    convert.assert_not_awaited()
    assert captured[0].cancelled.is_set()
    assert len([r for r in caplog.records if r.levelname == 'WARNING' and 'file_preview_timeout' in r.message]) == 1
    assert not [r for r in caplog.records if r.levelname == 'ERROR']
