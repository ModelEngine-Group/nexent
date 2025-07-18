import logging
from typing import Optional

from fastapi.responses import JSONResponse
from fastapi import APIRouter, Header

from services.remote_mcp_service import add_remote_mcp_server_list, delete_remote_mcp_server_list, \
    get_remote_mcp_server_list, mcp_server_health
from services.tool_configuration_service import get_tool_from_remote_mcp_server
from utils.auth_utils import get_current_user_id
from database.remote_mcp_db import update_mcp_status_by_name_and_url

router = APIRouter(prefix="/mcp")

# Configure logging
logger = logging.getLogger("remote_mcp_app")


@router.post("/tools")
async def get_tools_from_remote_mcp(
    service_name: str,
    mcp_url: str,
    authorization: Optional[str] = Header(None)
):
    """ Used to list tool information from the remote MCP server """
    try:
        tools_info = await get_tool_from_remote_mcp_server(mcp_server_name=service_name, remote_mcp_server=mcp_url)
        return JSONResponse(
            status_code=200,
            content={"tools": [tool.__dict__ for tool in tools_info], "status": "success"}
        )
    except Exception as e:
        logger.error(f"get tools from remote MCP server failed, error: {e}")
        return JSONResponse(
            status_code=400,
            content={"message": "Failed to get tools from remote MCP server", "status": "error"}
        )

@router.post("/add")
async def add_remote_proxies(
    mcp_url: str,
    service_name: str,
    authorization: Optional[str] = Header(None)
):
    """ Used to add a remote MCP server """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        result = await add_remote_mcp_server_list(tenant_id=tenant_id,
                                                  user_id=user_id,
                                                  remote_mcp_server=mcp_url,
                                                  remote_mcp_server_name=service_name)
        # If result is already a JSONResponse, return it directly
        if isinstance(result, JSONResponse):
            return result
        
        # Otherwise, return a success result
        return JSONResponse(
            status_code=200,
            content={"message": "Successfully added remote MCP proxy", "status": "success"}
        )
    except Exception as e:
        logger.error(f"Failed to add remote MCP proxy: {e}")
        return JSONResponse(
            status_code=400,
            content={"message": "Failed to add remote MCP proxy", "status": "error"}
        )

@router.delete("/")
async def delete_remote_proxies(
    service_name: str,
    mcp_url: str,
    authorization: Optional[str] = Header(None)
):
    """ Used to delete a remote MCP server """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        result = await delete_remote_mcp_server_list(tenant_id=tenant_id,
                                                     user_id=user_id,
                                                     remote_mcp_server=mcp_url,
                                                     remote_mcp_server_name=service_name)
        # If result is already a JSONResponse, return it directly
        if isinstance(result, JSONResponse):
            return result
        
        # Otherwise, return a success result
        return JSONResponse(
            status_code=200,
            content={"message": "Successfully deleted remote MCP proxy", "status": "success"}
        )
    except Exception as e:
        logger.error(f"Failed to delete remote MCP proxy: {e}")
        return JSONResponse(
            status_code=400,
            content={"message": "Failed to delete remote MCP proxy", "status": "error"}
        )

@router.get("/list")
async def get_remote_proxies(
    authorization: Optional[str] = Header(None)
):
    """ Used to get the list of remote MCP servers """
    try:
        _, tenant_id = get_current_user_id(authorization)
        remote_mcp_server_list = await get_remote_mcp_server_list(tenant_id=tenant_id)
        return JSONResponse(
            status_code=200,
            content={"remote_mcp_server_list": remote_mcp_server_list, "status": "success"}
        )
    except Exception as e:
        logger.error(f"Failed to get remote MCP proxy: {e}")
        return JSONResponse(
            status_code=400,
            content={"message": "Failed to get remote MCP proxy", "status": "error"}
        )

@router.get("/healthcheck")
async def check_mcp_health(mcp_url: str, service_name: str, authorization: Optional[str] = Header(None)):
    """ Used to check the health of the MCP server, the front end can call it, and automatically update the database status """
    user_id, tenant_id = get_current_user_id(authorization)

    # check the health of the MCP server
    response = await mcp_server_health(remote_mcp_server=mcp_url)
    # update the status of the MCP server in the database

    status = response.status_code == 200
    update_mcp_status_by_name_and_url(mcp_name=service_name,
                                        mcp_server=mcp_url,
                                        tenant_id=tenant_id,
                                        user_id=user_id,
                                        status=status)
    return response
