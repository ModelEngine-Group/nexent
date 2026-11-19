# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Preview source metadata and the existing cache probe policy through SI."""

import logging

from contracts.errors.exceptions import NotFoundException
from nexent.storage.errors import DeadlineExceeded, OperationCancelled, StorageError
from nexent.storage.models import ByteRange, ObjectRef

from infrastructure.preview_objects import preview_object_ports

logger = logging.getLogger(__name__)


class PreviewObjects:
    def __init__(self, *, ports=preview_object_ports):
        self.ports = ports

    def size(self, name, *, context):
        try:
            with self.ports(name, context=context) as store:
                return store.stat(ObjectRef('files', name), context=context).size
        except (DeadlineExceeded, OperationCancelled):
            raise
        except StorageError as error:
            # The old source-exists check treated provider failures as missing.
            raise NotFoundException(f'File not found: {name}') from error

    def cache_valid(self, name, *, context):
        with self.ports(name, writable=True, context=context) as store:
            ref = ObjectRef('files', name)
            try:
                store.stat(ref, context=context)
            except (DeadlineExceeded, OperationCancelled):
                raise
            except StorageError:
                return False
            opened = False
            try:
                with store.open_read(ref, byte_range=ByteRange(0, 1), context=context):
                    opened = True
                return True
            except (DeadlineExceeded, OperationCancelled):
                raise
            except Exception as error:
                if opened:
                    logger.warning('preview_cache_probe_close_failed error_type=%s', type(error).__name__)
                    return True
                if not isinstance(error, StorageError):
                    raise
                context.remaining()
                logger.warning('preview_cache_unreadable')
                try:
                    store.delete(ref, context=context)
                except (DeadlineExceeded, OperationCancelled):
                    raise
                except StorageError:
                    # Cache-delete failure previously did not start a retry or stop conversion.
                    logger.warning('preview_cache_cleanup_failed')
                return False
