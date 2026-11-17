# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bind an owned local source once, preserving the existing object publication and quotas."""

from uuid import uuid4

from contracts.constants.constants import CONFIG_SERVICE_NAME
from contracts.constants.environment import MAX_KNOWLEDGE_FILE_SIZE_BYTES
from contracts.knowledge_ingestion import INGESTION_DATASET
from fastapi import UploadFile
from management.services.file.local_source_staging import LocalSourceStaging
from management.services.knowledge_base.file_authorization import (
    KnowledgeFileAuthorization,
)
from management.services.knowledge_base.ingestion_journal import IngestionJournal
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import Conflict, OutcomeUnknown, ScopeDenied
from nexent.storage.models import FieldPatch, Revision, WriteOutcome

from infrastructure.file_processing.local_source import open_staged_local_source
from infrastructure.knowledge_ingestion import knowledge_ingestion_ports
from infrastructure.local_source_staging import local_source_staging_port


def prepare_staged_binding(resources, details, actor, index_name, context):
    if details.get("file_id"):
        raise ScopeDenied()
    authorization = KnowledgeFileAuthorization(resources, user_id=actor.user_id)
    knowledge = authorization._one(
        "cleanse_knowledge", "index_name", index_name, context
    )
    with local_source_staging_port(
        actor.tenant_id, actor.user_id, context=context
    ) as records:
        journal = LocalSourceStaging(records)
        row = journal.find(details.get("path_or_url"), context=context)
        if row["state"] == "BINDING":
            raise OutcomeUnknown(operation_id=context.operation_id)
        if row["state"] != "READY":
            raise Conflict()
        if row["file_size"] > MAX_KNOWLEDGE_FILE_SIZE_BYTES:
            from contracts.errors.codes import ErrorCode
            from contracts.errors.exceptions import AppException

            raise AppException(
                ErrorCode.FILE_TOO_LARGE, "Knowledge base file exceeds the size limit"
            )
        return journal.bind(
            row, knowledge["knowledge_id"], uuid4().hex, authorization, context=context
        )


def finish_staged_binding(stage, actor, context):
    confirmed = False
    try:
        with knowledge_ingestion_ports(
            actor.tenant_id, actor.user_id, context=context
        ) as (records, resources):
            row = IngestionJournal(records).record(
                stage["bound_file_id"], context=context
            )
            if (
                row["knowledge_id"] != stage["knowledge_id"]
                or row["created_by"] != actor.user_id
                or row["status"] != "UPLOADED"
                or row["ingestion_request"] is not None
                or row["file_size"] != stage["file_size"]
                or row["source_sha256"] != stage["source_sha256"]
                or row["source_revision"] is None
                or row["local_source_path"] not in (None, stage["local_source_path"])
            ):
                raise Conflict()
            from contracts.agentos_knowledge import KnowledgeFileReference

            KnowledgeFileAuthorization(resources, user_id=actor.user_id).resolve(
                KnowledgeFileReference(
                    knowledge_id=row["knowledge_id"],
                    file_id=row["file_id"],
                    file_version=row["source_generation"],
                ),
                edit=True,
                context=context,
            )
            receipt = records.patch(
                INGESTION_DATASET,
                row["file_id"],
                FieldPatch(
                    set_values={"local_source_path": stage["local_source_path"]}
                ),
                expected=Revision(str(row["version"])),
                context=context,
            )
            if receipt.outcome is WriteOutcome.UNKNOWN:
                raise OutcomeUnknown(operation_id=context.operation_id)
            if receipt.outcome is not WriteOutcome.CONFIRMED or not receipt.matched:
                raise Conflict()
            confirmed = True
            updated = IngestionJournal(records).record(row["file_id"], context=context)
        with local_source_staging_port(
            actor.tenant_id, actor.user_id, context=context
        ) as records:
            LocalSourceStaging(records).complete(stage, context=context)
        return updated
    except Exception as error:
        if confirmed:
            raise OutcomeUnknown(operation_id=context.operation_id) from error
        raise


async def publish_staged_binding(
    stage, index_name, actor, root, context, *, uploader=None
):
    if uploader is None:
        from management.services.file.service import upload_files_impl

        uploader = upload_files_impl
    stream = await run_blocking(
        "local-source-read",
        open_staged_local_source,
        stage,
        root,
        context,
        lane="file-upload",
        owner="management.file",
    )
    upload = UploadFile(
        file=stream, filename=stage["original_filename"], size=stage["file_size"]
    )
    try:
        context.remaining()
        result = await uploader(
            destination="minio",
            file=[upload],
            folder="knowledge_base",
            index_name=index_name,
            user_id=actor.user_id,
            uploader_tenant_id=actor.tenant_id,
            upload_owner_service=CONFIG_SERVICE_NAME,
            lifecycle_file_ids=[stage["bound_file_id"]],
        )
        if result[0] or not result[1]:
            if result.file_records and result.file_records[0].get("status") == "FAILED":
                raise Conflict()
            raise OutcomeUnknown(operation_id=context.operation_id)
        if (
            len(result.file_records) != 1
            or result.file_records[0]["file_id"] != stage["bound_file_id"]
        ):
            raise Conflict()
        return await run_blocking(
            "local-source-bind",
            finish_staged_binding,
            stage,
            actor,
            context,
            lane="control-io",
            owner="management.file",
        )
    finally:
        stream.close()
