import logging
from http import HTTPStatus
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse

from consts.exceptions import MCPConnectionError, NotFoundException
from consts.model import ToolInstanceInfoRequest, ToolInstanceSearchRequest, ToolValidateRequest
from services.tool_configuration_service import (
    search_tool_info_impl,
    update_tool_info_impl,
    update_tool_list,
    list_all_tools,
    load_last_tool_config_impl,
    validate_tool_impl,
)
from utils.auth_utils import get_current_user_id

router = APIRouter(prefix="/tool")
logger = logging.getLogger("tool_config_app")


@router.get("/list")
async def list_tools_api(authorization: Optional[str] = Header(None)):
    """
    List all system tools from PG dataset
    """
    try:
        _, tenant_id = get_current_user_id(authorization)
        # now only admin can modify the tool, user_id is not used
        return await list_all_tools(tenant_id=tenant_id)
    except Exception as e:
        logging.error(f"Failed to get tool info, error in: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Failed to get tool info, error in: {str(e)}")


@router.post("/search")
async def search_tool_info_api(request: ToolInstanceSearchRequest, authorization: Optional[str] = Header(None)):
    try:
        _, tenant_id = get_current_user_id(authorization)
        return search_tool_info_impl(request.agent_id, request.tool_id, tenant_id)
    except Exception as e:
        logging.error(f"Failed to search tool, error in: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Failed to search tool info")


@router.post("/update")
async def update_tool_info_api(request: ToolInstanceInfoRequest, authorization: Optional[str] = Header(None)):
    """
    Update an existing tool, create or update tool instance
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        return update_tool_info_impl(request, tenant_id, user_id)
    except Exception as e:
        logging.error(f"Failed to update tool, error in: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Failed to update tool, error in: {str(e)}")


@router.get("/scan_tool")
async def scan_and_update_tool(
    authorization: Optional[str] = Header(None)
):
    """ Used to update the tool list and status """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        await update_tool_list(tenant_id=tenant_id, user_id=user_id)
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"message": "Successfully update tool", "status": "success"}
        )
    except MCPConnectionError as e:
        logger.error(f"MCP connection failed: {e}")
        raise HTTPException(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE, detail="MCP connection failed")
    except Exception as e:
        logger.error(f"Failed to update tool: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Failed to update tool")


@router.get("/load_config/{tool_id}")
async def load_last_tool_config(tool_id: int, authorization: Optional[str] = Header(None)):
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        tool_params = load_last_tool_config_impl(tool_id, tenant_id, user_id)
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"message": tool_params, "status": "success"}
        )
    except ValueError:
        logger.error(f"Tool configuration not found for tool ID: {tool_id}")
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Tool configuration not found")
    except Exception as e:
        logger.error(f"Failed to load tool config: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Failed to load tool config")


@router.post("/validate")
async def validate_tool(
    request: ToolValidateRequest,
    authorization: Optional[str] = Header(None)
):
    """Validate specific tool based on source type"""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        result = await validate_tool_impl(request, tenant_id, user_id)

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content=result
        )
    except MCPConnectionError as e:
        logger.error(f"MCP connection failed: {e}")
        raise HTTPException(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            detail=str(e)
        )
    except NotFoundException as e:
        logger.error(f"Tool not found: {e}")
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to validate tool: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
