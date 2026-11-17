# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""DELETE-PUBLIC-04: source-only preview cleanup keeps its bounded best-effort behavior."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from management.services.knowledge_base.deletion_coordinator import DeletionCoordinator
from nexent.storage.errors import NotFound, Unavailable
from nexent.storage.models import ObjectMetadata, ObjectRef, Revision

from test.backend.services.test_cleanse_jobs import context


@pytest.fixture
def preview(monkeypatch):
    from infrastructure import knowledge_deletion as module

    objects = Mock()
    key = 'preview/converted/knowledge_base/doc_test.pdf'
    monkeypatch.setattr('management.services.file.preview.build_preview_pdf_object_key', lambda _: key)
    calls = []

    @contextmanager
    def port(row, actor, selected, *, context):
        calls.append((row, actor, selected))
        yield objects

    monkeypatch.setattr(module, 'deletion_preview_objects', port)
    row = {'file_id': 'b' * 32, 'tenant_id': 'tenant', 'object_name': 'knowledge_base/doc.txt', 'bucket_name': 'bucket'}
    actor = SimpleNamespace(user_id='user', tenant_id='tenant')
    return objects, calls, key, row, actor


@pytest.mark.parametrize('version', ['version:one', 'etag:one'])
def test_cache_is_deleted_once_using_only_its_derived_key(preview, version):
    objects, calls, key, row, actor = preview
    ref = ObjectRef('files', key, Revision(version))
    objects.stat.return_value = ObjectMetadata(ref, 1, 'application/pdf', 'one', None)
    operation = context()
    DeletionCoordinator._cleanup_preview(row, actor, operation)
    assert calls == [(row, actor, key)]
    objects.stat.assert_called_once_with(ObjectRef('files', key), context=operation)
    objects.delete.assert_called_once_with(ref if version.startswith('version:') else ObjectRef('files', key), context=operation)


@pytest.mark.parametrize('error', [NotFound(), Unavailable()])
def test_missing_or_unavailable_cache_never_retries_or_changes_source_result(preview, error):
    objects, calls, _key, row, actor = preview
    objects.stat.side_effect = error
    DeletionCoordinator._cleanup_preview(row, actor, context())
    assert len(calls) == 1
    objects.stat.assert_called_once()
    objects.delete.assert_not_called()


def test_non_knowledge_source_does_not_open_preview_storage(preview):
    _, calls, _, row, actor = preview
    DeletionCoordinator._cleanup_preview({**row, 'object_name': 'uploads/file.txt'}, actor, context())
    assert calls == []
