# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Delete one explicitly granted opaque key in an XML body, never in a URL path."""

from base64 import b64encode
from hashlib import md5

from nexent.storage.errors import (
    CapabilityUnsupported,
    OutcomeUnknown,
    ScopeDenied,
    Unavailable,
)
from nexent.storage.models import DeleteReceipt, ObjectRef

from infrastructure.object_storage.exact import opaque_key
from infrastructure.object_storage.port import S3ObjectStore


def _delete_checksum(params, **_):
    # General-purpose S3 buckets require the digest of the actual serialized XML.
    params['headers']['Content-MD5'] = b64encode(md5(params['body'], usedforsecurity=False).digest()).decode('ascii')


class ExactObjectDeletionStore(S3ObjectStore):
    def delete(self, ref, *, expected=None, context):
        binding = self._binding
        if (not isinstance(ref, ObjectRef) or ref.space != binding.space
            or not binding.writable or self.scope.system or self.scope.resource_prefix
            or binding.prefix or binding.exact_keys != {ref.key}):
            raise ScopeDenied()
        if expected is not None or ref.version is not None:
            raise CapabilityUnsupported(operation_id=context.operation_id)
        opaque_key(ref.key)
        with self._client(context) as client:
            client.meta.events.register('before-call.s3.DeleteObjects', _delete_checksum)
            response = self._call(client, 'delete_objects', context, write=True, Bucket=binding.bucket,
                                  Delete={'Objects': [{'Key': ref.key}], 'Quiet': False})
        errors = response.get('Errors')
        if errors:
            if (not isinstance(errors, list) or len(errors) != 1 or not isinstance(errors[0], dict)
                or errors[0].get('Key') != ref.key):
                raise OutcomeUnknown(operation_id=context.operation_id)
            failure = ScopeDenied if errors[0].get('Code') == 'AccessDenied' else Unavailable
            raise failure(operation_id=context.operation_id)
        deleted = response.get('Deleted')
        if (not isinstance(deleted, list) or len(deleted) != 1 or not isinstance(deleted[0], dict)
            or deleted[0].get('Key') != ref.key):
            raise OutcomeUnknown(operation_id=context.operation_id)
        return DeleteReceipt(context.operation_id, True)
