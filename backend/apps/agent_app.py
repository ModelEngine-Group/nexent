import logging
from http import HTTPStatus
from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException, Request, Query
from fastapi.encoders import jsonable_encoder
from starlette.responses import JSONResponse

from consts.model import AgentRequest, AgentInfoRequest, AgentIDRequest, ConversationResponse, AgentImportRequest, AgentNameBatchCheckRequest, AgentNameBatchRegenerateRequest, VersionPublishRequest, VersionListResponse, VersionDetailResponse, VersionRollbackRequest, VersionStatusRequest, CurrentVersionResponse, VersionCompareRequest
from services.agent_service import (
    get_agent_info_impl,
    get_creating_sub_agent_info_impl,
    update_agent_info_impl,
    delete_agent_impl,
    export_agent_impl,
    import_agent_impl,
    check_agent_name_conflict_batch_impl,
    regenerate_agent_name_batch_impl,
    list_all_agent_info_impl,
    run_agent_stream,
    stop_agent_tasks,
    get_agent_call_relationship_impl,
    clear_agent_new_mark_impl
)
from services.agent_version_service import (
    publish_version_impl,
    get_version_list_impl,
    get_version_impl,
    get_version_detail_impl,
    rollback_version_impl,
    update_version_status_impl,
    delete_version_impl,
    get_current_version_impl,
    compare_versions_impl,
    list_published_agents_impl,
)
from utils.auth_utils import get_current_user_info, get_current_user_id

# Import monitoring utilities
from utils.monitoring import monitoring_manager

agent_runtime_router = APIRouter(prefix="/agent")
agent_config_router = APIRouter(prefix="/agent")
logger = logging.getLogger("agent_app")


# Define API route
@agent_runtime_router.post("/run")
@monitoring_manager.monitor_endpoint("agent.run", exclude_params=["authorization"])
async def agent_run_api(agent_request: AgentRequest, http_request: Request, authorization: str = Header(None)):
    """
    Agent execution API endpoint
    """
    try:
        return await run_agent_stream(
            agent_request=agent_request,
            http_request=http_request,
            authorization=authorization
        )
    except Exception as e:
        logger.error(f"Agent run error: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Agent run error.")


@agent_runtime_router.get("/stop/{conversation_id}")
async def agent_stop_api(conversation_id: int, authorization: Optional[str] = Header(None)):
    """
    stop agent run and preprocess tasks for specified conversation_id
    """
    user_id, _ = get_current_user_id(authorization)
    if stop_agent_tasks(conversation_id, user_id).get("status") == "success":
        return {"status": "success", "message": "agent run and preprocess tasks stopped successfully"}
    else:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST,
                            detail=f"no running agent or preprocess tasks found for conversation_id {conversation_id}")


@agent_config_router.post("/search_info")
async def search_agent_info_api(
    agent_id: int = Body(...),
    version_no: int = Body(0),
    tenant_id: Optional[str] = Query(
        None, description="Tenant ID for filtering (uses auth if not provided)"),
    authorization: Optional[str] = Header(None)
):
    """
    Search agent info by agent_id and version_no
    version_no defaults to 0 (current/draft version)
    """
    try:
        _, auth_tenant_id = get_current_user_id(authorization)
        # Use explicit tenant_id if provided, otherwise fall back to auth tenant_id
        effective_tenant_id = tenant_id or auth_tenant_id
        return await get_agent_info_impl(agent_id, effective_tenant_id, version_no)
    except Exception as e:
        logger.error(f"Agent search info error: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Agent search info error.")


@agent_config_router.get("/get_creating_sub_agent_id")
async def get_creating_sub_agent_info_api(authorization: Optional[str] = Header(None)):
    """
    Create a new sub agent, return agent_ID
    """
    try:
        return await get_creating_sub_agent_info_impl(authorization)
    except Exception as e:
        logger.error(f"Agent create error: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Agent create error.")


@agent_config_router.post("/update")
async def update_agent_info_api(request: AgentInfoRequest, authorization: Optional[str] = Header(None)):
    """
    Update an existing agent
    """
    try:
        result = await update_agent_info_impl(request, authorization)
        return result or {}
    except Exception as e:
        logger.error(f"Agent update error: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Agent update error.")


