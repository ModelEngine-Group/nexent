# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management attests file scope and confirmed cleansing outputs to Runtime."""

from contracts.agentos_knowledge import (
    KnowledgeAuthorizationRequest,
    KnowledgeFileGrant,
    ObjectReference,
)
from contracts.knowledge_cleanse import knowledge_artifact_prefix, parse_cleanse_request
from contracts.knowledge_deletion import KnowledgeDeletionIntent
from management.services.knowledge_base.file_authorization import (
    KnowledgeFileAuthorization,
)
from management.services.knowledge_base.owner_cleanup import has_cleanup_authority
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import Comparison, Junction, PageRequest, RecordQuery
from pydantic import ValidationError

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
            inspect_cleanup=request.action == 'inspect',
            context=context,
        )
        if request.action == 'inspect' and has_cleanup_authority(knowledge, self.user_id, self.resources.records.scope.tenant_id):
            self._require_cleanup_inspection(file, knowledge, request)
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

    def _require_cleanup_inspection(self, file, knowledge, request):
        try:
            intent = KnowledgeDeletionIntent.model_validate(file['deletion_request'])
        except ValidationError:
            raise ScopeDenied() from None
        if (intent.scope != 'full' or intent.user_id != self.user_id or file['delete_flag'] != 'N'
                or file['status'] not in {'DELETE_REQUESTED', 'DELETED'}
                or intent.index_name != knowledge['index_name'] or intent.file_version != file['source_generation']
                or intent.filename != file['original_filename'] or intent.object_name != file['object_name']
                or any(getattr(intent, field) != getattr(request, field) for field in ('knowledge_id', 'file_id', 'file_version'))):
            raise ScopeDenied()
        expected = ([intent.source.space, intent.source.key, intent.source.version, intent.source.sha256]
                    if intent.source is not None else [None] * 4)
        if [file[field] for field in ('source_space', 'source_key', 'source_revision', 'source_sha256')] != expected:
            raise ScopeDenied()

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
                    if request.artifact.key.startswith('knowledge-cleanse/'):
                        try:
                            knowledge_artifact_prefix(request, request.artifact, job_id=row['job_id'])
                        except (TypeError, ValueError):
                            raise ScopeDenied() from None
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
