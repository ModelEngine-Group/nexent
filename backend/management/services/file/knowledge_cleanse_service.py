# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""KB-only admission; durable jobs are dispatched separately after record commit."""

from contracts.constants import environment
from contracts.knowledge_cleanse import KnowledgeCleanseLookup, KnowledgeCleanseRequest
from management.services.file.cleanse_authorization import KnowledgeCleanseAuthorization
from management.services.file.cleanse_cancellation import (
    cancel_knowledge_executions,
    require_knowledge_cleanup,
)
from management.services.file.cleanse_service import CleanseService
from management.services.file.knowledge_cleanse_release import (
    release_knowledge_artifacts,
)

from infrastructure.knowledge_cleanse import knowledge_cleanse_ports


class KnowledgeCleanseService(CleanseService):
    request_type = KnowledgeCleanseRequest
    lookup_type = KnowledgeCleanseLookup
    authorization_type = KnowledgeCleanseAuthorization

    def _ports(self, tenant_id, user_id, *, context):
        return knowledge_cleanse_ports(tenant_id, user_id, context=context)

    def cleanup_file(self, reference, *, tenant_id, user_id, context):
        with self._records(tenant_id, user_id, context) as (jobs, resources):
            require_knowledge_cleanup(jobs, resources, reference, user_id=user_id, context=context, releasing=True)
            result = cancel_knowledge_executions(jobs, resources, reference, user_id=user_id, context=context)
            result['artifacts_released'] = result['execution_drained'] and release_knowledge_artifacts(
                jobs, resources, reference, user_id=user_id, context=context,
                limit=environment.MAX_KNOWLEDGE_FILE_SIZE_BYTES,
            )
            return result