@agent_config_router.delete("")
async def delete_agent_api(
    request: AgentIDRequest,
    tenant_id: Optional[str] = Query(
        None, description="Tenant ID for filtering (uses auth if not provided)"),
    authorization: Optional[str] = Header(None),
    http_request: Request = None
):
    """
    Delete an agent
    """
    try:
        user_id, auth_tenant_id, _ = get_current_user_info(authorization, http_request)
        # Use explicit tenant_id if provided, otherwise fall back to auth tenant_id
        effective_tenant_id = tenant_id or auth_tenant_id
        await delete_agent_impl(request.agent_id, effective_tenant_id, user_id)
        return {}
    except Exception as e:
        logger.error(f"Agent delete error: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Agent delete error.")


@agent_config_router.post("/export")
async def export_agent_api(request: AgentIDRequest, authorization: Optional[str] = Header(None)):
    """
    export an agent
    """
    try:
        agent_info_str = await export_agent_impl(request.agent_id, authorization)
        return ConversationResponse(code=0, message="success", data=agent_info_str)
    except Exception as e:
        logger.error(f"Agent export error: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Agent export error.")


@agent_config_router.post("/import")
async def import_agent_api(request: AgentImportRequest, authorization: Optional[str] = Header(None)):
    """
    import an agent
    """
    try:
        await import_agent_impl(
            request.agent_info,
            authorization,
            force_import=request.force_import
        )
        return {}
    except Exception as e:
        logger.error(f"Agent import error: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Agent import error.")


@agent_config_router.put("/clear_new/{agent_id}")
async def clear_agent_new_mark_api(agent_id: int, authorization: Optional[str] = Header(None)):
    """
    Clear the NEW mark for an agent
    """
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization)
        affected_rows = await clear_agent_new_mark_impl(agent_id, tenant_id, user_id)
        return {"message": "Agent NEW mark cleared successfully", "affected_rows": affected_rows}
    except Exception as e:
        logger.error(f"Failed to clear agent NEW mark: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Failed to clear agent NEW mark.")


@agent_config_router.post("/check_name")
async def check_agent_name_batch_api(request: AgentNameBatchCheckRequest, authorization: Optional[str] = Header(None)):
    """
    Batch check whether agent name/display_name conflicts exist in the tenant.
    """
    try:
        return await check_agent_name_conflict_batch_impl(request, authorization)
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Agent name batch check error: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Agent name batch check error.")


@agent_config_router.post("/regenerate_name")
async def regenerate_agent_name_batch_api(request: AgentNameBatchRegenerateRequest, authorization: Optional[str] = Header(None)):
    """
    Batch regenerate agent name/display_name using LLM or suffix fallback.
    """
    try:
        return await regenerate_agent_name_batch_impl(request, authorization)
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Agent name batch regenerate error: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Agent name batch regenerate error.")


@agent_config_router.get("/list")
async def list_all_agent_info_api(
    tenant_id: Optional[str] = Query(
        None, description="Tenant ID for filtering (uses auth if not provided)"),
    authorization: Optional[str] = Header(None),
    request: Request = None
):
    """
    list all agent info
    """
    try:
        user_id, auth_tenant_id, _ = get_current_user_info(authorization, request)
        # Use explicit tenant_id if provided, otherwise fall back to auth tenant_id
        effective_tenant_id = tenant_id or auth_tenant_id
        return await list_all_agent_info_impl(tenant_id=effective_tenant_id, user_id=user_id)
    except Exception as e:
        logger.error(f"Agent list error: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Agent list error.")


