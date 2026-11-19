# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""PREVIEW-PREP-01 preserves opaque keys only in finite trusted bindings."""

from time import monotonic
from unittest.mock import Mock

import pytest
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import ObjectRef, OperationContext, StorageScope

from infrastructure.object_storage.port import ObjectBinding


@pytest.mark.parametrize('key', ['attachments/user/doc.pdf', 'knowledge_base/a:colon.pdf', 'knowledge_base/a\\b.pdf'])
def test_exact_metadata_uses_original_key_without_path_rewriting(key):
    from infrastructure.object_storage.exact import ExactKeyObjectStore

    client = Mock()
    client.head_object.return_value = {'ContentLength': 3, 'ETag': 'owned'}
    factory = Mock(return_value=client)
    store = ExactKeyObjectStore(StorageScope('management', None, 'office-preview', {'files'}, system=True),
        ObjectBinding('files', 'owned', '', {'management'}, allow_system=True, exact_keys={key}), factory)
    ctx = OperationContext('owned', monotonic()+5)
    assert store.stat(ObjectRef('files', key), context=ctx).size == 3
    client.head_object.assert_called_once_with(Bucket='owned', Key=key)
    client.close.assert_called_once()
    with pytest.raises(ScopeDenied):
        store.stat(ObjectRef('files', 'knowledge_base/other'), context=ctx)
    assert factory.call_count == 1
    with pytest.raises(ScopeDenied):
        store.delete(ObjectRef('files', key), context=ctx)
    assert factory.call_count == 1


def test_preview_composition_never_grants_source_write_or_another_key(mocker):
    from types import SimpleNamespace

    from infrastructure import preview_objects

    mocker.patch.object(preview_objects, '_configured_environment', return_value=SimpleNamespace(MINIO_DEFAULT_BUCKET='owned'))
    client = mocker.patch.object(preview_objects, '_configured_client')
    ctx = OperationContext('owned', monotonic()+5)
    with preview_objects.preview_object_ports('knowledge_base/source.pdf', context=ctx) as store:
        assert store.scope.system and store.scope.actor_id == 'office-preview' and store.scope.tenant_id is None
        with pytest.raises(ScopeDenied):
            store.delete(ObjectRef('files', 'knowledge_base/source.pdf'), context=ctx)
        with pytest.raises(ScopeDenied):
            store.stat(ObjectRef('files', 'knowledge_base/other.pdf'), context=ctx)
    with pytest.raises(ScopeDenied), preview_objects.preview_object_ports('knowledge_base/source.pdf', writable=True, context=ctx):
        pass
    client.assert_not_called()


def test_exact_adapter_cannot_be_composed_as_an_unbounded_store():
    from infrastructure.object_storage.exact import ExactKeyObjectStore

    client = Mock()
    with pytest.raises(ScopeDenied):
        ExactKeyObjectStore(StorageScope('management', 'tenant', 'actual', {'files'}),
            ObjectBinding('files', 'owned', '', {'management'}), client)
    client.assert_not_called()
