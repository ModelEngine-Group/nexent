import logging
from typing import Optional

from fastapi.responses import JSONResponse
from fastapi import APIRouter, Header

from services.tenant_config_service import add_remote_mcp_server_list, delete_remote_mcp_server_list, get_remote_mcp_server_list, recover_remote_mcp_server
from services.tool_configuration_service import get_tool_from_remote_mcp_server, update_tool_list
from utils.auth_utils import get_current_user_id

router = APIRouter(prefix="/mcp")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp app")


@router.get("/tools/")
async def get_tools_from_remote_mcp(
    service_name: str,
    mcp_url: str,
    authorization: Optional[str] = Header(None)
):
    """ 用于列出远程MCP服务器的工具信息 """
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
    """ 用于添加远程MCP服务器 """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        result = await add_remote_mcp_server_list(tenant_id=tenant_id,
                                                  user_id=user_id,
                                                  remote_mcp_server=mcp_url,
                                                  remote_mcp_server_name=service_name)
        # 如果result已经是JSONResponse，直接返回
        if isinstance(result, JSONResponse):
            return result
        
        # 否则返回成功结果
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
    """ 用于删除远程MCP服务器 """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        result = await delete_remote_mcp_server_list(tenant_id=tenant_id,
                                                     user_id=user_id,
                                                     remote_mcp_server=mcp_url,
                                                     remote_mcp_server_name=service_name)
        # 如果result已经是JSONResponse，直接返回
        if isinstance(result, JSONResponse):
            return result
        
        # 否则返回成功结果
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
    """ 用于获取远程MCP服务器列表 """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        remote_mcp_server_list = await get_remote_mcp_server_list(tenant_id=tenant_id,
                                                                  user_id=user_id)
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

@router.get("/recover")
async def recover_remote_proxies(
    authorization: Optional[str] = Header(None)
):
    """ 用于恢复远程MCP服务器 """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        result = await recover_remote_mcp_server(tenant_id=tenant_id, user_id=user_id)
        # 如果result已经是JSONResponse，直接返回
        if isinstance(result, JSONResponse):
            return result
        
        # 否则返回成功结果
        return JSONResponse(
            status_code=200,
            content={"message": "Successfully recovered remote MCP proxy", "status": "success"}
        )
    except Exception as e:
        logger.error(f"Failed to recover remote MCP proxy: {e}")
        return JSONResponse(
            status_code=400,
            content={"message": "Failed to recover remote MCP proxy", "status": "error"}
        )

@router.get("/update_tool")
async def scan_and_update_tool(
    authorization: Optional[str] = Header(None)
):
    """ 用于更新工具列表及状态 """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        await update_tool_list(tenant_id=tenant_id,
                         user_id=user_id)
        return JSONResponse(
            status_code=200,
            content={"message": "Successfully update tool", "status": "success"}
        )
    except Exception as e:
        logger.error(f"Failed to update tool: {e}")
        return JSONResponse(
            status_code=400,
            content={"message": "Failed to update tool", "status": "error"}
        )