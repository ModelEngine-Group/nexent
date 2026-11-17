# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Publish owned unbound local uploads without assigning a fictitious knowledge base."""

import asyncio
import logging
from threading import Event
from time import monotonic
from uuid import uuid4

from contracts.file import UploadFilesResult
from management.services.file.local_source_staging import LocalSourceStaging
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import DeadlineExceeded, OutcomeUnknown
from nexent.storage.models import OperationContext

from infrastructure.file_processing.local_source import (
    copy_local_source,
    describe_local_upload,
    local_source_location,
)
from infrastructure.local_source_staging import local_source_staging_port

logger = logging.getLogger(__name__)


def stage_local_source(stream, filename, actor, root, context):
    path = local_source_location(root, uuid4().hex, filename)
    size, digest = describe_local_upload(stream, context=context)
    confirmed = False
    try:
        with local_source_staging_port(
            actor.tenant_id, actor.user_id, context=context
        ) as records:
            journal = LocalSourceStaging(records)
            row = journal.reserve(
                path.parent.name, str(path), path.name, size, digest, context=context
            )
            copy_local_source(
                stream,
                root,
                row["stage_id"],
                path.name,
                expected_size=size,
                expected_sha256=digest,
                context=context,
            )
            result = journal.confirm(row, context=context)
            confirmed = True
        return result
    except Exception as error:
        if confirmed:
            raise OutcomeUnknown(operation_id=context.operation_id) from error
        raise


async def upload_staged_local_files(files, actor, root):
    errors, paths, names = [], [], []
    for upload in files:
        if upload is None:
            continue
        cancelled = Event()
        context = OperationContext(
            "local-staging-" + uuid4().hex, monotonic() + 120, cancelled=cancelled
        )
        try:
            async with asyncio.timeout(context.remaining()):
                row = await run_blocking(
                    "local-source-stage",
                    stage_local_source,
                    upload.file,
                    upload.filename or "",
                    actor,
                    root,
                    context,
                    lane="file-upload",
                    owner="management.file",
                )
            paths.append(row["local_source_path"])
            names.append(row["original_filename"])
        except (OutcomeUnknown, TimeoutError, DeadlineExceeded):
            logger.warning(
                "local_source_staging_unknown operation_id=%s threshold_seconds=120",
                context.operation_id,
            )
            errors.append("Local source publication requires reconciliation")
        except Exception:  # noqa: BLE001 - Preserve independent per-file upload outcomes.
            errors.append(f"Failed to save file: {upload.filename}")
        finally:
            cancelled.set()
    return UploadFilesResult(errors, paths, names)
