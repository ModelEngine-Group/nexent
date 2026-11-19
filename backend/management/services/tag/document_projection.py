# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Display tags only for already authorized file rows in the actual caller tenant."""

import asyncio
import logging
from threading import Event
from time import monotonic
from uuid import uuid4

from contracts.constants.constants import (
    DOCUMENT_TAG_BATCH_SIZE,
    KNOWLEDGE_DOCUMENT_TYPE,
    PUBLIC_DOCUMENT_ASSIGNMENT_FIELDS,
)
from management.services.tag.identity import (
    KNOWLEDGE_CONTENT_LIBRARY_CODE,
    LOCAL_DOCUMENT_PROVIDER,
    _encode_document_resource_id,
)
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import (
    Conflict,
    DeadlineExceeded,
    OperationCancelled,
    ScopeDenied,
)
from nexent.storage.models import (
    Comparison,
    Junction,
    OperationContext,
    PageRequest,
    RecordQuery,
    Sort,
)

from infrastructure.document_tags import document_tag_ports
from infrastructure.rdb.document_tag_records import ASSIGNMENTS, BINDINGS, KNOWLEDGE

logger = logging.getLogger(__name__)


class DocumentTagProjection:
    def __init__(self, *, ports=document_tag_ports):
        self.ports = ports

    def project(self, files, index_name, actor, *, context):
        projected = [dict(file, tags=[]) for file in files]
        paths = {str(file.get("path_or_url") or "").strip(): None for file in files}
        paths.pop("", None)
        if not paths or not index_name:
            return projected
        paths = {
            path: _encode_document_resource_id(
                LOCAL_DOCUMENT_PROVIDER, index_name, path
            )
            for path in paths
        }
        try:
            context.remaining()
            with self.ports(actor, context=context) as records:
                scope = records.scope
                if (
                    scope.service_role != "management"
                    or scope.system
                    or scope.resource_prefix
                    or scope.tenant_id != actor.tenant_id
                    or scope.actor_id != actor.user_id
                ):
                    raise ScopeDenied()
                page = records.query(
                    KNOWLEDGE,
                    RecordQuery(where=Comparison("index_name", "eq", index_name)),
                    PageRequest(limit=2),
                    context=context,
                )
                if (
                    len(page.items) != 1
                    or page.next_cursor
                    or page.items[0]["tenant_id"] != actor.tenant_id
                ):
                    return projected
                binding = records.query(
                    BINDINGS,
                    RecordQuery(
                        where=Junction(
                            "and",
                            (
                                Comparison(
                                    "resource_type", "eq", KNOWLEDGE_DOCUMENT_TYPE
                                ),
                                Comparison(
                                    "bucket_key", "eq", KNOWLEDGE_CONTENT_LIBRARY_CODE
                                ),
                            ),
                        )
                    ),
                    PageRequest(limit=2),
                    context=context,
                )
                if len(binding.items) != 1 or binding.next_cursor:
                    return projected
                assignments = {}
                ids = list(paths.values())
                for start in range(0, len(ids), DOCUMENT_TAG_BATCH_SIZE):
                    query = RecordQuery(
                        where=Junction(
                            "and",
                            (
                                Comparison(
                                    "resource_type", "eq", KNOWLEDGE_DOCUMENT_TYPE
                                ),
                                Comparison(
                                    "resource_id",
                                    "in",
                                    ids[start : start + DOCUMENT_TAG_BATCH_SIZE],
                                ),
                            ),
                        ),
                        order_by=(
                            Sort("definition_order"),
                            Sort("definition_id"),
                            Sort("value_order"),
                            Sort("value_id"),
                            Sort("assignment_id"),
                        ),
                    )
                    cursor, seen = None, set()
                    while True:
                        context.remaining()
                        page = records.query(
                            ASSIGNMENTS,
                            query,
                            PageRequest(limit=1000, cursor=cursor),
                            context=context,
                        )
                        for row in page.items:
                            if (
                                row["tenant_id"] != actor.tenant_id
                                or row["resource_id"]
                                not in ids[start : start + DOCUMENT_TAG_BATCH_SIZE]
                            ):
                                raise ScopeDenied()
                            assignments.setdefault(row["resource_id"], []).append(
                                {
                                    name: row[name]
                                    for name in PUBLIC_DOCUMENT_ASSIGNMENT_FIELDS
                                }
                            )
                        if page.next_cursor is None:
                            break
                        if page.next_cursor in seen:
                            raise Conflict()
                        seen.add(page.next_cursor)
                        cursor = page.next_cursor
                for output, source in zip(projected, files):
                    path = str(source.get("path_or_url") or "").strip()
                    output["tags"] = assignments.get(paths.get(path), [])
                context.remaining()
        except (DeadlineExceeded, OperationCancelled):
            raise
        except Exception as error:  # noqa: BLE001 - Preserve the existing display-only failure behavior.
            logger.warning(
                "document_tag_projection_unavailable operation_id=%s exception_type=%s",
                context.operation_id,
                type(error).__name__,
            )
            return [dict(file, tags=[]) for file in files]
        return projected


async def project_authorized_document_tags(files, *, index_name, actor):
    cancelled = Event()
    context = OperationContext(
        "document-tags-" + uuid4().hex, monotonic() + 10, cancelled=cancelled
    )
    try:
        async with asyncio.timeout(context.remaining()):
            return await run_blocking(
                "document-tag-projection",
                DocumentTagProjection().project,
                files,
                index_name,
                actor,
                context=context,
                lane="control-io",
                owner="management.tag",
            )
    except (TimeoutError, DeadlineExceeded, OperationCancelled) as error:
        logger.warning(
            "document_tag_projection_timeout operation_id=%s phase=display threshold_seconds=10 exception_type=%s",
            context.operation_id,
            type(error).__name__,
        )
        return [dict(file, tags=[]) for file in files]
    except Exception as error:  # noqa: BLE001 - Optional display also tolerates managed admission failure.
        logger.warning(
            "document_tag_projection_unavailable operation_id=%s exception_type=%s",
            context.operation_id,
            type(error).__name__,
        )
        return [dict(file, tags=[]) for file in files]
    finally:
        cancelled.set()
