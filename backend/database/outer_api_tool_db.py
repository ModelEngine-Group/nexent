"""
Database access layer for outer API tools (OpenAPI to MCP conversion).
"""

import logging
from typing import List, Optional, Dict, Any

from database.client import get_db_session, filter_property, as_dict
from database.db_models import OuterApiTool


logger = logging.getLogger("outer_api_tool_db")


def create_outer_api_tool(tool_data: Dict[str, Any], tenant_id: str, user_id: str) -> OuterApiTool:
    """
    Create a new outer API tool record.

    Args:
        tool_data: Dictionary containing tool information
        tenant_id: Tenant ID for multi-tenancy
        user_id: User ID for audit

    Returns:
        Created OuterApiTool object
    """
    tool_dict = tool_data.copy()
    tool_dict["tenant_id"] = tenant_id
    tool_dict["created_by"] = user_id
    tool_dict["updated_by"] = user_id
    tool_dict.setdefault("is_available", True)

    with get_db_session() as session:
        new_tool = OuterApiTool(**filter_property(tool_dict, OuterApiTool))
        session.add(new_tool)
        session.flush()
        return as_dict(new_tool)


def batch_create_outer_api_tools(
    tools_data: List[Dict[str, Any]],
    tenant_id: str,
    user_id: str
) -> List[Dict[str, Any]]:
    """
    Batch create outer API tool records.

    Args:
        tools_data: List of tool data dictionaries
        tenant_id: Tenant ID for multi-tenancy
        user_id: User ID for audit

    Returns:
        List of created tool dictionaries
    """
    results = []
    with get_db_session() as session:
        for tool_data in tools_data:
            tool_dict = tool_data.copy()
            tool_dict["tenant_id"] = tenant_id
            tool_dict["created_by"] = user_id
            tool_dict["updated_by"] = user_id
            tool_dict.setdefault("is_available", True)

            new_tool = OuterApiTool(**filter_property(tool_dict, OuterApiTool))
            session.add(new_tool)
            results.append(tool_dict)
        session.flush()
    return results


def query_outer_api_tools_by_tenant(tenant_id: str) -> List[Dict[str, Any]]:
    """
    Query all outer API tools for a tenant.

    Args:
        tenant_id: Tenant ID

    Returns:
        List of tool dictionaries
    """
    with get_db_session() as session:
        tools = session.query(OuterApiTool).filter(
            OuterApiTool.tenant_id == tenant_id,
            OuterApiTool.delete_flag != 'Y'
        ).all()
        return [as_dict(tool) for tool in tools]


def query_available_outer_api_tools(tenant_id: str) -> List[Dict[str, Any]]:
    """
    Query all available outer API tools for a tenant.

    Args:
        tenant_id: Tenant ID

    Returns:
        List of available tool dictionaries
    """
    with get_db_session() as session:
        tools = session.query(OuterApiTool).filter(
            OuterApiTool.tenant_id == tenant_id,
            OuterApiTool.delete_flag != 'Y',
            OuterApiTool.is_available == True
        ).all()
        return [as_dict(tool) for tool in tools]


def query_outer_api_tool_by_id(tool_id: int, tenant_id: str) -> Optional[Dict[str, Any]]:
    """
    Query outer API tool by ID.

    Args:
        tool_id: Tool ID
        tenant_id: Tenant ID

    Returns:
        Tool dictionary or None
    """
    with get_db_session() as session:
        tool = session.query(OuterApiTool).filter(
            OuterApiTool.id == tool_id,
            OuterApiTool.tenant_id == tenant_id,
            OuterApiTool.delete_flag != 'Y'
        ).first()
        return as_dict(tool) if tool else None


def query_outer_api_tool_by_name(name: str, tenant_id: str) -> Optional[Dict[str, Any]]:
    """
    Query outer API tool by name.

    Args:
        name: Tool name
        tenant_id: Tenant ID

    Returns:
        Tool dictionary or None
    """
    with get_db_session() as session:
        tool = session.query(OuterApiTool).filter(
            OuterApiTool.name == name,
            OuterApiTool.tenant_id == tenant_id,
            OuterApiTool.delete_flag != 'Y'
        ).first()
        return as_dict(tool) if tool else None


