# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Display-only model metadata never borrows a tenant identity or initializes an adapter."""

import logging

from contracts.knowledge_collections import KnowledgeModelDisplay
from nexent.storage.errors import DeadlineExceeded, OperationCancelled, ScopeDenied

from infrastructure.knowledge_model_display import (
    DISPLAY,
    knowledge_model_display_ports,
)

logger = logging.getLogger(__name__)


def knowledge_model_display(actor, grant, *, context, ports=knowledge_model_display_ports):
    context.remaining()
    if grant.embedding_model_id is None:
        return KnowledgeModelDisplay()
    try:
        with ports(actor, grant, context=context) as records:
            scope = records.scope
            if (scope.service_role != 'runtime' or scope.system or scope.resource_prefix
                or scope.actor_id != actor.user_id or scope.tenant_id != grant.resource_tenant_id
                or scope.namespaces != {DISPLAY}):
                raise ScopeDenied()
            row = records.get(DISPLAY, grant.embedding_model_id, context=context)
            context.remaining()
            if row is None:
                return KnowledgeModelDisplay()
            return KnowledgeModelDisplay(display_name=row['display_name'], is_multimodal=row['model_type'] == 'multi_embedding')
    except (DeadlineExceeded, OperationCancelled, ScopeDenied):
        raise
    except Exception as error:  # noqa: BLE001 - Preserve the existing display-only best-effort lookup.
        logger.warning('knowledge_model_display_unavailable operation_id=%s exception_type=%s',
                       context.operation_id, type(error).__name__)
        return KnowledgeModelDisplay()
