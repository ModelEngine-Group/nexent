from __future__ import annotations

import logging

import pytest

from consts.error_code import ErrorCode
from consts.exceptions import AppException
from management.services.knowledge_base import management as kb_management
from management.services.knowledge_base.management import (
    KNOWLEDGE_BASE_DELETE_BLOCKING_STATUSES,
    KnowledgeBaseManagementService,
)

INDEX_NAME = 'kb-delete-guard-test-index'

BLOCKING_STATUSES = ['UPLOADING', 'UPLOADED', 'PROCESSING', 'FORWARDING']


def _row(*, status, file_id=None, original_filename=None, object_name=None):
    return {
        'file_id': file_id,
        'original_filename': original_filename,
        'object_name': object_name,
        'status': status,
    }


class _Recorder:
    def __init__(self, rows):
        self.rows = list(rows)
        self.calls = []

    def __call__(self, *, index_name=None, tenant_id=None, include_hidden=False):
        self.calls.append({
            'index_name': index_name,
            'tenant_id': tenant_id,
            'include_hidden': include_hidden,
        })
        return self.rows


@pytest.mark.case_id('UT-BE-AUTO-BDBC2EA00EAF645E')
@pytest.mark.stage('D1')
def test_knowledge_base_delete_guard(monkeypatch, caplog):
    assert KNOWLEDGE_BASE_DELETE_BLOCKING_STATUSES == frozenset(BLOCKING_STATUSES)

    for status in BLOCKING_STATUSES:
        recorder = _Recorder([
            _row(status=status, file_id='file-1', original_filename=status.lower() + '.txt')
        ])
        monkeypatch.setattr(kb_management, 'list_file_records', recorder)
        with pytest.raises(AppException) as excinfo:
            KnowledgeBaseManagementService._assert_knowledge_base_delete_allowed(INDEX_NAME)
        assert excinfo.value.error_code == ErrorCode.KNOWLEDGE_DELETE_BLOCKED
        details = excinfo.value.details
        assert details['index_name'] == INDEX_NAME
        blocking_files = details['blocking_files']
        assert len(blocking_files) == 1
        assert set(blocking_files[0].keys()) == {'file_id', 'file_name', 'status'}
        assert blocking_files[0]['file_id'] == 'file-1'
        assert blocking_files[0]['file_name'] == status.lower() + '.txt'
        assert blocking_files[0]['status'] == status
        assert len(recorder.calls) == 1
        assert recorder.calls[0]['index_name'] == INDEX_NAME
        assert recorder.calls[0]['include_hidden'] is True

    mixed_rows = [
        _row(status='UPLOADING', file_id='b1', original_filename='uploading.txt'),
        _row(status='DELETE_REQUESTED', file_id='h1', original_filename='hidden.txt'),
        _row(status='DELETED', file_id='h2', original_filename='deleted.txt'),
        _row(status='COMPLETED', file_id='c1', original_filename='completed.txt'),
        _row(status='FAILED', file_id='f1', original_filename='failed.txt'),
    ]
    monkeypatch.setattr(kb_management, 'list_file_records', _Recorder(mixed_rows))
    with pytest.raises(AppException) as excinfo:
        KnowledgeBaseManagementService._assert_knowledge_base_delete_allowed(INDEX_NAME)
    assert excinfo.value.error_code == ErrorCode.KNOWLEDGE_DELETE_BLOCKED
    assert [bf['file_id'] for bf in excinfo.value.details['blocking_files']] == ['b1']

    file_name_cases = [
        ({'original_filename': 'orig.txt', 'object_name': 'obj.bin', 'file_id': 'fid'}, 'orig.txt'),
        ({'original_filename': None, 'object_name': 'obj.bin', 'file_id': 'fid'}, 'obj.bin'),
        ({'original_filename': '', 'object_name': 'obj.bin', 'file_id': 'fid'}, 'obj.bin'),
        ({'original_filename': None, 'object_name': None, 'file_id': 'fid'}, 'fid'),
        ({'original_filename': None, 'object_name': None, 'file_id': None}, 'unknown'),
    ]
    for fields, expected_name in file_name_cases:
        monkeypatch.setattr(
            kb_management,
            'list_file_records',
            _Recorder([_row(status='FORWARDING', **fields)]),
        )
        with pytest.raises(AppException) as excinfo:
            KnowledgeBaseManagementService._assert_knowledge_base_delete_allowed(INDEX_NAME)
        blocking_files = excinfo.value.details['blocking_files']
        assert len(blocking_files) == 1
        assert blocking_files[0]['file_name'] == expected_name

    non_blocking_batches = [
        [_row(status='DELETE_REQUESTED', file_id='d1')],
        [_row(status='DELETED', file_id='d2')],
        [],
    ]
    for batch in non_blocking_batches:
        monkeypatch.setattr(kb_management, 'list_file_records', _Recorder(batch))
        result = KnowledgeBaseManagementService._assert_knowledge_base_delete_allowed(INDEX_NAME)
        assert result == batch

    def _explode(*, index_name=None, tenant_id=None, include_hidden=False):
        raise RuntimeError('lifecycle-read-boom')

    monkeypatch.setattr(kb_management, 'list_file_records', _explode)
    with pytest.raises(AppException) as excinfo:
        KnowledgeBaseManagementService._assert_knowledge_base_delete_allowed(INDEX_NAME)
    assert excinfo.value.error_code == ErrorCode.SYSTEM_DATABASE_ERROR
    assert excinfo.value.details['operation'] == 'knowledge_base_delete_guard'
    assert excinfo.value.details['index_name'] == INDEX_NAME

    secret_filename = 'api_key=sk-1234567890abcdef'
    secret_file_id = 'password=super-secret-42'
    caplog.clear()
    monkeypatch.setattr(
        kb_management,
        'list_file_records',
        _Recorder([_row(status='UPLOADING', file_id=secret_file_id, original_filename=secret_filename)]),
    )
    with caplog.at_level(logging.INFO, logger='vectordatabase_service'):
        with pytest.raises(AppException):
            KnowledgeBaseManagementService._assert_knowledge_base_delete_allowed(INDEX_NAME)
    assert 'sk-1234567890abcdef' not in caplog.text
    assert 'super-secret-42' not in caplog.text
    assert 'api_key' not in caplog.text
    assert 'password' not in caplog.text
