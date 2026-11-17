# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Register local mirrors without changing the pinned object handed to Runtime."""

import asyncio
from threading import Event
from time import monotonic
from uuid import uuid4

from contracts.agentos_knowledge import KnowledgeFileReference
from contracts.file import UploadFilesResult
from contracts.knowledge_ingestion import INGESTION_DATASET
from management.services.knowledge_base.file_authorization import (
    KnowledgeFileAuthorization,
)
from management.services.knowledge_base.ingestion_journal import IngestionJournal
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import Conflict, OutcomeUnknown, ScopeDenied
from nexent.storage.models import FieldPatch, OperationContext, Revision, WriteOutcome

from infrastructure.file_processing.local_source import (
    copy_local_source,
    discard_local_source,
)
from infrastructure.knowledge_ingestion import knowledge_ingestion_ports


def publish_local_source(record, stream, actor, root, context):
    path, registered = None, False
    try:
        with knowledge_ingestion_ports(
            actor.tenant_id, actor.user_id, context=context
        ) as (records, resources):
            row = IngestionJournal(records).record(record["file_id"], context=context)
            if (
                row["created_by"] != actor.user_id
                or row["status"] != "UPLOADED"
                or row["ingestion_request"] is not None
            ):
                raise ScopeDenied()
            if any(
                row[name] != record[name]
                for name in (
                    "source_generation",
                    "source_space",
                    "source_key",
                    "source_revision",
                    "source_sha256",
                )
            ):
                raise Conflict()
            reference = KnowledgeFileReference(
                knowledge_id=row["knowledge_id"],
                file_id=row["file_id"],
                file_version=row["source_generation"],
            )
            KnowledgeFileAuthorization(resources, user_id=actor.user_id).resolve(
                reference, edit=True, context=context
            )
            path = copy_local_source(
                stream,
                root,
                row["file_id"],
                row["original_filename"],
                expected_size=row["file_size"],
                expected_sha256=row["source_sha256"],
                context=context,
            )
            receipt = records.patch(
                INGESTION_DATASET,
                row["file_id"],
                FieldPatch(set_values={"local_source_path": str(path)}),
                expected=Revision(str(row["version"])),
                context=context,
            )
            if receipt.outcome is WriteOutcome.UNKNOWN:
                raise OutcomeUnknown(operation_id=context.operation_id)
            if receipt.outcome is not WriteOutcome.CONFIRMED or not receipt.matched:
                raise Conflict()
            registered = True
            return IngestionJournal(records).record(row["file_id"], context=context)
    except OutcomeUnknown:
        raise
    except Exception as error:
        if registered:
            raise OutcomeUnknown(operation_id=context.operation_id) from error
        if path is not None:
            discard_local_source(path, root)
        raise


async def upload_local_knowledge_files(files, *, uploader, actor, root):
    result = await uploader(file=files)
    errors, paths, names = result
    records = list(result.file_records)
    uploads = [upload for upload in files if upload]
    if len(records) != len(uploads):
        raise ScopeDenied()
    by_object = {
        record["object_name"]: (index, upload, record)
        for index, (upload, record) in enumerate(zip(uploads, records))
    }
    local_paths, local_names = [], []
    errors = list(errors)
    for object_name, name in zip(paths, names):
        index, upload, record = by_object[object_name]
        cancelled = Event()
        context = OperationContext(
            "local-source-" + uuid4().hex, monotonic() + 120, cancelled=cancelled
        )
        try:
            async with asyncio.timeout(context.remaining()):
                updated = await run_blocking(
                    "knowledge-local-source",
                    publish_local_source,
                    record,
                    upload.file,
                    actor,
                    root,
                    context,
                    lane="file-upload",
                    owner="management.file",
                )
            records[index] = updated
            local_paths.append(updated["local_source_path"])
            local_names.append(name)
        except (OutcomeUnknown, TimeoutError):
            errors.append("Local source publication requires reconciliation")
        except Exception:  # noqa: BLE001 - Preserve the confirmed source while reporting this mirror failure.
            errors.append("Local source publication failed")
        finally:
            cancelled.set()
    return UploadFilesResult(
        errors, local_paths, local_names, result.quota_status, records
    )
