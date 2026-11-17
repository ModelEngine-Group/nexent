# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Cancel a fenced knowledge resource without impersonating individual job owners."""

from contracts.agentos_knowledge import KnowledgeFileReference
from contracts.knowledge_deletion import KnowledgeDeletionIntent
from management.services.file.cleanse_jobs import DATASET
from management.services.knowledge_base.file_authorization import (
    KnowledgeFileAuthorization,
)
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import (
    Comparison,
    FieldPatch,
    Junction,
    PageRequest,
    RecordQuery,
    Sort,
)


def require_knowledge_cleanup(jobs, resources, reference, *, user_id, context, releasing=False):
    if not isinstance(reference, KnowledgeFileReference) or any(
        port.scope.system or port.scope.service_role != "management" or port.scope.actor_id != user_id
        or port.scope.tenant_id != resources.scope.tenant_id for port in (jobs, resources)
    ):
        raise ScopeDenied()
    file, _ = KnowledgeFileAuthorization(resources, user_id=user_id).resolve(
        reference, edit=True, history=True, cleanup=True, context=context,
    )
    if file["status"] != "DELETE_REQUESTED" or file.get("deletion_request") is None:
        raise ScopeDenied()
    intent = KnowledgeDeletionIntent.model_validate(file["deletion_request"])
    if intent.scope != "full" or any(getattr(intent, name) != getattr(reference, name) for name in (
        "knowledge_id", "file_id", "file_version",
    )):
        raise ScopeDenied()
    if releasing and file['stage'] != 'DELETE_CLEANSE_PENDING':
        raise ScopeDenied()
    return (
        Comparison("scope_kind", "eq", "knowledge"),
        Comparison("knowledge_id", "eq", reference.knowledge_id),
        Comparison("file_id", "eq", reference.file_id),
        Comparison("file_version", "lte", reference.file_version),
    )


def cancel_knowledge_executions(jobs, resources, reference, *, user_id, context):
    scope = require_knowledge_cleanup(jobs, resources, reference, user_id=user_id, context=context)
    query = RecordQuery(
        where=Junction("and", scope), order_by=(Sort("job_id"),),
        fields=("id", "job_id", "status", "execution_ended"),
    )
    task_ids, drained, cursor = [], True, None
    while True:
        context.remaining()
        page = jobs.query(DATASET, query, PageRequest(limit=100, cursor=cursor), context=context)
        if page.items:
            with jobs.transaction(context=context) as tx:
                selected = scope + (Comparison("job_id", "in", [row["job_id"] for row in page.items]),)
                tx.claim(DATASET, RecordQuery(where=Junction("and", selected + (Comparison("status", "eq", "queued"),))),
                         FieldPatch(set_values={"status": "cancelled", "execution_ended": True}),
                         limit=100, context=context)
                tx.claim(DATASET, RecordQuery(where=Junction("and", selected + (Comparison("status", "eq", "running"),))),
                         FieldPatch(set_values={"status": "cancelled"}), limit=100, context=context)
                for row in page.items:
                    current = tx.get(DATASET, row["id"], fields=query.fields, context=context)
                    if current is None:
                        raise ScopeDenied()
                    task_ids.append(current["job_id"])
                    drained = drained and current["status"] in {"completed", "failed", "cancelled", "released"} and current["execution_ended"] is True
        if not page.next_cursor:
            break
        cursor = page.next_cursor
    return {"task_ids": task_ids, "cancelled_count": len(task_ids), "execution_drained": drained}
