import logging
from typing import Any, Dict, List

from database.client import as_dict, filter_property, get_db_session
from database.db_models import McpRecord

logger = logging.getLogger("remote_mcp_db")


def create_mcp_record(mcp_data: Dict[str, Any], tenant_id: str, user_id: str):
    """
    Create new MCP record

    :param mcp_data: Dictionary containing MCP information
    :param tenant_id: Tenant ID
    :param user_id: User ID
    :return: Created MCP record
    """
    with get_db_session() as session:
        mcp_data.update({
            "tenant_id": tenant_id,
            "user_id": user_id,
            "created_by": user_id,
            "updated_by": user_id,
            "delete_flag": "N"
        })
        new_mcp = McpRecord(**filter_property(mcp_data, McpRecord))
        session.add(new_mcp)


def delete_mcp_record_by_name_and_url(mcp_name: str, mcp_server: str, tenant_id: str, user_id: str):
    """
    Delete MCP record by name and URL

    :param mcp_name: MCP name
    :param mcp_server: MCP server URL
    :param tenant_id: Tenant ID
    :param user_id: User ID
    """
    with get_db_session() as session:
        session.query(McpRecord).filter(
            McpRecord.mcp_name == mcp_name,
            McpRecord.mcp_server == mcp_server,
            McpRecord.tenant_id == tenant_id,
            McpRecord.delete_flag != 'Y'
        ).update({"delete_flag": "Y", "updated_by": user_id})


def delete_mcp_record_by_container_id(container_id: str, tenant_id: str, user_id: str):
    """
    Soft delete MCP record by container ID

    :param container_id: Docker container ID
    :param tenant_id: Tenant ID
    :param user_id: User ID
    """
    with get_db_session() as session:
        session.query(McpRecord).filter(
            McpRecord.container_id == container_id,
            McpRecord.tenant_id == tenant_id,
            McpRecord.delete_flag != 'Y'
        ).update({"delete_flag": "Y", "updated_by": user_id})


def update_mcp_status_by_name_and_url(mcp_name: str, mcp_server: str, tenant_id: str, user_id: str, status: bool):
    """
    Update the status of MCP record by name and URL
    :param mcp_name: MCP name
    :param mcp_server: MCP server URL
    :param tenant_id: Tenant ID
    :param status: New status (True/False)
    :param user_id: User ID
    """
    with get_db_session() as session:
        session.query(McpRecord).filter(
            McpRecord.mcp_name == mcp_name,
            McpRecord.mcp_server == mcp_server,
            McpRecord.tenant_id == tenant_id,
            McpRecord.delete_flag != 'Y'
        ).update({"status": status, "updated_by": user_id})


def get_mcp_records_by_tenant(tenant_id: str) -> List[Dict[str, Any]]:
    """
    Get all MCP records for a tenant

    :param tenant_id: Tenant ID
    :return: List of MCP records
    """
    with get_db_session() as session:
        mcp_records = session.query(McpRecord).filter(
            McpRecord.tenant_id == tenant_id,
            McpRecord.delete_flag != 'Y'
        ).order_by(McpRecord.create_time.desc()).all()

        return [as_dict(record) for record in mcp_records]


def get_mcp_server_by_name_and_tenant(mcp_name: str, tenant_id: str) -> str:
    """
    Get MCP server address by name and tenant ID

    :param mcp_name: MCP name
    :param tenant_id: Tenant ID
    :return: MCP server address, empty string if not found
    """
    with get_db_session() as session:
        mcp_record = session.query(McpRecord).filter(
            McpRecord.mcp_name == mcp_name,
            McpRecord.tenant_id == tenant_id,
            McpRecord.delete_flag != 'Y'
        ).first()

        return mcp_record.mcp_server if mcp_record else ""


def update_mcp_record_by_name_and_url(
    update_data,
    tenant_id: str,
    user_id: str,
    status: bool = None
):
    """
    Update MCP record by current name and URL

    :param update_data: MCPUpdateRequest containing current and new values
    :param tenant_id: Tenant ID
    :param user_id: User ID
    :param status: Optional status to update
    """
    update_fields = {
        "mcp_name": update_data.new_service_name,
        "mcp_server": update_data.new_mcp_url,
        "updated_by": user_id
    }

    if status is not None:
        update_fields["status"] = status

    with get_db_session() as session:
        session.query(McpRecord).filter(
            McpRecord.mcp_name == update_data.current_service_name,
            McpRecord.mcp_server == update_data.current_mcp_url,
            McpRecord.tenant_id == tenant_id,
            McpRecord.delete_flag != 'Y'
        ).update(update_fields)


def check_mcp_name_exists(mcp_name: str, tenant_id: str) -> bool:
    """
    Check if MCP name already exists for a tenant

    :param mcp_name: MCP name
    :param tenant_id: Tenant ID
    :return: True if name exists, False otherwise
    """
    with get_db_session() as session:
        mcp_record = session.query(McpRecord).filter(
            McpRecord.mcp_name == mcp_name,
            McpRecord.tenant_id == tenant_id,
            McpRecord.delete_flag != 'Y'
        ).first()
        return mcp_record is not None
