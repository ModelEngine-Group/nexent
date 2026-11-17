# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read an explicit metadata allowlist without fetching credentials or content."""

from sqlalchemy import func, literal, select, union_all

from management.db.client import get_db_session
from management.db.models import AgentInfo, KnowledgeRecord, McpRecord, ModelRecord
from permissions.resource_access import require_inventory_scope


def resource_inventory(user, tenant_id=None, page=1, page_size=20):
    tenant = require_inventory_scope(user, tenant_id)
    definitions = (
        (ModelRecord, ModelRecord.model_id, ModelRecord.model_name, "model"),
        (McpRecord, McpRecord.mcp_id, McpRecord.mcp_name, "mcp"),
        (AgentInfo, AgentInfo.agent_id, AgentInfo.name, "agent"),
        (KnowledgeRecord, KnowledgeRecord.knowledge_id, KnowledgeRecord.knowledge_name, "knowledge"),
    )
    statements = []
    for model, identity, name, kind in definitions:
        query = select(literal(kind).label("kind"), identity.label("id"), name.label("name"), model.tenant_id)
        query = query.where(model.delete_flag == "N")
        if tenant is not None:
            query = query.where(model.tenant_id == tenant)
        if model is AgentInfo:
            query = query.where(model.version_no == 0)
        statements.append(query)
    inventory = union_all(*statements).subquery()

    with get_db_session() as session:
        total = session.scalar(select(func.count()).select_from(inventory))
        rows = (
            session.execute(
                select(inventory)
                .order_by(inventory.c.kind, inventory.c.tenant_id, inventory.c.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            .mappings()
            .all()
        )
        return {"items": [dict(row) for row in rows], "total": total, "page": page, "page_size": page_size}
