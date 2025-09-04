import logging

from fastmcp import Client

from consts.exceptions import MCPConnectionError, MCPNameIllegal
from database.remote_mcp_db import (
    create_mcp_record,
    delete_mcp_record_by_name_and_url,
    get_mcp_records_by_tenant,
    check_mcp_name_exists,
    update_mcp_status_by_name_and_url
)

logger = logging.getLogger("remote_mcp_service")


async def mcp_server_health(remote_mcp_server: str) -> bool:
    try:
        client = Client(remote_mcp_server)
        async with client:
            connected = client.is_connected()
            return connected
    except Exception as e:
        logger.error(f"Remote MCP server health check failed: {e}")
        raise MCPConnectionError("MCP connection failed")


async def add_remote_mcp_server_list(tenant_id: str,
                                     user_id: str,
                                     remote_mcp_server: str,
                                     remote_mcp_server_name: str):

    # check if MCP name already exists
    if check_mcp_name_exists(mcp_name=remote_mcp_server_name, tenant_id=tenant_id):
        logger.error(
            f"MCP name already exists, tenant_id: {tenant_id}, remote_mcp_server_name: {remote_mcp_server_name}")
        raise MCPNameIllegal("MCP name already exists")

    # check if the address is available
    if not await mcp_server_health(remote_mcp_server=remote_mcp_server):
        raise MCPConnectionError("MCP connection failed")

    # update the PG database record
    insert_mcp_data = {"mcp_name": remote_mcp_server_name,
                       "mcp_server": remote_mcp_server,
                       "status": True}
    create_mcp_record(
        mcp_data=insert_mcp_data, tenant_id=tenant_id, user_id=user_id)


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
    except Exception:
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
