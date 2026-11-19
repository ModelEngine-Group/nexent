# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-DOC-IMAGE-APPEND-01/02 pin original image bytes without transport copies."""

import hashlib
from io import BytesIO
from time import monotonic
from unittest.mock import Mock

import pytest
from contracts.agentos_knowledge import ObjectReference
from management.services.knowledge_base import document_images
from nexent.storage.errors import InvalidInput, NotFound
from nexent.storage.models import ObjectMetadata, ObjectRef, OperationContext, Revision

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.file_processing import image_sources


@pytest.fixture
def image(mocker):
    raw = b'\x89PNG\r\n\x1a\noriginal bytes'
    context = OperationContext('image-reference-ut', monotonic() + 10)
    actor = ServicePrincipal('operator', 'tenant-a')
    ref = ObjectReference(space='files', key='images_in_attachments/a.png', version='etag:one',
                          sha256=hashlib.sha256(raw).hexdigest())
    store = Mock()
    store.stat.return_value = ObjectMetadata(ObjectRef(ref.space, ref.key, Revision(ref.version)), len(raw), 'image/png')
    streams = []

    def open_read(*args, **kwargs):
        stream = BytesIO(raw)
        streams.append(stream)
        return stream

    store.open_read.side_effect = open_read
    bind = mocker.patch.object(image_sources, 'bind_source_objects', return_value=store)
    mocker.patch.object(image_sources.environment, 'MINIO_DEFAULT_BUCKET', 'files')
    return actor, context, ref, raw, store, streams, bind


def test_pin_and_fixed_read_preserve_original_bytes_and_close_owned_handles(image):
    actor, context, ref, raw, store, streams, bind = image
    assert image_sources.pin_object_image('s3://files/' + ref.key, user_id=actor.user_id,
                                          tenant_id=actor.tenant_id, context=context) == ref
    assert image_sources.read_pinned_object_image(ref, user_id=actor.user_id,
                                                  tenant_id=actor.tenant_id, context=context) == raw
    assert all(stream.closed for stream in streams) and store.close.call_count == 2
    assert all(call.args == (actor.tenant_id, actor.user_id, ref.key, 'files') for call in bind.call_args_list)
    assert [call.kwargs['role'] for call in bind.call_args_list] == ['management', 'runtime']
    assert all(call.kwargs['writable'] is False for call in bind.call_args_list)
    assert all(call.args[0] == ObjectRef('files', ref.key, Revision(ref.version))
               for call in store.open_read.call_args_list)


@pytest.mark.parametrize('failure', ['hash', 'version', 'read'])
def test_fixed_image_failure_never_returns_bytes_and_closes(image, failure):
    actor, context, ref, raw, store, streams, _ = image
    if failure == 'hash':
        ref = ref.model_copy(update={'sha256': 'f' * 64})
    elif failure == 'version':
        store.stat.return_value = ObjectMetadata(ObjectRef('files', ref.key, Revision('other')), len(raw), 'image/png')
    else:
        store.open_read.side_effect = OSError('read failed')
    with pytest.raises((InvalidInput, OSError)):
        image_sources.read_pinned_object_image(ref, user_id=actor.user_id, tenant_id=actor.tenant_id, context=context)
    assert all(stream.closed for stream in streams) and store.close.call_count == 1


@pytest.mark.parametrize('failure', ['declared_size', 'declared_hash'])
def test_pin_does_not_publish_an_inconsistent_snapshot(image, failure):
    actor, context, ref, raw, store, streams, _ = image
    store.stat.return_value = ObjectMetadata(ObjectRef('files', ref.key, Revision(ref.version)),
        len(raw) - 1 if failure == 'declared_size' else len(raw), 'image/png',
        sha256='f' * 64 if failure == 'declared_hash' else None)
    with pytest.raises(InvalidInput):
        image_sources.pin_object_image('s3://files/' + ref.key, user_id=actor.user_id,
                                        tenant_id=actor.tenant_id, context=context)
    assert all(stream.closed for stream in streams) and store.close.call_count == 1


@pytest.mark.parametrize('url', ['s3://files/images_in_attachments/a.png', '/files/images_in_attachments/a.png',
                                  'images_in_attachments/a.png'])
def test_management_pin_reuses_original_address_and_identity_policy(image, mocker, url):
    actor, context, ref, _, _, _, _ = image
    mocker.patch.object(document_images.environment, 'MINIO_DEFAULT_BUCKET', 'files')
    pin = mocker.patch.object(document_images, 'pin_object_image', return_value=ref)
    assert document_images.pin_document_image(url, actor, context=context) == ref
    pin.assert_called_once_with('s3://files/' + ref.key, user_id=actor.user_id,
                                tenant_id=actor.tenant_id, context=context)


def test_management_pin_rejects_foreign_attachment_before_object_io(image, mocker):
    actor, context, _, _, _, _, _ = image
    pin = mocker.patch.object(document_images, 'pin_object_image', create=True)
    with pytest.raises(PermissionError):
        document_images.pin_document_image('attachments/other/private.png', actor, context=context)
    pin.assert_not_called()


def test_management_pin_keeps_original_missing_file_failure(image, mocker):
    actor, context, _, _, _, _, _ = image
    mocker.patch.object(document_images.environment, 'MINIO_DEFAULT_BUCKET', 'files')
    pin = mocker.patch.object(document_images, 'pin_object_image', side_effect=NotFound())
    with pytest.raises(FileNotFoundError):
        document_images.pin_document_image('images_in_attachments/a.png', actor, context=context)
    assert pin.call_count == 1
