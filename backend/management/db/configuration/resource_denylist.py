# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Persistence for tool denylist settings in the existing configuration tables."""

from sqlalchemy import case, func, or_, select, text

from contracts.constants.constants import MANAGED_KNOWLEDGE_TOOL_NAMES, SYSTEM_MANAGED_TOOL_NAMES
from infrastructure.rdb.mcp_execution_records import McpRecord, ToolInfo
from infrastructure.rdb.skill_execution_records import SkillInfo
from infrastructure.rdb.tenant_config_record import TenantConfig
from infrastructure.system_configuration.models import RESOURCE_DENYLIST_KEY, SystemConfiguration


def _global_config_query(column):
    return select(column).where(
        SystemConfiguration.configuration_key == RESOURCE_DENYLIST_KEY,
        SystemConfiguration.delete_flag == "N",
    )


def _tenant_config_query(column, tenant_id):
    return select(column).where(
        TenantConfig.tenant_id == tenant_id,
        TenantConfig.config_key == RESOURCE_DENYLIST_KEY,
        TenantConfig.user_id.is_(None),
        TenantConfig.delete_flag == "N",
    )


def global_config(session):
    return session.scalars(_global_config_query(SystemConfiguration)).one_or_none()


def tenant_config(session, tenant_id):
    return session.scalars(_tenant_config_query(TenantConfig, tenant_id)).one_or_none()


def policy_values(session, tenant_id):
    """Read both rule sets from the same database snapshot."""
    global_value = _global_config_query(SystemConfiguration.configuration_value).scalar_subquery()
    tenant_value = _tenant_config_query(func.coalesce(TenantConfig.config_value, ""), tenant_id).scalar_subquery()
    return session.execute(select(global_value, tenant_value)).one()


def lock_config(session, tenant_id):
    scope = "global" if tenant_id is None else f"tenant:{tenant_id}"
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"{RESOURCE_DENYLIST_KEY}:{scope}"},
    )


def tool_catalog(session, tenant_id=None):
    criteria = (
        ToolInfo.delete_flag == "N",
        ToolInfo.is_available.is_(True),
        ToolInfo.name.is_not(None),
        ToolInfo.is_user_selectable.is_not(False),
        ToolInfo.name.not_in(SYSTEM_MANAGED_TOOL_NAMES | MANAGED_KNOWLEDGE_TOOL_NAMES),
        or_(ToolInfo.origin_name.is_(None), ToolInfo.origin_name.not_in(MANAGED_KNOWLEDGE_TOOL_NAMES)),
    )
    if tenant_id is None:
        service = case((ToolInfo.source == "mcp", ToolInfo.usage), else_=None)
        return session.execute(
            select(ToolInfo.name, ToolInfo.source, service.label("usage"),
                   func.min(func.nullif(ToolInfo.description, "")).label("description"))
            .where(*criteria).group_by(ToolInfo.name, ToolInfo.source, service)
            .order_by(ToolInfo.name, ToolInfo.source, service)
        ).mappings().all()
    return session.execute(
        select(ToolInfo.tool_id, ToolInfo.name, ToolInfo.source, ToolInfo.usage, ToolInfo.description)
        .where(*criteria, ToolInfo.author == tenant_id)
        .order_by(ToolInfo.name, ToolInfo.usage, ToolInfo.tool_id)
    ).mappings().all()


def resource_catalog(session, tenant_id=None):
    """Return active MCP and skill definitions without credentials or execution content."""
    resources = []
    for model, kind, id_column, name_column, description_column in (
        (McpRecord, "mcp", McpRecord.mcp_id, McpRecord.mcp_name, McpRecord.description),
        (SkillInfo, "skill", SkillInfo.skill_id, SkillInfo.skill_name, SkillInfo.skill_description),
    ):
        query = select(id_column, name_column, description_column).where(model.delete_flag == "N")
        if tenant_id is not None:
            query = query.where(or_(model.tenant_id == tenant_id, model.tenant_id.is_(None))
                                if kind == "skill" else model.tenant_id == tenant_id)
        seen = set()
        for resource_id, name, description in session.execute(query.order_by(name_column, id_column)):
            if not name:
                continue
            key = f"{kind}:{name if tenant_id is None else resource_id}"
            if key not in seen:
                resources.append({"key": key, "name": name, "description": description or "",
                                  "resource_type": kind})
                seen.add(key)
    return resources


def blocked_mcp_tool_ids(session, tenant_id, global_names, mcp_ids):
    """Resolve service policies to this tenant's current tool definitions on every read."""
    names = set(global_names)
    if mcp_ids:
        names.update(session.scalars(select(McpRecord.mcp_name).where(
            McpRecord.mcp_id.in_(mcp_ids), McpRecord.tenant_id == tenant_id,
            McpRecord.delete_flag == "N",
        )).all())
    if not names:
        return set()
    return set(session.scalars(select(ToolInfo.tool_id).where(
        ToolInfo.author == tenant_id, ToolInfo.source == "mcp", ToolInfo.usage.in_(names),
        ToolInfo.delete_flag == "N",
    )).all())


def save_config(session, tenant_id, row, value, actor):
    if row is None:
        if tenant_id is None:
            session.add(SystemConfiguration(
                configuration_key=RESOURCE_DENYLIST_KEY, configuration_value=value,
                created_by=actor, updated_by=actor, delete_flag="N",
            ))
        else:
            session.add(TenantConfig(
                tenant_id=tenant_id, config_key=RESOURCE_DENYLIST_KEY,
                value_type="single", config_value=value,
                created_by=actor, updated_by=actor, delete_flag="N",
            ))
        return
    if tenant_id is None:
        row.configuration_value = value
    else:
        row.config_value = value
    row.updated_by = actor
    row.update_time = func.now()