def update_outer_api_tool(
    tool_id: int,
    tool_data: Dict[str, Any],
    tenant_id: str,
    user_id: str
) -> Optional[Dict[str, Any]]:
    """
    Update an outer API tool record.

    Args:
        tool_id: Tool ID
        tool_data: Dictionary containing updated tool information
        tenant_id: Tenant ID
        user_id: User ID for audit

    Returns:
        Updated tool dictionary or None if not found
    """
    tool_dict = tool_data.copy()
    tool_dict["updated_by"] = user_id

    with get_db_session() as session:
        tool = session.query(OuterApiTool).filter(
            OuterApiTool.id == tool_id,
            OuterApiTool.tenant_id == tenant_id,
            OuterApiTool.delete_flag != 'Y'
        ).first()

        if not tool:
            return None

        for key, value in tool_dict.items():
            if hasattr(tool, key):
                setattr(tool, key, value)

        session.flush()
        return as_dict(tool)


def delete_outer_api_tool(tool_id: int, tenant_id: str, user_id: str) -> bool:
    """
    Soft delete an outer API tool record.

    Args:
        tool_id: Tool ID
        tenant_id: Tenant ID
        user_id: User ID for audit

    Returns:
        True if deleted, False if not found
    """
    with get_db_session() as session:
        tool = session.query(OuterApiTool).filter(
            OuterApiTool.id == tool_id,
            OuterApiTool.tenant_id == tenant_id,
            OuterApiTool.delete_flag != 'Y'
        ).first()

        if not tool:
            return False

        tool.delete_flag = 'Y'
        tool.updated_by = user_id
        return True


def delete_all_outer_api_tools(tenant_id: str, user_id: str) -> int:
    """
    Soft delete all outer API tools for a tenant.

    Args:
        tenant_id: Tenant ID
        user_id: User ID for audit

    Returns:
        Number of deleted tools
    """
    with get_db_session() as session:
        count = session.query(OuterApiTool).filter(
            OuterApiTool.tenant_id == tenant_id,
            OuterApiTool.delete_flag != 'Y'
        ).update({
            OuterApiTool.delete_flag: 'Y',
            OuterApiTool.updated_by: user_id
        })
        return count


def sync_outer_api_tools(
    tools_data: List[Dict[str, Any]],
    tenant_id: str,
    user_id: str
) -> Dict[str, Any]:
    """
    Sync outer API tools: delete old ones and create new ones.
    This is used for full replacement of tools from a new OpenAPI JSON upload.

    Args:
        tools_data: List of tool data dictionaries to be synced
        tenant_id: Tenant ID
        user_id: User ID for audit

    Returns:
        Dictionary with counts of created and deleted tools
    """
    with get_db_session() as session:
        existing_tools = session.query(OuterApiTool).filter(
            OuterApiTool.tenant_id == tenant_id,
            OuterApiTool.delete_flag != 'Y'
        ).all()

        existing_tool_dict = {tool.name: tool for tool in existing_tools}
        existing_tool_names = set(existing_tool_dict.keys())
        new_tool_names = set(t.get("name") for t in tools_data if t.get("name"))

        to_delete_names = existing_tool_names - new_tool_names

        for tool in existing_tools:
            if tool.name in to_delete_names:
                tool.delete_flag = 'Y'
                tool.updated_by = user_id

        for tool_data in tools_data:
            tool_name = tool_data.get("name")
            if tool_name in existing_tool_dict:
                tool = existing_tool_dict[tool_name]
                for key, value in tool_data.items():
                    if hasattr(tool, key):
                        setattr(tool, key, value)
                tool.updated_by = user_id
                tool.is_available = True
            else:
                tool_dict = tool_data.copy()
                tool_dict["tenant_id"] = tenant_id
                tool_dict["created_by"] = user_id
                tool_dict["updated_by"] = user_id
                tool_dict.setdefault("is_available", True)
                new_tool = OuterApiTool(**filter_property(tool_dict, OuterApiTool))
                session.add(new_tool)

        session.flush()

        return {
            "created": len(new_tool_names - existing_tool_names),
            "updated": len(existing_tool_names & new_tool_names),
            "deleted": len(to_delete_names)
        }
