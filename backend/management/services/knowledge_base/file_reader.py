# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read lifecycle projections with current-reader DAC, independent of execution ownership."""

import asyncio
import logging
from contextlib import contextmanager
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

    @staticmethod
    def _authorized_rows(rows, identity, actor, *, context, edit):
        selected = []
        for value in rows:
            row = dict(value)
            tenant = row.pop("resource_tenant_id")
            if tenant not in {actor.tenant_id, ASSET_OWNER_TENANT_ID}:
                raise ScopeDenied()
            row["tenant_id"] = tenant
            selected.append(row)
        member, groups = KnowledgeFileAuthorization(identity, user_id=actor.user_id).identity(context=context)
        permissions = resolve_knowledge_permissions(selected, actor.user_id, actor.tenant_id,
            member, groups, speed_mode=False)
        if any(permissions[row["index_name"]] is None or edit and permissions[row["index_name"]] not in {"EDIT", "CREATOR"}
               for row in selected):
            raise ScopeDenied()
        return selected

    def knowledges(self, knowledge_ids, actor, *, context, edit=False):
        if (not isinstance(knowledge_ids, (list, tuple)) or not 0 < len(knowledge_ids) <= 100
            or any(type(value) is not int or value <= 0 for value in knowledge_ids)
            or len(set(knowledge_ids)) != len(knowledge_ids)):
            raise InvalidInput()
        context.remaining()
        with self.ports(actor, context=context) as (knowledge, identity, _):
            if any(port.scope.service_role != "management" or port.scope.system or port.scope.resource_prefix
                or port.scope.actor_id != actor.user_id or port.scope.tenant_id != actor.tenant_id
                for port in (knowledge, identity)):
                raise ScopeDenied()
            page = knowledge.query(KNOWLEDGE, RecordQuery(where=Comparison("knowledge_id", "in", list(knowledge_ids))),
                PageRequest(limit=len(knowledge_ids)), context=context)
            if (page.next_cursor or len(page.items) != len(knowledge_ids)
                or {row["knowledge_id"] for row in page.items} != set(knowledge_ids)
                or len({row["index_name"] for row in page.items}) != len(page.items)):
                raise ScopeDenied()
            rows = {row["knowledge_id"]: row for row in self._authorized_rows(
                page.items, identity, actor, context=context, edit=edit)}
            return [rows[key] for key in knowledge_ids]

    @contextmanager
    def _records(self, index_name, actor, *, context, knowledge_id=None, edit=False):
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
                RecordQuery(where=Comparison("index_name" if knowledge_id is None else 'knowledge_id', "eq",
                                             index_name if knowledge_id is None else knowledge_id)),
                PageRequest(limit=2),
                context=context,
            )
            if not page.items:
                raise ValueError(f"Knowledge base '{index_name}' not found")
            if len(page.items) != 1 or page.next_cursor:
                raise ScopeDenied()
            row = self._authorized_rows(page.items, identity, actor, context=context, edit=edit)[0]
            resource_tenant = row["tenant_id"]
            records = scoped_files(resource_tenant)
            if (
                records.scope.tenant_id != resource_tenant
                or records.scope.actor_id != actor.user_id
                or records.scope.service_role != "management"
                or records.scope.system
            ):
                raise ScopeDenied()
            yield records, row

    def knowledge(self, index_name, actor, *, context, knowledge_id=None, edit=False):
        with self._records(index_name, actor, context=context, knowledge_id=knowledge_id, edit=edit) as (_, row):
            return row

    def files(self, index_name, actor, *, context):
        with self._records(index_name, actor, context=context) as (records, knowledge):
            query = RecordQuery(
                where=Junction("and", (
                    Comparison("knowledge_id", "eq", knowledge["knowledge_id"]),
                    Comparison("index_name", "eq", index_name),
                )),
                order_by=(Sort("file_id"),),
            )
            rows, cursor = [], None
            while True:
                context.remaining()
                page = records.query(FILES, query, PageRequest(limit=1000, cursor=cursor), context=context)
                rows.extend(page.items)
                if not page.next_cursor:
                    return rows
                cursor = page.next_cursor

    def error_info(self, index_name, path, actor, *, file_id=None, context):
        with self._records(index_name, actor, context=context) as (records, row):
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


async def _read(phase, callback, *args, **kwargs):
    cancelled = Event()
    context = OperationContext(
        "knowledge-file-read-" + uuid4().hex, monotonic() + 10, cancelled=cancelled
    )
    try:
        async with asyncio.timeout(context.remaining()):
            return await run_blocking(
                "knowledge-file-" + phase,
                callback,
                *args,
                **kwargs,
                context=context,
                lane="control-io",
                owner="management.knowledge_base",
            )
    except (TimeoutError, DeadlineExceeded) as exc:
        logger.warning(
            "knowledge_file_read_timeout operation_id=%s phase=%s threshold_seconds=10 error_type=%s",
            context.operation_id,
            phase,
            type(exc).__name__,
        )
        raise
    finally:
        cancelled.set()


async def read_document_error(index_name, path, actor, *, file_id=None):
    return await _read("error-info", KnowledgeFileReader().error_info, index_name, path, actor, file_id=file_id)