@agent_config_router.get("/call_relationship/{agent_id}")
async def get_agent_call_relationship_api(agent_id: int, authorization: Optional[str] = Header(None)):
    """
    Get agent call relationship tree including tools and sub-agents
    """
    try:
        _, tenant_id = get_current_user_id(authorization)
        return get_agent_call_relationship_impl(agent_id, tenant_id)
    except Exception as e:
        logger.error(f"Agent call relationship error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail="Failed to get agent call relationship.")


# Agent Version Management APIs
# ---------------------------------------------------------------------------


@agent_config_router.post("/{agent_id}/publish")
async def publish_version_api(
    agent_id: int,
    request: VersionPublishRequest,
    authorization: str = Header(None),
):
    """
    Publish a new version
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        result = publish_version_impl(
            agent_id=agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
            version_name=request.version_name,
            release_note=request.release_note,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Publish version error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Publish version error.")


@agent_config_router.post("/{agent_id}/versions/compare")
async def compare_versions_api(
    agent_id: int,
    request: VersionCompareRequest,
    authorization: str = Header(None),
):
    """
    Compare two versions and return their differences
    """
    try:
        _, tenant_id = get_current_user_id(authorization)
        result = compare_versions_impl(
            agent_id=agent_id,
            tenant_id=tenant_id,
            version_no_a=request.version_no_a,
            version_no_b=request.version_no_b,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=jsonable_encoder(result))
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Compare versions error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Compare versions error.")


@agent_config_router.get("/{agent_id}/versions", response_model=VersionListResponse)
async def get_version_list_api(
    agent_id: int,
    tenant_id: Optional[str] = Query(
        None, description="Tenant ID for filtering (uses auth if not provided)"),
    authorization: Optional[str] = Header(None),
    request: Request = None
):
    """
    Get version list for an agent
    """
    try:
        user_id, auth_tenant_id, _ = get_current_user_info(authorization, request)
        # Use explicit tenant_id if provided, otherwise fall back to auth tenant_id
        effective_tenant_id = tenant_id or auth_tenant_id
        logger.info(f"Get version list for agent_id: {agent_id}, tenant_id: {effective_tenant_id}")
        result = get_version_list_impl(
            agent_id=agent_id,
            tenant_id=effective_tenant_id,
        )
        logger.info(f"Version list: {result}")
        return JSONResponse(status_code=HTTPStatus.OK, content=jsonable_encoder(result))
    except Exception as e:
        logger.error(f"Get version list error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Get version list error.")


@agent_config_router.get("/{agent_id}/versions/{version_no}", response_model=VersionDetailResponse)
async def get_version_api(
    agent_id: int,
    version_no: int,
    authorization: str = Header(None),
):
    """
    Get version
    """
    try:
        _, tenant_id = get_current_user_id(authorization)
        result = get_version_impl(
            agent_id=agent_id,
            tenant_id=tenant_id,
            version_no=version_no,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=jsonable_encoder(result))
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"Get version detail error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Get version detail error.")

@agent_config_router.get("/{agent_id}/versions/{version_no}/detail", response_model=VersionDetailResponse)
async def get_version_detail_api(
    agent_id: int,
    version_no: int,
    authorization: str = Header(None),
):
    """
    Get version detail including snapshot data
    """
    try:
        _, tenant_id = get_current_user_id(authorization)
        result = get_version_detail_impl(
            agent_id=agent_id,
            tenant_id=tenant_id,
            version_no=version_no,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=jsonable_encoder(result))
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"Get version detail error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Get version detail error.")


@agent_config_router.post("/{agent_id}/versions/{version_no}/rollback")
async def rollback_version_api(
    agent_id: int,
    version_no: int,
    authorization: str = Header(None),
):
    """
    Rollback to a specific version by updating current_version_no only.
    This does NOT create a new version - the draft will point to the target version.
    Use the publish endpoint to create an actual new version after rollback.
    """
    try:
        _, tenant_id = get_current_user_id(authorization)
        result = rollback_version_impl(
            agent_id=agent_id,
            tenant_id=tenant_id,
            target_version_no=version_no,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Rollback version error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Rollback version error.")


@agent_config_router.patch("/{agent_id}/versions/{version_no}/status")
async def update_version_status_api(
    agent_id: int,
    version_no: int,
    request: VersionStatusRequest,
    authorization: str = Header(None),
):
    """
    Update version status (DISABLED / ARCHIVED)
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        result = update_version_status_impl(
            agent_id=agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
            version_no=version_no,
            status=request.status,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Update version status error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Update version status error.")


@agent_config_router.delete("/{agent_id}/versions/{version_no}")
async def delete_version_api(
    agent_id: int,
    version_no: int,
    authorization: str = Header(None),
):
    """
    Delete a version (soft delete by setting delete_flag='Y')
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        result = delete_version_impl(
            agent_id=agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
            version_no=version_no,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Delete version error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Delete version error.")


@agent_config_router.get("/{agent_id}/current_version", response_model=CurrentVersionResponse)
async def get_current_version_api(
    agent_id: int,
    authorization: str = Header(None),
):
    """
    Get current published version
    """
    try:
        _, tenant_id = get_current_user_id(authorization)
        result = get_current_version_impl(
            agent_id=agent_id,
            tenant_id=tenant_id,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=jsonable_encoder(result))
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"Get current version error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Get current version error.")


@agent_config_router.get("/published_list")
async def list_published_agents_api(
    authorization: Optional[str] = Header(None),
    request: Request = None,
):
    """
    List all published agents with their current published version information.
    """
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, request)
        return await list_published_agents_impl(tenant_id=tenant_id, user_id=user_id)
    except Exception as e:
        logger.error(f"Published agents list error: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Published agents list error."
        )

