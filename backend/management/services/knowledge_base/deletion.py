# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Public document deletion delegates execution to the persistent phase owner."""

from management.services.knowledge_base.base_deletion_public import (
    project_base_deletion,
)
from management.services.knowledge_base.deletion_public import project_deletion
from management.services.knowledge_base.ingestion_dispatch import (
    default_base_deletion_coordinator,
    default_coordinator,
    default_deletion_coordinator,
)
from management.services.knowledge_base.management import KnowledgeBaseManagementService

from infrastructure.agentos_identity import ServicePrincipal


class KnowledgeBaseDocumentDeletionService(KnowledgeBaseManagementService):
    @staticmethod
    async def delete_knowledge_base(index_name, *, requested_by, tenant_id):
        actor = ServicePrincipal(requested_by, tenant_id)
        coordinator = default_base_deletion_coordinator(default_coordinator())
        row = await coordinator.request(index_name, actor)
        return project_base_deletion(index_name, row)

    @staticmethod
    async def delete_document_by_scope(
        index_name, path_or_url, scope, *, requested_by, tenant_id, file_id=None, remove_tags=False,
    ):
        actor = ServicePrincipal(requested_by, tenant_id)
        coordinator = default_deletion_coordinator(default_coordinator())
        row = await coordinator.request(
            index_name, path_or_url, scope, actor, file_id=file_id, remove_tags=remove_tags,
        )
        return project_deletion(row)
