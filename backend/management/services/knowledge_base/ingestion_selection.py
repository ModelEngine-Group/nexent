# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Resolve public upload aliases to an exact current authorized file without reading caller paths."""

from contracts.agentos_knowledge import KnowledgeFileReference, ObjectReference
from management.services.knowledge_base.file_authorization import (
    KnowledgeFileAuthorization,
)
from management.services.knowledge_base.file_selection import (
    matches_file_selection,
    parse_file_selections,
)
from nexent.storage.errors import NotFound, ScopeDenied
from nexent.storage.models import Comparison, Junction, PageRequest, RecordQuery
from pydantic import ValidationError


def resolve_ingestion_file(
    records, actor, index_name, details, *, destination, context
):
    if (
        records.scope.tenant_id != actor.tenant_id
        or records.scope.actor_id != actor.user_id
        or destination not in {"minio", "local"}
    ):
        raise ScopeDenied()
    if not isinstance(details, dict):
        raise ScopeDenied()
    authorization = KnowledgeFileAuthorization(records, user_id=actor.user_id)
    knowledge = authorization._one(
        "cleanse_knowledge", "index_name", index_name, context
    )
    authorization.resolve_knowledge(
        knowledge["knowledge_id"], edit=True, context=context
    )
    terms = [
        Comparison("knowledge_id", "eq", knowledge["knowledge_id"]),
        Comparison(
            "status",
            "in",
            ["UPLOADED", "PROCESSING", "FORWARDING", "FAILED", "COMPLETED"],
        ),
    ]
    path, file_id = details.get("path_or_url"), details.get("file_id")
    if path is not None and (not isinstance(path, str) or not 0 < len(path) <= 2048):
        raise ScopeDenied()
    keys, qualified = (
        parse_file_selections([path]) if path and destination == "minio" else ([], {})
    )
    if file_id:
        try:
            KnowledgeFileReference(
                knowledge_id=knowledge["knowledge_id"], file_id=file_id, file_version=0
            )
        except ValidationError:
            raise ScopeDenied() from None
        terms.append(Comparison("file_id", "eq", file_id))
    elif not path:
        raise ScopeDenied()
    elif destination == "local":
        terms.append(Comparison("local_source_path", "eq", path))
    else:
        choices = (
            [Comparison(name, "in", keys) for name in ("source_key", "object_name")]
            if keys
            else []
        )
        for bucket, names in qualified.items():
            choices.append(
                Junction(
                    "and",
                    (
                        Comparison("bucket_name", "eq", bucket),
                        Junction(
                            "or",
                            tuple(
                                Comparison(field, "in", names)
                                for field in ("source_key", "object_name")
                            ),
                        ),
                    ),
                )
            )
        terms.append(Junction("or", tuple(choices)))
    page = records.query(
        "cleanse_files",
        RecordQuery(where=Junction("and", tuple(terms))),
        PageRequest(limit=2),
        context=context,
    )
    if not page.items:
        raise NotFound()
    if len(page.items) != 1 or page.next_cursor:
        raise ScopeDenied()
    row = page.items[0]
    if path and (
        row["local_source_path"] != path
        if destination == "local"
        else not matches_file_selection(row, keys, qualified)
    ):
        raise ScopeDenied()
    try:
        reference = KnowledgeFileReference(
            knowledge_id=row["knowledge_id"],
            file_id=row["file_id"],
            file_version=row["source_generation"],
        )
        source = ObjectReference(
            space=row["source_space"],
            key=row["source_key"],
            version=row["source_revision"],
            sha256=row["source_sha256"],
        )
    except ValidationError:
        raise ScopeDenied() from None
    if source.space != "files":
        raise ScopeDenied()
    authorization.resolve(reference, edit=True, context=context)
    return row
