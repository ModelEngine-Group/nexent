# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management operations that coordinate AIDP HTTP and local bindings."""

import logging

from ext_components.aidp.services import aidp_service
from infrastructure.rdb.client import get_db_session
from management.db.agent.repository import query_knowledge_binding_agents
from management.db.conversation.repository import remove_conversation_knowledge_bindings
from management.db.tool.repository import remove_tool_knowledge_references


logger = logging.getLogger(__name__)


def get_bound_agents(kds_ids: list[str], *, tenant_id: str) -> dict:
    return {"agents": query_knowledge_binding_agents(kds_ids=kds_ids, tenant_id=tenant_id)}


def delete_aidp_kb_impl(server_url: str, api_key: str, kds_id: str) -> bool:
    """Clean up bindings after a successful or already-absent upstream deletion."""
    deleted = aidp_service.delete_aidp_kb_impl(server_url, api_key, kds_id)
    if deleted:
        try:
            with get_db_session() as session:
                remove_tool_knowledge_references(session, kds_ids=[kds_id])
                remove_conversation_knowledge_bindings(session, kds_ids=[kds_id])
        except Exception as exc:  # Binding cleanup must not hide a successful upstream deletion.
            logger.warning("Failed to clean up bindings for deleted AIDP knowledge base '%s': %s", kds_id, exc)
    return deleted
