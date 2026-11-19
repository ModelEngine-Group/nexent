# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""PREVIEW-PREP-01/02 keeps existing source/cache decisions through scoped SI."""

from contextlib import contextmanager
from time import monotonic
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from contracts.errors.exceptions import NotFoundException
from nexent.storage.errors import (
    DeadlineExceeded,
    NotFound,
    OutcomeUnknown,
    Unavailable,
)
from nexent.storage.models import ByteRange


@pytest.fixture
def preview():
    from management.services.file.preview_storage import PreviewObjects

    store, opened, closed = MagicMock(), [], []
    store.stat.return_value = SimpleNamespace(size=123)
    @contextmanager
    def ports(name, *, writable=False, context):
        opened.append((name, writable))
        try:
            yield store
        finally:
            closed.append(name)
    return SimpleNamespace(service=PreviewObjects(ports=ports), store=store, opened=opened, closed=closed)


def context():
    from nexent.storage.models import OperationContext
    return OperationContext('owned', monotonic()+5)


def test_source_stat_is_one_readonly_request(preview):
    s = preview
    assert s.service.size('knowledge_base/source.pdf', context=context()) == 123
    assert s.opened == [('knowledge_base/source.pdf', False)] and s.closed == ['knowledge_base/source.pdf']
    s.store.stat.assert_called_once()
    s.store.delete.assert_not_called()


@pytest.mark.parametrize('error', [NotFound(), Unavailable()])
def test_source_retains_existing_missing_or_unavailable_result(preview, error):
    preview.store.stat.side_effect = error
    with pytest.raises(NotFoundException):
        preview.service.size('knowledge_base/missing.pdf', context=context())


def test_deadline_is_not_reported_as_missing(preview):
    preview.store.stat.side_effect = DeadlineExceeded()
    with pytest.raises(DeadlineExceeded):
        preview.service.size('knowledge_base/source.pdf', context=context())


def test_cache_probe_uses_first_byte_range_and_closes(preview):
    s = preview
    assert s.service.cache_valid('preview/converted/current.pdf', context=context())
    assert s.opened == [('preview/converted/current.pdf', True)] and s.closed == ['preview/converted/current.pdf']
    assert s.store.open_read.call_args.kwargs['byte_range'] == ByteRange(0, 1)
    s.store.open_read.return_value.__exit__.assert_called_once()
    s.store.delete.assert_not_called()


def test_missing_cache_does_not_probe_or_delete(preview):
    s = preview
    s.store.stat.side_effect = NotFound()
    assert not s.service.cache_valid('preview/converted/current.pdf', context=context())
    s.store.open_read.assert_not_called()
    s.store.delete.assert_not_called()


def test_probe_close_failure_keeps_valid_cache_without_deletion(preview, caplog):
    s = preview
    s.store.open_read.return_value.__exit__.side_effect = RuntimeError('owned close failure')
    assert s.service.cache_valid('preview/converted/current.pdf', context=context())
    s.store.delete.assert_not_called()
    assert any('preview_cache_probe_close_failed' in r.message for r in caplog.records)


@pytest.mark.parametrize('delete_error', [None, OutcomeUnknown()])
def test_corrupt_cache_only_attempts_current_key_once(preview, delete_error):
    s = preview
    s.store.open_read.side_effect = Unavailable()
    s.store.delete.side_effect = delete_error
    assert not s.service.cache_valid('preview/converted/current.pdf', context=context())
    s.store.delete.assert_called_once()
    assert s.store.delete.call_args.args[0].key == 'preview/converted/current.pdf'
