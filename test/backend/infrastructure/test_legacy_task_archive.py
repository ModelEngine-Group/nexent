# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Private maintenance exports retain original bytes without deserialization or mutations."""

import base64
import hashlib
import json

import pytest
from contracts.knowledge_maintenance import LEGACY_TASKS
from nexent.storage.errors import CapabilityUnsupported, InvalidInput, ScopeDenied
from nexent.storage.models import PageRequest, RecordQuery

from test.backend.infrastructure.test_legacy_task_records import (
    store as store,  # noqa: PLC0414
)
from test.backend.services.test_cleanse_jobs import context


def archive(port):
    return port.get(LEGACY_TASKS, 'known', fields=('archive',), context=context())


def test_archive_preserves_result_and_binary_auxiliary_values_without_writes(store):
    port, backend, general, _ = store
    raw = backend.get.return_value
    general.scan.return_value = (0, [b'dp:known:part:0:chunks'])
    general.dump.side_effect = lambda key: b'\x00original-error\xff' if key == 'error:reason:known' else b'\x0alist-data'
    general.pttl.return_value = 5000
    row = archive(port)
    values = {item['key']: item for item in row['archive']}
    result = values['celery-task-meta-known']
    assert result['encoding'] == 'raw' and base64.b64decode(result['value_base64']) == raw
    assert result['sha256'] == hashlib.sha256(raw).hexdigest() == row['revision']
    error = values['error:reason:known']
    assert error['encoding'] == 'redis-dump' and base64.b64decode(error['value_base64']) == b'\x00original-error\xff'
    assert error['ttl_ms'] == 5000 and 'dp:known:part:0:chunks' in values
    for client in (backend, general):
        for method in ('set', 'delete', 'expire', 'persist', 'restore', 'eval'):
            getattr(client, method).assert_not_called()


def test_absent_values_are_explicit_and_not_empty_payloads(store):
    port, backend, general, _ = store
    backend.get.return_value = None
    general.dump.return_value = None
    general.pttl.return_value = -2
    row = archive(port)
    assert row['result_present'] is False
    assert all(item['value_base64'] is None and item['sha256'] is None for item in row['archive'])


@pytest.mark.parametrize('result', [{'index_name': 'other'}, {'index_name': 'old-kb', 'tenant_id': 'foreign'}])
def test_explicit_metadata_conflict_prevents_raw_export(store, result):
    port, backend, general, _ = store
    backend.get.return_value = json.dumps({'status': 'SUCCESS', 'result': result}).encode()
    with pytest.raises(ScopeDenied): archive(port)
    general.dump.assert_not_called()


def test_large_valid_foreign_metadata_still_prevents_raw_export(store):
    port, backend, general, _ = store
    backend.get.return_value = json.dumps({'status': 'SUCCESS', 'result': {
        'index_name': 'foreign', 'error': 'x' * (1024 * 1024)}}).encode()
    with pytest.raises(ScopeDenied): archive(port)
    general.dump.assert_not_called()


def test_oversized_result_is_rejected_without_truncation(store):
    port, backend, general, _ = store
    backend.get.return_value = b'x' * (16 * 1024 * 1024 + 1)
    with pytest.raises(InvalidInput): archive(port)
    general.dump.assert_not_called()


def test_non_archive_field_and_foreign_task_are_denied_before_io(store):
    port, _, _, factory = store
    with pytest.raises(ScopeDenied): port.get(LEGACY_TASKS, 'foreign', fields=('archive',), context=context())
    with pytest.raises(CapabilityUnsupported): port.get(LEGACY_TASKS, 'known', fields=('password',), context=context())
    factory.assert_not_called()


def test_query_exports_only_selected_index_and_keeps_normal_scan_redacted(store):
    port, _, general, _ = store
    general.dump.return_value = None
    normal = port.get(LEGACY_TASKS, 'known', context=context())
    assert 'archive' not in normal and 'private text' not in json.dumps(normal)
    page = port.query(LEGACY_TASKS, RecordQuery(fields=('archive',)), PageRequest(), context=context())
    assert page.items[0]['archive'][0]['encoding'] == 'raw'


@pytest.mark.parametrize('key', [b'dp:foreign:part:0', b'dp:known:part:../../foreign'])
def test_scanned_part_must_stay_within_the_exact_task_namespace(store, key):
    port, _, general, _ = store
    general.scan.return_value = (0, [key])
    with pytest.raises(ScopeDenied): archive(port)
    general.dump.assert_not_called()


def test_corrupt_pg_linked_result_is_preserved_without_interpreting_it(store):
    port, backend, general, _ = store
    backend.get.return_value = b'\x80opaque-pickle\xff'
    general.dump.return_value = None
    row = archive(port)
    assert row['status'] == 'UNKNOWN' and not row['metadata_valid']
    assert base64.b64decode(row['archive'][0]['value_base64']) == backend.get.return_value


def test_oversized_auxiliary_value_is_rejected_without_mutation(store):
    port, _, general, _ = store
    general.dump.return_value = b'x' * (16 * 1024 * 1024 + 1)
    with pytest.raises(InvalidInput): archive(port)
    general.delete.assert_not_called()


def test_per_task_limit_rejects_large_combined_values_without_truncation(store):
    port, _, general, _ = store
    general.dump.return_value = b'x' * (16 * 1024 * 1024)
    with pytest.raises(InvalidInput): archive(port)
    assert general.dump.call_count == 4
    general.delete.assert_not_called()


def test_archive_closes_once_when_auxiliary_read_is_cancelled(store):
    from dataclasses import replace

    from nexent.core.concurrency import RunCancellationScope
    from nexent.storage.errors import OperationCancelled

    port, backend, general, _ = store
    scope = RunCancellationScope()
    port._cancellation = scope
    def cancel(key):
        scope.cancel()
        return b'old value'
    general.dump.side_effect = cancel
    with pytest.raises(OperationCancelled):
        port.get(LEGACY_TASKS, 'known', fields=('archive',), context=replace(context(), cancelled=scope.stop_event))
    assert general.close.call_count == backend.close.call_count == 1
