# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Resolve document selection to current authorized knowledge file identities."""

from contracts.agentos_knowledge import KnowledgeFileReference, ObjectReference
from management.services.knowledge_base.file_authorization import (
    KnowledgeFileAuthorization,
)
from management.services.knowledge_base.file_selection import (
    matches_file_selection,
    parse_file_selections,
)
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import Comparison, Junction, PageRequest, RecordQuery

from infrastructure.knowledge_cleanse import knowledge_resource_ports


def resolve_tool_files(records, user_id, knowledge_ids, paths, *, context):
    """None and empty external paths mean no filter; an unresolved selection means deny-all."""
    if not paths:
        return None
    if not knowledge_ids:
        return []
    if len(paths) > 1000:
        raise ScopeDenied()
    keys, qualified = parse_file_selections(paths)
    KnowledgeFileAuthorization(records, user_id=user_id).resolve_knowledges(knowledge_ids, edit=False, context=context)
    choices = []
    if keys:
        choices.extend(Comparison(field, "in", keys) for field in ("source_key", "object_name"))
    for bucket, names in qualified.items():
        choices.append(Junction("and", (Comparison("bucket_name", "eq", bucket), Junction("or", tuple(
            Comparison(field, "in", names) for field in ("source_key", "object_name")
        )))))
    page = records.query("cleanse_files", RecordQuery(where=Junction("and", (
        Comparison("knowledge_id", "in", list(knowledge_ids)),
        Comparison("status", "in", ["UPLOADED", "PROCESSING", "FORWARDING", "FAILED", "COMPLETED"]),
        Junction("or", tuple(choices)),
    ))), PageRequest(limit=1000), context=context)
    if page.next_cursor:
        raise ScopeDenied()
    refs = []
    for row in page.items:
        if row["knowledge_id"] not in knowledge_ids or not matches_file_selection(row, keys, qualified) or row["source_space"] != "files":
            raise ScopeDenied()
        try:
            ObjectReference(space=row["source_space"], key=row["source_key"], version=row["source_revision"], sha256=row["source_sha256"])
            refs.append(KnowledgeFileReference(knowledge_id=row["knowledge_id"], file_id=row["file_id"], file_version=row["source_generation"]))
        except (ValueError, TypeError):
            raise ScopeDenied() from None
    return sorted(refs, key=lambda ref: (ref.knowledge_id, ref.file_id, ref.file_version))


def prepare_tool_files(user_id, tenant_id, knowledge_ids, paths, *, context):
    if not paths:
        return None
    with knowledge_resource_ports(tenant_id, user_id, context=context, include_files=True) as records:
        return resolve_tool_files(records, user_id, knowledge_ids, paths, context=context)
