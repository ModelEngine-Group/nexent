# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read an explicit metadata allowlist without fetching credentials or content."""

from sqlalchemy import func, literal, select, union_all

from infrastructure.rdb.agent_monitoring import monitored_agent_predicate
from infrastructure.rdb.client import get_db_session
from management.db.agent.models import AgentInfo
from management.db.knowledge_base.models import KnowledgeRecord
from management.db.mcp.models import McpRecord
from management.db.model.models import ModelRecord
from management.utils.serialization import convert_string_to_list
from permissions.resource_access import require_inventory_scope


def resource_inventory(user, tenant_id=None, page=1, page_size=20):
    tenant = require_inventory_scope(user, tenant_id)
    definitions = (
        (ModelRecord, ModelRecord.model_id, ModelRecord.model_name, "model", None),
        (McpRecord, McpRecord.mcp_id, McpRecord.mcp_name, "mcp", None),
        (AgentInfo, AgentInfo.agent_id, AgentInfo.name, "agent", AgentInfo.group_ids),
        (KnowledgeRecord, KnowledgeRecord.knowledge_id, KnowledgeRecord.knowledge_name, "knowledge", None),
    )
    statements = []
    for model, identity, name, kind, group_ids_column in definitions:
        group_expression = group_ids_column if group_ids_column is not None else literal(None)
        query = select(
            literal(kind).label("kind"),
            identity.label("id"),
            name.label("name"),
            model.tenant_id,
            group_expression.label("group_ids"),
        )
        query = query.where(model.delete_flag == "N")
        if tenant is not None:
            query = query.where(model.tenant_id == tenant)
        if model is AgentInfo:
            query = query.where(model.version_no == 0, monitored_agent_predicate())
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
        items = []
        for row in rows:
            item = dict(row)
            raw_groups = item.pop("group_ids")
            if item["kind"] == "agent":
                item["group_ids"] = convert_string_to_list(raw_groups)
            items.append(item)
        return {"items": items, "total": total, "page": page, "page_size": page_size}
