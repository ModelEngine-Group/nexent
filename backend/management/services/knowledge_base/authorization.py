# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management attests file scope and confirmed cleansing outputs to Runtime."""

from contracts.agentos_knowledge import (
    KnowledgeAuthorizationRequest,
    KnowledgeFileGrant,
    ObjectReference,
)
from contracts.knowledge_cleanse import parse_cleanse_request
from management.services.knowledge_base.file_authorization import (
    KnowledgeFileAuthorization,
)
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import Comparison, Junction, PageRequest, RecordQuery

from infrastructure.knowledge_cleanse import knowledge_cleanse_ports


class KnowledgeAuthorization:
    def __init__(self, jobs, resources, *, user_id):
        self.jobs, self.user_id = jobs, user_id
        self.resources = KnowledgeFileAuthorization(resources, user_id=user_id)

    def authorize(self, request, *, context):
        if not isinstance(request, KnowledgeAuthorizationRequest):
            raise ScopeDenied()
        execution = request.action in {"upload", "execute"}
        file, knowledge = self.resources.resolve(
            request,
            edit=request.action != "inspect",
            history=not execution,
            cleanup=not execution,
            context=context,
        )
        source = None
        if execution:
            try:
                source = ObjectReference(
                    space=file["source_space"],
                    key=file["source_key"],
                    version=file["source_revision"],
                    sha256=file["source_sha256"],
                )
            except ValueError:
                raise ScopeDenied() from None
            self._artifact(request, source, context)
        return KnowledgeFileGrant(
            action=request.action,
            knowledge_id=request.knowledge_id,
            file_id=request.file_id,
            file_version=request.file_version,
            filename=file["original_filename"],
            source=source,
            collection=knowledge["index_name"],
            embedding_model_id=knowledge.get("embedding_model_id"),
            artifact=request.artifact,
            parser_version=request.parser_version,
        )

    def _artifact(self, request, source, context):
        terms = tuple(
            Comparison(name, "eq", value)
            for name, value in {
                "scope_kind": "knowledge",
                "knowledge_id": request.knowledge_id,
                "file_id": request.file_id,
                "file_version": request.file_version,
                "user_id": self.user_id,
                "status": "completed",
                "parser_version": request.parser_version,
            }.items()
        )
        cursor = None
        while True:
            page = self.jobs.query(
                "file_cleanse_jobs",
                RecordQuery(where=Junction("and", terms)),
                PageRequest(limit=100, cursor=cursor),
                context=context,
            )
            for row in page.items:
                if (
                    row["artifact"] == request.artifact.model_dump(mode="json")
                    and parse_cleanse_request(row).source == source
                ):
                    return
            if page.next_cursor is None:
                raise ScopeDenied()
            cursor = page.next_cursor


def authorize_knowledge(request, actor, *, context):
    with knowledge_cleanse_ports(actor.tenant_id, actor.user_id, context=context) as (
        jobs,
        resources,
    ):
        return KnowledgeAuthorization(jobs, resources, user_id=actor.user_id).authorize(
            request, context=context
        )
