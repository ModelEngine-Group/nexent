# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""LT-01/02: finite, redacted legacy task reads never mutate or infer ownership."""

import json
from dataclasses import replace
from unittest.mock import MagicMock, Mock

import pytest
from contracts.knowledge_maintenance import LEGACY_TASKS
from nexent.core.concurrency import RunCancellationScope
from nexent.storage.errors import (
    CapabilityUnsupported,
    InvalidInput,
    OperationCancelled,
    ScopeDenied,
    Unavailable,
)
from nexent.storage.models import Comparison, PageRequest, RecordQuery, StorageScope

from infrastructure.redis.legacy_tasks import LegacyTaskRecords
from test.backend.services.test_cleanse_jobs import context


@pytest.fixture
def store():
    backend, general = MagicMock(), MagicMock()
    for client in (backend, general):
        client.__enter__.return_value = client
        client.__exit__.side_effect = lambda *args, selected=client: selected.close()
    backend.get.return_value = json.dumps({'status': 'SUCCESS', 'result': {'index_name': 'old-kb',
        'file_id': 'b'*32, 'source': 'https://secret:password@host', 'chunks': ['private text']}}).encode()
    backend.scan.return_value = (0, [b'celery-task-meta-known'])
    general.exists.return_value = 0
    general.scan.return_value = (0, [])
    factory = Mock(side_effect=lambda url, **kw: backend if url.endswith('/0') else general)
    port = LegacyTaskRecords(StorageScope('management', 'tenant-a', 'operator', {LEGACY_TASKS}), 'old-kb',
        {'known'}, backend_url='redis://local/0', general_url='redis://local/1', client_factory=factory)
    return port, backend, general, factory


def test_selected_metadata_is_redacted_and_auxiliary_values_are_never_read(store):
    port, backend, general, _ = store
    row = port.get(LEGACY_TASKS, 'known', context=context())
    assert row['status'] == 'SUCCESS' and row['file_id'] == 'b'*32
    assert row['index_matches'] and row['tenant_matches'] is None
    assert len(row['revision']) == 64 and row['origin'] == 'pg_reference'
    assert all(value not in json.dumps(row) for value in ('secret', 'password', 'private text', 'source', 'chunks"'))
    backend.get.assert_called_once_with('celery-task-meta-known')
    general.get.assert_not_called()
    assert general.exists.call_count == 4 and general.scan.call_args.kwargs['match'] == 'dp:known:part:*'
    assert backend.close.call_count == general.close.call_count == 1


def test_known_missing_result_is_explicit_unknown_not_pending(store):
    port, backend, _, _ = store; backend.get.return_value = None
    row = port.get(LEGACY_TASKS, 'known', context=context())
    assert row['status'] == 'UNKNOWN' and row['result_present'] is False


def test_redis_only_discovery_selects_exact_index_without_exporting_other_tasks(store):
    port, backend, _, _ = store
    backend.scan.return_value = (0, [b'celery-task-meta-other', b'celery-task-meta-only'])
    backend.get.side_effect = [b'{"status":"SUCCESS","result":{"index_name":"other-kb"}}',
        b'{"status":"STARTED","result":{"index_name":"old-kb"}}']
    page = port.query(LEGACY_TASKS, RecordQuery(), PageRequest(limit=1), context=context())
    assert [row['task_id'] for row in page.items] == ['only']
    assert page.items[0]['origin'] == 'index_metadata' and page.next_cursor is None


def test_scan_cursor_is_private_ordered_and_bound_to_live_handle(store):
    port, backend, _, _ = store
    backend.scan.side_effect = [(7, [b'celery-task-meta-known']), (0, [])]
    first = port.query(LEGACY_TASKS, RecordQuery(), PageRequest(limit=1), context=context())
    assert first.next_cursor
    with pytest.raises(InvalidInput):
        port.query(LEGACY_TASKS, RecordQuery(), PageRequest(cursor='7'), context=context())
    assert port.query(LEGACY_TASKS, RecordQuery(), PageRequest(cursor=first.next_cursor), context=context()).next_cursor is None
    with pytest.raises(InvalidInput):
        port.query(LEGACY_TASKS, RecordQuery(), PageRequest(cursor=first.next_cursor), context=context())


@pytest.mark.parametrize('raw', [b'not-json', b'[]', b'{"status":"unexpected-secret"}', b'x'*(1024*1024+1)],
                         ids=['invalid-json', 'array', 'unknown-status', 'oversized'])
def test_corrupt_known_results_are_evidence_and_never_deserialized_with_celery(store, raw):
    port, backend, _, _ = store; backend.get.return_value = raw
    row = port.get(LEGACY_TASKS, 'known', context=context())
    assert row['status'] == 'UNKNOWN' and row['metadata_valid'] is False
    assert 'unexpected-secret' not in json.dumps(row)


@pytest.mark.parametrize('method', ['insert', 'update', 'delete', 'count', 'transaction'])
def test_mutation_and_unimplemented_count_fail_without_io(store, method):
    port, _, _, factory = store
    with pytest.raises(CapabilityUnsupported): getattr(port, method)(LEGACY_TASKS, context=context())
    factory.assert_not_called()


def test_arbitrary_task_get_dataset_and_predicates_are_denied_before_io(store):
    port, _, _, factory = store
    with pytest.raises(ScopeDenied): port.get(LEGACY_TASKS, 'foreign', context=context())
    with pytest.raises(ScopeDenied): port.get('other', 'known', context=context())
    with pytest.raises(CapabilityUnsupported):
        port.query(LEGACY_TASKS, RecordQuery(where=Comparison('task_id', 'eq', 'known')), PageRequest(), context=context())
    factory.assert_not_called()


def test_connection_uses_finite_no_retry_and_closes_on_failure(store):
    from redis.exceptions import ConnectionError
    port, backend, _, factory = store; backend.get.side_effect = ConnectionError('secret url')
    with pytest.raises(Unavailable): port.get(LEGACY_TASKS, 'known', context=context())
    assert backend.get.call_count == backend.close.call_count == 1
    kwargs = factory.call_args.kwargs
    assert kwargs['retry_on_timeout'] is False and kwargs['retry_on_error'] == [] and kwargs['socket_timeout'] <= 5


def test_cancellation_closes_client_once_before_read_returns(store):
    port, backend, _, _ = store
    scope = RunCancellationScope(); port._cancellation = scope
    def cancel(*args):
        scope.cancel()
        assert backend.close.call_count == 1
    backend.get.side_effect = cancel
    with pytest.raises(OperationCancelled):
        port.get(LEGACY_TASKS, 'known', context=replace(context(), cancelled=scope.stop_event))
    assert backend.close.call_count == 1


@pytest.mark.parametrize('response', [(0, [b'key']*10001), (-1, []), (0, ['not-bytes']), {'cursor': 0}])
def test_invalid_scan_response_is_not_a_successful_empty_inventory(store, response):
    port, backend, _, _ = store; backend.scan.return_value = response
    with pytest.raises(Unavailable):
        port.query(LEGACY_TASKS, RecordQuery(), PageRequest(), context=context())
    assert backend.scan.call_count == backend.close.call_count == 1


def test_closed_port_rejects_further_reads_without_opening_client(store):
    port, _, _, factory = store; port.close(); port.close()
    with pytest.raises(ScopeDenied): port.get(LEGACY_TASKS, 'known', context=context())
    factory.assert_not_called()
