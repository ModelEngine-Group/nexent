# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Live file and KB permission resolution shared by cleansing and AgentOS grants."""

from nexent.storage.errors import ScopeDenied
from nexent.storage.models import Comparison, PageRequest, RecordQuery
from permissions.dac import resolve_knowledge_permissions


class KnowledgeFileAuthorization:
    def __init__(self, records, *, user_id):
        if not isinstance(user_id, str) or not 0 < len(user_id) <= 100:
            raise ScopeDenied()
        self.records, self.user_id = records, user_id

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

    def resolve(self, reference, *, edit, context, history=False):
        member = self._one("cleanse_memberships", "user_id", self.user_id, context)
        account = self._one("cleanse_accounts", "user_id", self.user_id, context)
        knowledge = self._one(
            "cleanse_knowledge", "knowledge_id", reference.knowledge_id, context
        )
        file = self._one(
            "knowledge_file_history" if history else "cleanse_files",
            "file_id",
            reference.file_id,
            context,
        )
        allowed = {"UPLOADED", "PROCESSING", "FORWARDING", "FAILED", "COMPLETED"}
        if history:
            allowed |= {"DELETE_REQUESTED", "DELETED"}
        if (
            not knowledge["index_name"]
            or file["knowledge_id"] != reference.knowledge_id
            or file["status"] not in allowed
            or file["source_generation"] is None
            or (
                file["source_generation"] < reference.file_version
                if history
                else file["source_generation"] != reference.file_version
            )
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
        if permission is None or edit and permission not in {"EDIT", "CREATOR"}:
            raise ScopeDenied()
        return file, knowledge
