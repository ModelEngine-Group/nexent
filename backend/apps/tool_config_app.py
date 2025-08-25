from fastapi import HTTPException, APIRouter
from fastapi.responses import JSONResponse
import logging
from database.tool_db import query_all_tools
from consts.model import ToolInstanceInfoRequest, ToolInstanceSearchRequest
from services.tool_configuration_service import search_tool_info_impl, update_tool_info_impl, update_tool_list
from fastapi import Header
from typing import Optional
from utils.auth_utils import get_current_user_id

router = APIRouter(prefix="/tool")

# Configure logging
logger = logging.getLogger("tool_config_app")


@router.get("/list")
async def list_tools_api(authorization: Optional[str] = Header(None)):
    """
    List all system tools from PG dataset
    """
    try:
        _, tenant_id = get_current_user_id(authorization)
        # now only admin can modify the tool, user_id is not used
        return query_all_tools(tenant_id=tenant_id)
    except Exception as e:
        logging.error(f"Failed to get tool info, error in: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get tool info, error in: {str(e)}")

@router.post("/search")
async def search_tool_info_api(request: ToolInstanceSearchRequest, authorization: Optional[str] = Header(None)):
    try:
        return search_tool_info_impl(request.agent_id, request.tool_id, authorization)
    except Exception as e: 
        logging.error(f"Failed to update tool, error in: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update tool, error in: {str(e)}")


@router.post("/update")
async def update_tool_info_api(request: ToolInstanceInfoRequest, authorization: Optional[str] = Header(None)):
    """
    Update an existing tool, create or update tool instance
    """
    try:
        return update_tool_info_impl(request, authorization)
    except Exception as e:
        logging.error(f"Failed to update tool, error in: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update tool, error in: {str(e)}")

@router.get("/scan_tool")
async def scan_and_update_tool(
    authorization: Optional[str] = Header(None)
):
    """ Used to update the tool list and status """
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