import logging
from fastapi.responses import JSONResponse

from database.remote_mcp_db import create_mcp_record, delete_mcp_record_by_name_and_url, get_mcp_records_by_tenant
from fastmcp import Client
logger = logging.getLogger("remote_mcp_service")


async def mcp_server_health(remote_mcp_server: str) -> JSONResponse:
    try:
        client = Client(remote_mcp_server)
        async with client:
            connected = client.is_connected()
            if connected:
                return JSONResponse(
                    status_code=200,
                    content={"message": "Successfully connected to remote MCP server", "status": "success"}
                )
            else:
                logger.error(f"Remote MCP server health check failed: not connected to {remote_mcp_server}")
                return JSONResponse(
                    status_code=503,
                    content={"message": "Cannot connect to remote MCP server", "status": "error"}
                )
    except Exception as e:
        logger.error(f"Remote MCP server health check failed: {e}")
        return JSONResponse(
            status_code=400,
            content={"message": "Failed to add remote MCP proxy", "status": "error"}
        )

async def add_remote_mcp_server_list(tenant_id: str,
                                     user_id: str,
                                     remote_mcp_server: str,
                                     remote_mcp_server_name: str):

    # check if the address is available
    response = await mcp_server_health(remote_mcp_server=remote_mcp_server)
    if response.status_code != 200:
        return response

    # update the PG database record
    insert_mcp_data = {"mcp_name": remote_mcp_server_name,
                       "mcp_server": remote_mcp_server,
                       "status": True}
    result = create_mcp_record(mcp_data=insert_mcp_data, tenant_id=tenant_id, user_id=user_id)
    if not result:
        logger.error(
            f"add_remote_mcp_server_list failed, tenant_id: {tenant_id}, user_id: {user_id}, remote_mcp_server: {remote_mcp_server}, remote_mcp_server_name: {remote_mcp_server_name}")
        return JSONResponse(
            status_code=400,
            content={"message": "Failed to add remote MCP proxy, database error", "status": "error"}
        )

    return JSONResponse(
        status_code=200,
        content={"message": "Successfully added remote MCP proxy", "status": "success"}
    )

async def delete_remote_mcp_server_list(tenant_id: str,
                                        user_id: str,
                                        remote_mcp_server: str,
                                        remote_mcp_server_name: str):
    # delete the record in the PG database
    result = delete_mcp_record_by_name_and_url(mcp_name=remote_mcp_server_name,
                                               mcp_server=remote_mcp_server,
                                               tenant_id=tenant_id,
                                               user_id=user_id)
    if not result:
        logger.error(
            f"delete_remote_mcp_server_list failed, tenant_id: {tenant_id}, user_id: {user_id}, remote_mcp_server: {remote_mcp_server}, remote_mcp_server_name: {remote_mcp_server_name}")
        return JSONResponse(
            status_code=400,
            content={"message": "Failed to delete remote MCP server, server not record", "status": "error"}
        )

    return JSONResponse(
        status_code=200,
        content={"message": "Successfully added remote MCP proxy", "status": "success"}
    )

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