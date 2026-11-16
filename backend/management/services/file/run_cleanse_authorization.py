# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Current actor and exact owner/run source scope for the reverse FileCleanse API."""

from contracts.agentos_knowledge import FileCleanseLookup, FileCleanseRequest
from contracts.knowledge_cleanse import parse_cleanse_request
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import Comparison, PageRequest, RecordQuery


class RunCleanseAuthorization:
    def __init__(self, records, *, user_id):
        if not isinstance(user_id, str) or not 0 < len(user_id) <= 100:
            raise ScopeDenied()
        self.records, self.user_id = records, user_id

    def authorize(self, request, *, context):
        if not isinstance(request, (FileCleanseRequest, FileCleanseLookup)):
            raise ScopeDenied()
        for dataset in ("cleanse_memberships", "cleanse_accounts"):
            page = self.records.query(
                dataset, RecordQuery(where=Comparison("user_id", "eq", self.user_id)),
                PageRequest(limit=2), context=context,
            )
            if page.next_cursor or len(page.items) != 1:
                raise ScopeDenied()
            identity = page.items[0]
            if (identity["user_id"] != self.user_id or identity["tenant_id"] != self.records.scope.tenant_id
                    or dataset == "cleanse_accounts" and not identity["user_roles"]):
                raise ScopeDenied()
        if isinstance(request, FileCleanseRequest):
            if (request.source.space != "files" or request.filename in {".", ".."}
                    or any(char in request.filename for char in ("/", "\\", "\x00"))
                    or not request.source.key.startswith((
                        f"attachments/{self.user_id}/", f"skill-files/{self.user_id}/",
                        f"workspace/{self.user_id}/{request.run_id}/outputs/",
                    ))):
                raise ScopeDenied()
            return request.source
        return None

    def authorize_execution(self, row, request, *, context):
        if (row["tenant_id"] != self.records.scope.tenant_id or row["user_id"] != self.user_id
                or parse_cleanse_request(row) != request):
            raise ScopeDenied()
        return self.authorize(request, context=context)
