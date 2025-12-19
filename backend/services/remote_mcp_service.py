import logging

from fastmcp import Client

from consts.exceptions import MCPConnectionError, MCPNameIllegal
from database.remote_mcp_db import (
    create_mcp_record,
    delete_mcp_record_by_name_and_url,
    delete_mcp_record_by_container_id,
    get_mcp_records_by_tenant,
    check_mcp_name_exists,
    update_mcp_status_by_name_and_url,
)

logger = logging.getLogger("remote_mcp_service")


async def mcp_server_health(remote_mcp_server: str) -> bool:
    try:
        client = Client(remote_mcp_server)
        async with client:
            connected = client.is_connected()
            return connected
    except BaseException as e:
        logger.error(f"Remote MCP server health check failed: {e}", exc_info=True)
        # Prevent library-level exits (e.g., SystemExit) from crashing the service
        raise MCPConnectionError("MCP connection failed")


async def add_remote_mcp_server_list(
    tenant_id: str,
    user_id: str,
    remote_mcp_server: str,
    remote_mcp_server_name: str,
    container_id: str | None = None,
):

    # check if MCP name already exists
    if check_mcp_name_exists(mcp_name=remote_mcp_server_name, tenant_id=tenant_id):
        logger.error(
            f"MCP name already exists, tenant_id: {tenant_id}, remote_mcp_server_name: {remote_mcp_server_name}")
        raise MCPNameIllegal("MCP name already exists")

    # check if the address is available
    if not await mcp_server_health(remote_mcp_server=remote_mcp_server):
        raise MCPConnectionError("MCP connection failed")

    # update the PG database record
    insert_mcp_data = {
        "mcp_name": remote_mcp_server_name,
        "mcp_server": remote_mcp_server,
        "status": True,
        "container_id": container_id,
    }
    create_mcp_record(mcp_data=insert_mcp_data, tenant_id=tenant_id, user_id=user_id)


async def delete_remote_mcp_server_list(tenant_id: str,
                                        user_id: str,
                                        remote_mcp_server: str,
                                        remote_mcp_server_name: str):
    # delete the record in the PG database
    delete_mcp_record_by_name_and_url(mcp_name=remote_mcp_server_name,
                                      mcp_server=remote_mcp_server,
                                      tenant_id=tenant_id,
                                      user_id=user_id)


async def get_remote_mcp_server_list(tenant_id: str):
    mcp_records = get_mcp_records_by_tenant(tenant_id=tenant_id)
    mcp_records_list = []

    for record in mcp_records:
        mcp_records_list.append({
            "remote_mcp_server_name": record["mcp_name"],
            "remote_mcp_server": record["mcp_server"],
            "status": record["status"]
        })
    return mcp_records_list


async def check_mcp_health_and_update_db(mcp_url, service_name, tenant_id, user_id):
    # check the health of the MCP server
    try:
        status = await mcp_server_health(remote_mcp_server=mcp_url)
    except BaseException:
        status = False
    # update the status of the MCP server in the database
    update_mcp_status_by_name_and_url(
        mcp_name=service_name,
        mcp_server=mcp_url,
        tenant_id=tenant_id,
        user_id=user_id,
        status=status)
    if not status:
        raise MCPConnectionError("MCP connection failed")


async def delete_mcp_by_container_id(tenant_id: str, user_id: str, container_id: str):
    """
    Soft delete MCP record associated with a specific container ID.

    This is used when stopping a containerized MCP so that the MCP record and
    its container are removed together.
    """
    delete_mcp_record_by_container_id(
        container_id=container_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )
