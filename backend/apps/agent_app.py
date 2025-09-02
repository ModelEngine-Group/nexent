import logging
from http import HTTPStatus
from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from consts.model import AgentRequest, AgentInfoRequest, AgentIDRequest, ConversationResponse, AgentImportRequest
from services.agent_service import (
    get_agent_info_impl,
    get_creating_sub_agent_info_impl,
    update_agent_info_impl,
    delete_agent_impl,
    export_agent_impl,
    import_agent_impl,
    list_all_agent_info_impl,
    insert_related_agent_impl,
    run_agent_stream,
    stop_agent_tasks,
    get_agent_call_relationship_impl,
    delete_related_agent_impl
)
from utils.auth_utils import get_current_user_info, get_current_user_id

router = APIRouter(prefix="/agent")
logger = logging.getLogger("agent_app")


# Define API route
@router.post("/run")
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


@router.get("/stop/{conversation_id}")
async def agent_stop_api(conversation_id: int):
    """
    stop agent run and preprocess tasks for specified conversation_id
    """
    if stop_agent_tasks(conversation_id).get("status") == "success":
        return {"status": "success", "message": "agent run and preprocess tasks stopped successfully"}
    else:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST,
                            detail=f"no running agent or preprocess tasks found for conversation_id {conversation_id}")


@router.post("/search_info")
async def search_agent_info_api(agent_id: int = Body(...), authorization: Optional[str] = Header(None)):
    """
    Search agent info by agent_id
    """
    try:
        _, tenant_id = get_current_user_id(authorization)
        return await get_agent_info_impl(agent_id, tenant_id)
    except Exception as e:
        logger.error(f"Agent search info error: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Agent search info error.")


@router.get("/get_creating_sub_agent_id")
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


@router.post("/update")
async def update_agent_info_api(request: AgentInfoRequest, authorization: Optional[str] = Header(None)):
    """
    Update an existing agent
    """
    try:
        await update_agent_info_impl(request, authorization)
        return {}
    except Exception as e:
        logger.error(f"Agent update error: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Agent update error.")


@router.delete("")
async def delete_agent_api(request: AgentIDRequest, authorization: Optional[str] = Header(None)):
    """
    Delete an agent
    """
    try:
        await delete_agent_impl(request.agent_id, authorization)
        return {}
    except Exception as e:
        logger.error(f"Agent delete error: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Agent delete error.")


@router.post("/export")
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


@router.post("/import")
async def import_agent_api(request: AgentImportRequest, authorization: Optional[str] = Header(None)):
    """
    import an agent
    """
    try:
        await import_agent_impl(request.agent_info, authorization)
        return {}
    except Exception as e:
        logger.error(f"Agent import error: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Agent import error.")


@router.get("/list")
async def list_all_agent_info_api(authorization: Optional[str] = Header(None), request: Request = None):
    """
    list all agent info
    """
    try:
        _, tenant_id, _ = get_current_user_info(authorization, request)
        return await list_all_agent_info_impl(tenant_id=tenant_id)
    except Exception as e:
        logger.error(f"Agent list error: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Agent list error.")


@router.post("/related_agent")
async def related_agent_api(parent_agent_id: int = Body(...),
                            child_agent_id: int = Body(...),
                            authorization: Optional[str] = Header(None)):
    """
    get related agent info
    """
    try:
        _, tenant_id = get_current_user_id(authorization)
        return insert_related_agent_impl(parent_agent_id=parent_agent_id,
                                         child_agent_id=child_agent_id,
                                         tenant_id=tenant_id)
    except Exception as e:
        logger.error(f"Agent related info error: {str(e)}")
        return JSONResponse(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            content={"message": "Failed to insert relation", "status": "error"}
        )


@router.post("/delete_related_agent")
async def delete_related_agent_api(parent_agent_id: int = Body(...),
                                   child_agent_id: int = Body(...),
                                   authorization: Optional[str] = Header(None)):
    """
    delete related agent info
    """
    try:
        _, tenant_id = get_current_user_id(authorization)
        return delete_related_agent_impl(parent_agent_id, child_agent_id, tenant_id)
    except Exception as e:
        logger.error(f"Agent related info error: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Agent related info error.")


@router.get("/call_relationship/{agent_id}")
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
