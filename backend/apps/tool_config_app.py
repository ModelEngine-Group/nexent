import logging
from http import HTTPStatus
from typing import Optional, Dict, Any

from fastapi import APIRouter, Header, HTTPException, Body
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
    import_openapi_service,
    list_openapi_services,
    delete_openapi_service,
    _refresh_openapi_services_in_mcp,
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


# --------------------------------------------------
# OpenAPI Service Management (using from_openapi)
# --------------------------------------------------

@router.post("/openapi_service")
async def import_openapi_service_api(
    openapi_service_request: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None)
):
    """
    Import OpenAPI JSON as an MCP service using FastMCP.from_openapi().

    All tools from the same OpenAPI spec will be grouped under the same
    mcp_service_name. When refreshing, all tools are registered together.

    Request Body:
        service_name: MCP service name for grouping tools
        server_url: Base URL of the REST API server
        openapi_json: Complete OpenAPI JSON specification
        service_description: Optional service description
        force_update: If True, replace all existing tools for this service
    """
    service_name = openapi_service_request.get("service_name")
    server_url = openapi_service_request.get("server_url")
    openapi_json = openapi_service_request.get("openapi_json")
    service_description = openapi_service_request.get("service_description")
    force_update = openapi_service_request.get("force_update", False)

    if not service_name:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="service_name is required"
        )
    if not server_url:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="server_url is required"
        )
    if not openapi_json:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="openapi_json is required"
        )
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        result = import_openapi_service(
            service_name=service_name,
            openapi_json=openapi_json,
            server_url=server_url,
            tenant_id=tenant_id,
            user_id=user_id,
            service_description=service_description,
            force_update=force_update
        )

        mcp_result = _refresh_openapi_services_in_mcp(tenant_id)
        result["mcp_refresh"] = mcp_result

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "OpenAPI service import successful",
                "status": "success",
                "data": result
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to import OpenAPI service: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to import OpenAPI service: {str(e)}"
        )


@router.get("/openapi_services")
async def list_openapi_services_api(
    authorization: Optional[str] = Header(None)
):
    """
    List all OpenAPI services for the current tenant.
    """
    try:
        _, tenant_id = get_current_user_id(authorization)
        services = list_openapi_services(tenant_id)
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "success",
                "data": services
            }
        )
    except Exception as e:
        logger.error(f"Failed to list OpenAPI services: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to list OpenAPI services: {str(e)}"
        )


@router.delete("/openapi_service/{service_name}")
async def delete_openapi_service_api(
    service_name: str,
    authorization: Optional[str] = Header(None)
):
    """
    Delete an OpenAPI service (all tools belonging to it).
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        deleted = delete_openapi_service(service_name, tenant_id, user_id)
        if not deleted:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail="Service not found"
            )
        # Refresh MCP service to reflect the deletion
        mcp_result = _refresh_openapi_services_in_mcp(tenant_id)
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "Service deleted successfully",
                "status": "success",
                "mcp_refresh": mcp_result
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete OpenAPI service: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete OpenAPI service: {str(e)}"
        )
