import logging
from typing import Optional

from fastapi import HTTPException, APIRouter, Header, Request, Body
from fastapi.responses import JSONResponse
from consts.model import AgentRequest, AgentInfoRequest, AgentIDRequest, ConversationResponse, AgentImportRequest
from services.agent_service import get_agent_info_impl, \
    get_creating_sub_agent_info_impl, update_agent_info_impl, delete_agent_impl, export_agent_impl, import_agent_impl, \
    list_all_agent_info_impl, insert_related_agent_impl, run_agent_stream, stop_agent_tasks
from database.agent_db import delete_related_agent
from utils.auth_utils import get_current_user_info, get_current_user_id


router = APIRouter(prefix="/agent")
# Configure logging
logger = logging.getLogger("agent_app")

# Define API route
@router.post("/run")
async def agent_run_api(agent_request: AgentRequest, http_request: Request, authorization: str = Header(None)):
    """
    Agent execution API endpoint
    """
    return await run_agent_stream(
        agent_request=agent_request,
        http_request=http_request,
        authorization=authorization
    )


@router.get("/stop/{conversation_id}")
async def agent_stop_api(conversation_id: int):
    """
    stop agent run and preprocess tasks for specified conversation_id
    """
    if stop_agent_tasks(conversation_id).get("status") == "success":
        return {"status": "success", "message": "agent run and preprocess tasks stopped successfully"}
    else:
        raise HTTPException(status_code=404, detail=f"no running agent or preprocess tasks found for conversation_id {conversation_id}")


@router.post("/search_info")
async def search_agent_info_api(agent_id: int = Body(...), authorization: Optional[str] = Header(None)):
    """
    Search agent info by agent_id
    """
    try:
        _, tenant_id = get_current_user_id(authorization)
        return get_agent_info_impl(agent_id, tenant_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent search info error: {str(e)}")


@router.get("/get_creating_sub_agent_id")
async def get_creating_sub_agent_info_api(authorization: Optional[str] = Header(None)):
    """
    Create a new sub agent, return agent_ID
    """
    try:
        return get_creating_sub_agent_info_impl(authorization)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent create error: {str(e)}")


@router.post("/update")
async def update_agent_info_api(request: AgentInfoRequest, authorization: Optional[str] = Header(None)):
    """
    Update an existing agent
    """
    try:
        update_agent_info_impl(request, authorization)
        return {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent update error: {str(e)}")


@router.delete("")
async def delete_agent_api(request: AgentIDRequest, authorization: Optional[str] = Header(None)):
    """
    Delete an agent
    """
    try:
        await delete_agent_impl(request.agent_id, authorization)
        return {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent delete error: {str(e)}")


@router.post("/export")
async def export_agent_api(request: AgentIDRequest, authorization: Optional[str] = Header(None)):
    """
    export an agent
    """
    try:
        agent_info_str = await export_agent_impl(request.agent_id, authorization)
        return ConversationResponse(code=0, message="success", data=agent_info_str)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent export error: {str(e)}")


@router.post("/import")
async def import_agent_api(request: AgentImportRequest, authorization: Optional[str] = Header(None)):
    """
    import an agent
    """
    try:
        await import_agent_impl(request.agent_info, authorization)
        return {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent import error: {str(e)}")

@router.get("/list")
async def list_all_agent_info_api(authorization: Optional[str] = Header(None), request: Request = None):
    """
    list all agent info
    """
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization, request)
        return list_all_agent_info_impl(tenant_id=tenant_id, user_id=user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent list error: {str(e)}")


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
            status_code=400,
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
        return delete_related_agent(parent_agent_id, child_agent_id, tenant_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent related info error: {str(e)}")


@router.get("/call_relationship/{agent_id}")
async def get_agent_call_relationship_api(agent_id: int, authorization: Optional[str] = Header(None)):
    """
    Get agent call relationship tree including tools and sub-agents
    """
    try:
        _, tenant_id = get_current_user_id(authorization)
        from services.agent_service import get_agent_call_relationship_impl
        return get_agent_call_relationship_impl(agent_id, tenant_id)
    except Exception as e:
        logger.error(f"Agent call relationship error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get agent call relationship: {str(e)}")