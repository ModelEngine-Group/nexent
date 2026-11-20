# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""FILE-BODY-03 seals the exact read port and normalizes transport deadlines."""

from time import monotonic
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError, ReadTimeoutError
from nexent.storage.errors import DeadlineExceeded, ScopeDenied
from nexent.storage.models import ObjectRef, OperationContext


def test_exact_read_port_and_body_timeout_close_once(mocker):
    from infrastructure import file_reads

    raw = Mock()
    body = Mock()
    raw.get_object.return_value = {'Body': body}
    body.read.side_effect = ReadTimeoutError(endpoint_url='https://private.invalid')
    configured = mocker.patch.object(file_reads, '_configured_client', return_value=raw)
    mocker.patch.object(file_reads, '_configured_environment', return_value=SimpleNamespace(MINIO_DEFAULT_BUCKET='owned'))
    ctx = OperationContext('owned', monotonic()+30)
    with file_reads.file_read_ports('knowledge_base/a:colon', context=ctx) as store:
        assert store.scope.system and store.scope.actor_id == 'management.file.read'
        with pytest.raises(ScopeDenied):
            store.delete(ObjectRef('files', 'knowledge_base/a:colon'), context=ctx)
        with pytest.raises(DeadlineExceeded), store.open_read(ObjectRef('files', 'knowledge_base/a:colon'), context=ctx) as reader:
            reader.read(64*1024)
    assert 0 < configured.call_args.args[0] <= 5
    raw.get_object.assert_called_once_with(Bucket='owned', Key='knowledge_base/a:colon')
    body.close.assert_called_once()
    raw.close.assert_called_once()


@pytest.mark.parametrize(('name', 'bucket', 'key'), [
    ('attachments/a:colon', 'owned', 'attachments/a:colon'),
    ('s3://legacy/attachments/a:colon', 'legacy', 'attachments/a:colon'),
    ('/legacy/attachments/a:colon', 'legacy', 'attachments/a:colon'),
])
def test_attachment_size_requests_one_head_and_closes(mocker, name, bucket, key):
    from infrastructure import file_reads

    raw = Mock()
    raw.head_object.return_value = {'ContentLength': 123, 'ETag': 'revision'}
    configured = mocker.patch.object(file_reads, '_configured_client', return_value=raw)
    mocker.patch.object(file_reads, '_configured_environment', return_value=SimpleNamespace(MINIO_DEFAULT_BUCKET='owned'))

    assert file_reads.read_attachment_size(name) == 123
    assert 0 < configured.call_args.args[0] <= 5
    raw.head_object.assert_called_once_with(Bucket=bucket, Key=key)
    raw.get_object.assert_not_called()
    raw.close.assert_called_once()


@pytest.mark.parametrize('error', [
    ClientError({'Error': {'Code': '404'}}, 'HeadObject'),
    ReadTimeoutError(endpoint_url='https://private.invalid'),
])
def test_attachment_size_preserves_zero_without_another_request(mocker, error):
    from infrastructure import file_reads

    raw = Mock()
    raw.head_object.side_effect = error
    mocker.patch.object(file_reads, '_configured_client', return_value=raw)
    mocker.patch.object(file_reads, '_configured_environment', return_value=SimpleNamespace(MINIO_DEFAULT_BUCKET='owned'))

    assert file_reads.read_attachment_size('attachments/missing') == 0
    raw.head_object.assert_called_once_with(Bucket='owned', Key='attachments/missing')
    raw.get_object.assert_not_called()
    raw.close.assert_called_once()
