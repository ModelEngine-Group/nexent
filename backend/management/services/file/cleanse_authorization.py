# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Live KB resource authorization using scoped records and the existing pure DAC."""

from contracts.agentos_knowledge import ObjectReference
from contracts.knowledge_cleanse import (
    KnowledgeCleanseLookup,
    KnowledgeCleanseRequest,
    parse_cleanse_request,
)
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import Comparison, PageRequest, RecordQuery
from permissions.dac import resolve_knowledge_permissions


class KnowledgeCleanseAuthorization:
    def __init__(self, records, *, user_id):
        if not isinstance(user_id, str) or not 0 < len(user_id) <= 100:
            raise ScopeDenied()
        self.records = records
        self.user_id = user_id

    def _rows(self, dataset, field, value, context, *, limit=2):
        page = self.records.query(
            dataset,
            RecordQuery(where=Comparison(field, "eq", value)),
            PageRequest(limit=limit),
            context=context,
        )
        if page.next_cursor:
            raise ScopeDenied()
        return page.items

    def _one(self, dataset, field, value, context):
        rows = self._rows(dataset, field, value, context)
        if len(rows) != 1:
            raise ScopeDenied()
        return rows[0]

    def authorize(self, request, *, context):
        if not isinstance(request, (KnowledgeCleanseRequest, KnowledgeCleanseLookup)):
            raise ScopeDenied()
        member = self._one("cleanse_memberships", "user_id", self.user_id, context)
        account = self._one("cleanse_accounts", "user_id", self.user_id, context)
        knowledge = self._one(
            "cleanse_knowledge", "knowledge_id", request.knowledge_id, context
        )
        if not knowledge["index_name"]:
            raise ScopeDenied()
        file = self._one("cleanse_files", "file_id", request.file_id, context)
        if (
            file["knowledge_id"] != request.knowledge_id
            or file["source_generation"] != request.file_version
            or file["status"]
            not in {"UPLOADED", "PROCESSING", "FORWARDING", "FAILED", "COMPLETED"}
        ):
            raise ScopeDenied()
        links = self._rows(
            "cleanse_group_memberships", "user_id", self.user_id, context, limit=1000
        )
        groups = []
        if links:
            page = self.records.query(
                "cleanse_groups",
                RecordQuery(
                    where=Comparison(
                        "group_id", "in", list({link["group_id"] for link in links})
                    )
                ),
                PageRequest(limit=1000),
                context=context,
            )
            if page.next_cursor:
                raise ScopeDenied()
            groups = [group["group_id"] for group in page.items]
        permission = resolve_knowledge_permissions(
            [knowledge],
            self.user_id,
            self.records.scope.tenant_id,
            {**member, "user_roles": account["user_roles"]},
            groups,
            speed_mode=False,
        )[knowledge["index_name"]]
        if (
            permission is None
            or isinstance(request, KnowledgeCleanseRequest)
            and permission not in {"EDIT", "CREATOR"}
        ):
            raise ScopeDenied()
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
