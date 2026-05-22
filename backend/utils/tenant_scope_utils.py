"""Tenant visibility helpers for multi-tenant resource isolation."""

from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Query

from consts.const import ASSET_OWNER_TENANT_ID
from consts.model import ToolSourceEnum

# Prefabricated skill records use source=custom (global, not tenant-owned).
PREFAB_SKILL_SOURCE = "custom"


def normalize_tenant_id(tenant_id: Optional[str]) -> Optional[str]:
    """Map legacy empty tenant_id to ASSET_OWNER virtual tenant."""
    if tenant_id == "":
        return ASSET_OWNER_TENANT_ID
    return tenant_id


def is_asset_owner_tenant(tenant_id: Optional[str]) -> bool:
    """Return True when the caller is an ASSET_OWNER (virtual tenant scope)."""
    return tenant_id in (ASSET_OWNER_TENANT_ID, "")


def is_tenant_scoped_user(tenant_id: Optional[str]) -> bool:
    """Return True when the caller belongs to a real tenant."""
    if tenant_id is None or tenant_id == "":
        return False
    return tenant_id != ASSET_OWNER_TENANT_ID


def _asset_owner_column_match(column):
    """Match asset-owner scope including legacy empty-string rows."""
    return or_(column == ASSET_OWNER_TENANT_ID, column == "")


def _exclude_asset_owner_column(column):
    """Exclude asset-owner scoped rows from tenant-admin queries."""
    return (
        column != ASSET_OWNER_TENANT_ID,
        column != "",
        column.isnot(None),
    )


def apply_model_tenant_filter(stmt, tenant_id: Optional[str], model_cls):
    """
    Scope model records by tenant.

    - ASSET_OWNER: only records with tenant_id in (ASSET_OWNER, legacy "").
    - Tenant admin: only records matching their tenant_id (excludes asset-owner assets).
    """
    if tenant_id is None:
        return stmt
    if is_asset_owner_tenant(tenant_id):
        return stmt.where(_asset_owner_column_match(model_cls.tenant_id))
    return stmt.where(
        model_cls.tenant_id == tenant_id,
        *_exclude_asset_owner_column(model_cls.tenant_id),
    )


def apply_agent_tenant_filter(query: Query, tenant_id: Optional[str], agent_cls) -> Query:
    """Scope agent records; same rules as models."""
    if tenant_id is None:
        return query
    if is_asset_owner_tenant(tenant_id):
        return query.filter(_asset_owner_column_match(agent_cls.tenant_id))
    return query.filter(
        agent_cls.tenant_id == tenant_id,
        *_exclude_asset_owner_column(agent_cls.tenant_id),
    )


def apply_tool_info_visibility_filter(
    query: Query, tenant_id: Optional[str], tool_cls
) -> Query:
    """
    Scope ToolInfo listing.

    - ASSET_OWNER: tools with author in (ASSET_OWNER, legacy "").
    - Tenant admin: tools owned by the tenant OR prefabricated local tools (source=local).
    """
    if tenant_id is None:
        return query
    if is_asset_owner_tenant(tenant_id):
        return query.filter(_asset_owner_column_match(tool_cls.author))
    return query.filter(
        or_(
            tool_cls.author == tenant_id,
            tool_cls.source == ToolSourceEnum.LOCAL.value,
        )
    )

