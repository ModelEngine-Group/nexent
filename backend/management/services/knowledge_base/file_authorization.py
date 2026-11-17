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

    def identity(self, *, context):
        member = self._one("cleanse_memberships", "user_id", self.user_id, context)
        account = self._one("cleanse_accounts", "user_id", self.user_id, context)
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
        return {**member, "user_roles": account["user_roles"]}, groups

    def resolve_knowledges(self, knowledge_ids, *, edit, context):
        member, groups = self.identity(context=context)
        page = self.records.query(
            "cleanse_knowledge", RecordQuery(where=Comparison("knowledge_id", "in", knowledge_ids)),
            PageRequest(limit=len(knowledge_ids)), context=context,
        )
        rows = {row["knowledge_id"]: row for row in page.items}
        if (page.next_cursor or set(rows) != set(knowledge_ids) or len(page.items) != len(knowledge_ids)
            or any(not row["index_name"] for row in rows.values())
            or len({row["index_name"] for row in rows.values()}) != len(rows)):
            raise ScopeDenied()
        permissions = resolve_knowledge_permissions(
            list(rows.values()),
            self.user_id,
            self.records.scope.tenant_id,
            member,
            groups,
            speed_mode=False,
        )
        for row in rows.values():
            permission = permissions[row["index_name"]]
            if permission is None or edit and permission not in {"EDIT", "CREATOR"}:
                raise ScopeDenied()
        return [rows[key] for key in knowledge_ids]

    def resolve_knowledge(self, knowledge_id, *, edit, context):
        return self.resolve_knowledges([knowledge_id], edit=edit, context=context)[0]

    def resolve(self, reference, *, edit, context, history=False):
        knowledge = self.resolve_knowledge(reference.knowledge_id, edit=edit, context=context)
        file = self._one(
            "knowledge_file_history" if history else "cleanse_files", "file_id", reference.file_id, context,
        )
        allowed = {"UPLOADED", "PROCESSING", "FORWARDING", "FAILED", "COMPLETED"}
        if history:
            allowed |= {"DELETE_REQUESTED", "DELETED"}
        if (file["knowledge_id"] != reference.knowledge_id or file["status"] not in allowed
            or file["source_generation"] is None or (
                file["source_generation"] < reference.file_version if history
                else file["source_generation"] != reference.file_version
            )):
            raise ScopeDenied()
        return file, knowledge
