# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Project existing source size/availability using exact, read-only object handles."""

import logging

from contracts.constants.constants import ASSET_OWNER_ATTACHMENTS_PREFIX
from management.services.knowledge_base.file_projection import merge_lifecycle_files
from nexent.storage.errors import DeadlineExceeded, OperationCancelled, ScopeDenied

from infrastructure.knowledge_file_display import knowledge_file_display_objects

logger = logging.getLogger(__name__)


class FileSourceDisplay:
    def __init__(self, *, objects=knowledge_file_display_objects):
        self.objects = objects

    def project(self, files, actor, *, context, lifecycle_rows=()):
        metadata = {}

        def stat(key):
            if key not in metadata:
                try:
                    with self.objects(actor, key, context=context) as (objects, ref):
                        metadata[key] = objects.stat(ref, context=context)
                except (DeadlineExceeded, OperationCancelled, ScopeDenied):
                    raise
                except Exception as error:  # noqa: BLE001 - Preserve display-only lookup failure semantics.
                    logger.warning(
                        "knowledge_file_display_unavailable operation_id=%s exception_type=%s",
                        context.operation_id,
                        type(error).__name__,
                    )
                    metadata[key] = None
            return metadata[key]

        by_path = {}
        for source in files:
            context.remaining()
            file = dict(source)
            key = file.get("path_or_url") or ""
            if not file.get("file_size") and key:
                value = stat(key)
                file["file_size"] = value.size if value is not None else 0
            by_path[file.get("path_or_url")] = file
        # Enrich physical sizes before lifecycle values, including stored zero.
        merge_lifecycle_files(by_path, lifecycle_rows)
        result = []
        for file in by_path.values():
            context.remaining()
            key = file.get("path_or_url") or ""
            file["chunks"] = []
            file["source_available"] = True
            if file.get("status") == "COMPLETED" and key.startswith(
                ("knowledge_base/", f"{ASSET_OWNER_ATTACHMENTS_PREFIX}/")
            ):
                file["source_available"] = stat(key) is not None
            result.append(file)
        return result
