# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""The existing lifespan advances parent pages with a separate cursor and no restart."""

from contextlib import contextmanager
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from management.services.knowledge_base import ingestion_dispatch as dispatch
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import Page


@pytest.fixture
def discovery(monkeypatch):
    events = []
    records = SimpleNamespace(query=Mock(return_value=Page(({
        'knowledge_id': 2, 'index_name': 'private', 'tenant_id': 'target', 'user_id': 'admin',
        'owner_user_id': 'owner', 'purpose': 'tenant_deletion'},), 'base-next')))

    @contextmanager
    def ports(*, context):
        try:
            yield records
        finally:
            events.append('closed')

    async def blocking(name, fn, **kwargs):
        assert kwargs == {'lane': 'control-io', 'owner': 'management.knowledge_base'}
        return fn()

    async def advance(*args, **kwargs):
        assert events == ['closed']

    selected = SimpleNamespace(request_owner_cleanup=AsyncMock(side_effect=advance))
    monkeypatch.setattr(dispatch, 'base_dispatch_ports', ports)
    monkeypatch.setattr(dispatch, 'run_blocking', blocking)
    monkeypatch.setattr(dispatch, 'default_base_deletion_coordinator', Mock(return_value=selected))
    return SimpleNamespace(**locals())


async def test_parent_page_closes_storage_before_rpc_and_preserves_issuer(discovery):
    assert await dispatch.dispatch_bases_once(object(), stop=Event(), cursor='prior') == (1, 'base-next')
    assert discovery.events == ['closed']
    assert discovery.records.query.call_args.args[2].cursor == 'prior'
    args, kwargs = discovery.selected.request_owner_cleanup.call_args
    assert args[:2] == ('private', 'owner')
    assert args[2].user_id == 'admin' and args[2].tenant_id == 'target'
    assert kwargs['purpose'] == 'tenant_deletion'


async def test_stopped_parent_discovery_has_no_storage_or_rpc(discovery):
    stop = Event()
    stop.set()
    assert await dispatch.dispatch_bases_once(object(), stop=stop, cursor='prior') == (0, 'prior')
    discovery.records.query.assert_not_called()


async def test_scope_error_is_not_retried_or_hidden(discovery):
    discovery.selected.request_owner_cleanup.side_effect = ScopeDenied()
    with pytest.raises(ScopeDenied):
        await dispatch.dispatch_bases_once(object(), stop=Event())
    discovery.selected.request_owner_cleanup.assert_awaited_once()


async def test_single_lifespan_loop_keeps_both_cursors_without_starvation(monkeypatch):
    stop, files, bases = Event(), [], []

    async def file_page(root, *, stop, cursor):
        files.append(cursor)
        return 100, 'file-next'

    async def base_page(root, *, stop, cursor):
        bases.append(cursor)
        if len(bases) == 2:
            stop.set()
        return 100, 'base-next'

    monkeypatch.setattr(dispatch, 'dispatch_once', file_page)
    monkeypatch.setattr(dispatch, 'dispatch_bases_once', base_page)
    await dispatch.serve(object(), stop=stop, poll_seconds=0.01)
    assert files == [None, 'file-next'] and bases == [None, 'base-next']
