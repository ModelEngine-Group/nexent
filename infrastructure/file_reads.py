# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""One exact read-only object; transport deadlines never expose vendor details."""

import logging
from contextlib import contextmanager
from time import monotonic
from uuid import uuid4

from botocore.exceptions import ConnectTimeoutError, ReadTimeoutError
from nexent.storage.errors import DeadlineExceeded, NotFound, StorageError
from nexent.storage.models import ObjectRef, OperationContext, StorageScope

from infrastructure.object_storage.composition import (
    _configured_client,
    _configured_environment,
)
from infrastructure.object_storage.exact import ExactKeyObjectStore
from infrastructure.object_storage.port import ObjectBinding
from infrastructure.object_storage.read_access import normalize_object_location
from infrastructure.rdb.composition import close_owned

logger = logging.getLogger(__name__)
_FILE_READ_IO_SECONDS = 5


def _read_call(action, *args, context, **kwargs):
    try:
        return action(*args, **kwargs)
    except (ConnectTimeoutError, ReadTimeoutError):
        raise DeadlineExceeded(operation_id=context.operation_id) from None


class _Body:
    def __init__(self, body, context):
        self.body, self.context = body, context

    def read(self, size):
        return _read_call(self.body.read, size, context=self.context)

    def close(self):
        self.body.close()


class _ReadClient:
    def __init__(self, client, context):
        self.client, self.context = client, context

    def get_object(self, **kwargs):
        response = _read_call(self.client.get_object, context=self.context, **kwargs)
        response['Body'] = _Body(response['Body'], self.context)
        return response

    def head_object(self, **kwargs):
        return _read_call(self.client.head_object, context=self.context, **kwargs)

    def close(self):
        self.client.close()


@contextmanager
def file_read_ports(object_name, *, context, bucket=None):
    bucket = bucket or _configured_environment().MINIO_DEFAULT_BUCKET
    def client(remaining):
        return _ReadClient(_configured_client(min(_FILE_READ_IO_SECONDS, remaining)), context)
    store = ExactKeyObjectStore(StorageScope('management', None, 'management.file.read', {'files'}, system=True),
        ObjectBinding('files', bucket, '', {'management'}, allow_system=True, exact_keys={object_name}), client)
    try:
        context.remaining()
        yield store
    finally:
        close_owned(context, [store.close])


def read_attachment_size(object_name: str) -> int:
    """Read size for an existing attachment reference with its legacy zero-on-error behavior."""
    key, bucket = normalize_object_location(object_name)
    context = OperationContext(f'file-size-{uuid4().hex}', monotonic() + _FILE_READ_IO_SECONDS)
    try:
        with file_read_ports(key, bucket=bucket, context=context) as store:
            return store.stat(ObjectRef('files', key), context=context).size
    except NotFound:
        return 0
    except StorageError as error:
        logger.warning('file_size_unavailable operation_id=%s error_type=%s',
                       context.operation_id, type(error).__name__)
        return 0
