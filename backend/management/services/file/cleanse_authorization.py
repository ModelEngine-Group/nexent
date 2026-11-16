# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Current source checks for cleansing on top of the shared Management DAC."""

from contracts.agentos_knowledge import ObjectReference
from contracts.knowledge_cleanse import (
    KnowledgeCleanseLookup,
    KnowledgeCleanseRequest,
    parse_cleanse_request,
)
from management.services.knowledge_base.file_authorization import (
    KnowledgeFileAuthorization,
)
from nexent.storage.errors import ScopeDenied


class KnowledgeCleanseAuthorization(KnowledgeFileAuthorization):
    def authorize(self, request, *, context):
        if not isinstance(request, (KnowledgeCleanseRequest, KnowledgeCleanseLookup)):
            raise ScopeDenied()
        file, _ = self.resolve(
            request, edit=isinstance(request, KnowledgeCleanseRequest), context=context
        )
        try:
            source = ObjectReference(
                space=file["source_space"],
                key=file["source_key"],
                version=file["source_revision"],
                sha256=file["source_sha256"],
            )
        except ValueError:
            raise ScopeDenied() from None
        if isinstance(request, KnowledgeCleanseRequest) and (
            request.source != source or request.filename != file["original_filename"]
        ):
            raise ScopeDenied()
        return source

    def authorize_execution(self, row, request, *, context):
        if (
            row["tenant_id"] != self.records.scope.tenant_id
            or row["user_id"] != self.user_id
            or parse_cleanse_request(row) != request
        ):
            raise ScopeDenied()
        return self.authorize(request, context=context)
