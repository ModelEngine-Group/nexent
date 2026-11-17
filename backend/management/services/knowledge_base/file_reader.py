# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read lifecycle projections with current-reader DAC, independent of execution ownership."""

import asyncio
import logging
from threading import Event
from time import monotonic
from uuid import uuid4

from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from contracts.knowledge_ingestion import FILE_KNOWLEDGE_READ_DATASET as KNOWLEDGE
from contracts.knowledge_ingestion import FILE_READ_DATASET as FILES
from management.services.knowledge_base.file_authorization import (
    KnowledgeFileAuthorization,
)
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import DeadlineExceeded, InvalidInput, NotFound, ScopeDenied
from nexent.storage.models import (
    Comparison,
    Junction,
    OperationContext,
    PageRequest,
    RecordQuery,
    Sort,
)
from permissions.dac import resolve_knowledge_permissions

from infrastructure.knowledge_file_read import knowledge_file_read_ports

logger = logging.getLogger(__name__)


class KnowledgeFileReader:
    def __init__(self, *, ports=knowledge_file_read_ports):
        self.ports = ports

    def error_info(self, index_name, path, actor, *, file_id=None, context):
        context.remaining()
        with self.ports(actor, context=context) as (knowledge, identity, scoped_files):
            if any(
                port.scope.service_role != "management"
                or port.scope.system
                or port.scope.actor_id != actor.user_id
                or port.scope.tenant_id != actor.tenant_id
                for port in (knowledge, identity)
            ):
                raise ScopeDenied()
            page = knowledge.query(
                KNOWLEDGE,
                RecordQuery(where=Comparison("index_name", "eq", index_name)),
                PageRequest(limit=2),
                context=context,
            )
            if not page.items:
                raise ValueError(f"Knowledge base '{index_name}' not found")
            if len(page.items) != 1 or page.next_cursor:
                raise ScopeDenied()
            row = dict(page.items[0])
            resource_tenant = row.pop("resource_tenant_id")
            if resource_tenant not in {actor.tenant_id, ASSET_OWNER_TENANT_ID}:
                raise ScopeDenied()
            row["tenant_id"] = resource_tenant
            membership, groups = KnowledgeFileAuthorization(
                identity, user_id=actor.user_id
            ).identity(context=context)
            permission = resolve_knowledge_permissions(
                [row],
                actor.user_id,
                actor.tenant_id,
                membership,
                groups,
                speed_mode=False,
            )[index_name]
            if permission is None:
                raise ScopeDenied()
            records = scoped_files(resource_tenant)
            if (
                records.scope.tenant_id != resource_tenant
                or records.scope.actor_id != actor.user_id
                or records.scope.service_role != "management"
                or records.scope.system
            ):
                raise ScopeDenied()
            terms = [
                Comparison("knowledge_id", "eq", row["knowledge_id"]),
                Comparison("index_name", "eq", index_name),
            ]
            if file_id:
                terms.append(Comparison("file_id", "eq", file_id))
            else:
                terms.append(
                    Junction(
                        "or",
                        (
                            Comparison("object_name", "eq", path),
                            Comparison("local_source_path", "eq", path),
                        ),
                    )
                )
            page = records.query(
                FILES,
                RecordQuery(
                    where=Junction("and", tuple(terms)),
                    order_by=(Sort("update_time", descending=True),),
                ),
                PageRequest(limit=1),
                context=context,
            )
            if not page.items:
                raise NotFound()
            file = page.items[0]
            failed_at = file["failed_at"]
            if failed_at is not None and not isinstance(failed_at, str):
                raise InvalidInput()
            if isinstance(failed_at, str) and failed_at.endswith("+00:00"):
                failed_at = failed_at[:-6] + "Z"
            return {
                "status": "success",
                "error_code": file["error_code"],
                "error_message": file["error_message"],
                "error_stage": file["error_stage"] or file["stage"],
                "failed_at": failed_at,
            }


async def read_document_error(index_name, path, actor, *, file_id=None):
    cancelled = Event()
    context = OperationContext(
        "knowledge-file-read-" + uuid4().hex, monotonic() + 10, cancelled=cancelled
    )
    try:
        async with asyncio.timeout(context.remaining()):
            return await run_blocking(
                "knowledge-file-error",
                KnowledgeFileReader().error_info,
                index_name,
                path,
                actor,
                file_id=file_id,
                context=context,
                lane="control-io",
                owner="management.knowledge_base",
            )
    except (TimeoutError, DeadlineExceeded):
        logger.warning(
            "knowledge_file_read_timeout operation_id=%s phase=error-info threshold_seconds=10",
            context.operation_id,
        )
        raise
    finally:
        cancelled.set()
