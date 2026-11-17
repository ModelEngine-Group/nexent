# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Authorize versioned content using current KB permissions and completed manifests."""

import re

from contracts.agentos_knowledge import (
    KnowledgeContentGrant,
    KnowledgeContentRequest,
    ObjectReference,
)
from contracts.knowledge_cleanse import parse_cleanse_request
from management.services.knowledge_base.file_authorization import (
    KnowledgeFileAuthorization,
)
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import Comparison, Junction, PageRequest, RecordQuery

from infrastructure.knowledge_cleanse import knowledge_cleanse_ports
from infrastructure.knowledge_content import read_knowledge_manifest


class KnowledgeContentAuthorization:
    def __init__(self, jobs, resources, load_manifest, *, user_id):
        self.jobs = jobs
        self.resources = KnowledgeFileAuthorization(resources, user_id=user_id)
        self.load_manifest = load_manifest

    def authorize(self, request, *, context):
        if not isinstance(request, KnowledgeContentRequest):
            raise ScopeDenied()
        file, _ = self.resources.resolve(request, edit=False, context=context)
        try:
            source = ObjectReference(
                space=file["source_space"],
                key=file["source_key"],
                version=file["source_revision"],
                sha256=file["source_sha256"],
            )
        except ValueError:
            raise ScopeDenied() from None
        if source.space != "files":
            raise ScopeDenied()
        selected = source
        if request.image_ref is not None:
            if request.image_ref.space != "files" or not re.fullmatch(
                "images/"
                + source.sha256
                + "/"
                + request.image_ref.sha256
                + r"\.(?:png|jpg|jpeg|gif|webp|bmp|tiff)",
                request.image_ref.key,
            ):
                raise ScopeDenied()
            self._image(request, source, context)
            selected = request.image_ref
        return KnowledgeContentGrant(
            **request.model_dump(),
            object_ref=selected,
            filename=file["original_filename"],
        )

    def _image(self, request, source, context):
        terms = tuple(
            Comparison(name, "eq", value)
            for name, value in {
                "scope_kind": "knowledge",
                "knowledge_id": request.knowledge_id,
                "file_id": request.file_id,
                "file_version": request.file_version,
                "status": "completed",
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
                cleanse = parse_cleanse_request(row)
                if cleanse.source != source:
                    continue
                reference = ObjectReference.model_validate(row["artifact"])
                manifest = self.load_manifest(reference, context=context)
                if (
                    manifest.source != source
                    or manifest.parser_version != row["parser_version"]
                ):
                    raise ScopeDenied()
                if any(
                    block.kind == "image" and block.object_ref == request.image_ref
                    for block in manifest.blocks
                ):
                    return
            if page.next_cursor is None:
                raise ScopeDenied()
            cursor = page.next_cursor


def authorize_knowledge_content(request, actor, *, context):
    def load_manifest(reference, *, context):
        return read_knowledge_manifest(actor, reference, context=context)

    with knowledge_cleanse_ports(actor.tenant_id, actor.user_id, context=context) as (
        jobs,
        resources,
    ):
        return KnowledgeContentAuthorization(
            jobs, resources, load_manifest, user_id=actor.user_id
        ).authorize(request, context=context)
