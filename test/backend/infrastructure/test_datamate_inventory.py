# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""HEALTH-SI-02/04 retains external provider pagination and closes on failures."""

from contextlib import contextmanager
from time import monotonic
from unittest.mock import Mock

import httpx
import pytest
from nexent.storage.errors import DeadlineExceeded
from nexent.storage.models import OperationContext

from infrastructure.vdb.datamate_inventory import datamate_collection_count


def response(data, status=200):
    return httpx.Response(status, json=data)


def factory(client):
    @contextmanager
    def create(**kwargs):
        try:
            assert 0 < kwargs['timeout'] <= 5
            assert kwargs['trust_env'] is False
            yield client
        finally:
            client.close()
    return create


def test_two_pages_keep_document_type_non_null_ids_and_duplicates():
    pages = [response({'data': {'totalPages': 2, 'content': [
        {'id': 0, 'type': 'DOCUMENT'}, {'id': None, 'type': 'DOCUMENT'}, {'id': 3, 'type': 'OTHER'}]}}),
        response({'data': {'content': [{'id': 0, 'type': 'DOCUMENT'}, {'id': 'two', 'type': 'DOCUMENT'}]}})]
    client = Mock(post=Mock(side_effect=pages))
    count = datamate_collection_count('https://owned.invalid/', context=OperationContext('owned', monotonic()+5),
                                     client_factory=factory(client))
    assert count == 3
    assert [c.kwargs['json'] for c in client.post.call_args_list] == [{'page': 1, 'size': 20}, {'page': 2, 'size': 20}]
    assert all(c.args == ('https://owned.invalid/api/knowledge-base/list',) for c in client.post.call_args_list)
    assert all(p.is_closed for p in pages)
    client.close.assert_called_once()


def test_failed_page_keeps_original_failure_prefix_and_does_not_continue():
    failed = response({'detail': 'owned refusal'}, 403)
    client = Mock(post=Mock(return_value=failed))
    with pytest.raises(RuntimeError, match='Failed to fetch DataMate knowledge bases: Failed to get knowledge base list'):
        datamate_collection_count('https://owned.invalid', context=OperationContext('owned', monotonic()+5),
                                 client_factory=factory(client))
    client.post.assert_called_once()
    client.close.assert_called_once()
    assert failed.is_closed


def test_cancel_between_pages_does_not_send_next_request():
    from threading import Event

    cancelled = Event()
    first = response({'data': {'totalPages': 2, 'content': []}})
    def post(*args, **kwargs):
        cancelled.set()
        return first
    client = Mock(post=Mock(side_effect=post))
    from nexent.storage.errors import OperationCancelled
    with pytest.raises(OperationCancelled):
        datamate_collection_count('https://owned.invalid',
            context=OperationContext('owned', monotonic()+5, cancelled=cancelled), client_factory=factory(client))
    client.post.assert_called_once()
    client.close.assert_called_once()
    assert first.is_closed


def test_expired_root_never_opens_http_client():
    create = Mock()
    with pytest.raises(DeadlineExceeded):
        datamate_collection_count('https://owned.invalid', context=OperationContext('owned', monotonic()-1), client_factory=create)
    create.assert_not_called()
