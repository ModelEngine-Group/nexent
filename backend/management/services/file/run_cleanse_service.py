# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Run-file cleansing admission; no parser, broker, model or Runtime table access."""

from contracts.agentos_knowledge import FileCleanseLookup, FileCleanseRequest
from management.services.file.cleanse_service import CleanseService
from management.services.file.run_cleanse_authorization import RunCleanseAuthorization

from infrastructure.knowledge_cleanse import knowledge_cleanse_ports


class FileCleanseService(CleanseService):
    request_type = FileCleanseRequest
    lookup_type = FileCleanseLookup
    authorization_type = RunCleanseAuthorization

    def _ports(self, tenant_id, user_id, *, context):
        return knowledge_cleanse_ports(
            tenant_id, user_id, context=context,
            resource_namespaces={"cleanse_memberships", "cleanse_accounts"},
        )
