# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""SOURCE-OBJECT-04 deletes one exact opaque S3 key without URL normalization or replay."""

from time import monotonic
from unittest.mock import Mock

import pytest
from nexent.storage.errors import (
    CapabilityUnsupported,
    OutcomeUnknown,
    ScopeDenied,
    Unavailable,
)
from nexent.storage.models import ObjectRef, OperationContext, Revision, StorageScope

from infrastructure.object_storage.port import ObjectBinding


def objects(key):
    from infrastructure.object_storage.deletion import ExactObjectDeletionStore

    client = Mock()
    client.delete_objects.return_value = {'Deleted': [{'Key': key}]}
    factory = Mock(return_value=client)
    scope = StorageScope('management', 'tenant', 'actual', {'files'})
    binding = ObjectBinding('files', 'owned', '', {'management'}, writable=True, exact_keys={key})
    return ExactObjectDeletionStore(scope, binding, factory), client, factory, OperationContext('owned', monotonic()+5)


@pytest.mark.parametrize('key', ['knowledge_base/source', 'knowledge_base/name:colon', 'knowledge_base/a\\b',
    'knowledge_base/a//b', 'knowledge_base/a/../b'])
def test_literal_exact_key_is_one_request_body_not_a_url_path(key):
    store, client, factory, context = objects(key)
    assert store.delete(ObjectRef('files', key), context=context).deleted
    client.delete_objects.assert_called_once_with(Bucket='owned', Delete={'Objects': [{'Key': key}], 'Quiet': False})
    client.delete_object.assert_not_called()
    assert factory.call_count == 1
    client.close.assert_called_once()


def test_another_key_and_conditions_do_not_open_provider():
    store, _, factory, context = objects('one')
    with pytest.raises(ScopeDenied):
        store.delete(ObjectRef('files', 'other'), context=context)
    with pytest.raises(CapabilityUnsupported):
        store.delete(ObjectRef('files', 'one'), expected=Revision('etag:old'), context=context)
    factory.assert_not_called()


def test_delete_supplies_md5_of_serialized_xml_on_owned_client():
    store, client, _, context = objects('one')
    store.delete(ObjectRef('files', 'one'), context=context)
    registration = client.meta.events.register.call_args
    assert registration.args[0] == 'before-call.s3.DeleteObjects'
    params = {'body': b'abc', 'headers': {}}
    registration.args[1](params=params)
    assert params['headers'] == {'Content-MD5': 'kAFQmDzST7DWlj99KOF/cg=='}
    client.delete_objects.assert_called_once()
    client.close.assert_called_once()


@pytest.mark.parametrize(('response', 'error'), [({'Errors': [{'Key': 'one', 'Code': 'AccessDenied'}]}, ScopeDenied),
    ({'Errors': [{'Key': 'one', 'Code': 'InternalError'}]}, Unavailable), ({}, OutcomeUnknown),
    ({'Deleted': [{'Key': 'other'}]}, OutcomeUnknown), ({'Errors': ['malformed']}, OutcomeUnknown)])
def test_only_exact_deleted_acknowledgement_confirms_success(response, error):
    store, client, factory, context = objects('one')
    client.delete_objects.return_value = response
    with pytest.raises(error):
        store.delete(ObjectRef('files', 'one'), context=context)
    assert factory.call_count == client.delete_objects.call_count == 1
    client.delete_object.assert_not_called()
    client.close.assert_called_once()
