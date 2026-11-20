# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read the legacy attachment bucket's first object page for Management."""

from datetime import datetime

from botocore.exceptions import BotoCoreError, ClientError
from nexent.storage.errors import InvalidInput, Unavailable
from nexent.storage.models import CapabilitySet, ObjectInventoryEntry, StorageScope

from infrastructure.object_storage.composition import (
    _configured_client,
    _configured_environment,
)
from infrastructure.rdb.composition import close_owned


class AttachmentInventory:
    scope = StorageScope('management', None, 'management.attachment.inventory', {'files'}, system=True)
    capabilities = CapabilitySet({'object.inventory.first_page'})

    def __init__(self, bucket, client_factory):
        if not bucket:
            raise InvalidInput()
        self._bucket, self._client_factory = bucket, client_factory

    def first_page(self, prefix, *, limit, context):
        if not isinstance(prefix, str) or type(limit) is not int or not 1 <= limit <= 1000:
            raise InvalidInput(operation_id=context.operation_id)
        try:
            client = self._client_factory(context.remaining())
            try:
                result = client.list_objects_v2(Bucket=self._bucket, Prefix=prefix, MaxKeys=limit)
            finally:
                close_owned(context, [client.close])
            context.remaining()
            contents = result.get('Contents', [])
            if not isinstance(contents, list) or len(contents) > limit:
                raise ValueError()
            entries = tuple(ObjectInventoryEntry(item['Key'], item['Size'], item['LastModified']) for item in contents)
            if any(
                not isinstance(e.key, str) or not e.key.startswith(prefix)
                or type(e.size) is not int or e.size < 0 or not isinstance(e.last_modified, datetime)
                for e in entries
            ):
                raise ValueError()
            return entries
        except (BotoCoreError, ClientError, OSError, ValueError, KeyError, TypeError):
            raise Unavailable(operation_id=context.operation_id) from None

    def close(self):
        """Each first-page read owns and closes its client."""


def attachment_inventory_port():
    return AttachmentInventory(_configured_environment().MINIO_DEFAULT_BUCKET, _configured_client)
