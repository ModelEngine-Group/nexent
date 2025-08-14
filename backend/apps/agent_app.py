import logging
from typing import Optional

from fastapi import HTTPException, APIRouter, Header, Request, Body
from fastapi.responses import StreamingResponse, JSONResponse
from nexent.core.agents.run_agent import agent_run

from database.agent_db import delete_related_agent
from utils.auth_utils import get_current_user_info, get_current_user_id
from agents.create_agent_info import create_agent_run_info
from consts.model import AgentRequest, AgentInfoRequest, AgentIDRequest, ConversationResponse, AgentImportRequest
from services.agent_service import get_agent_info_impl, \
    get_creating_sub_agent_info_impl, update_agent_info_impl, delete_agent_impl, export_agent_impl, import_agent_impl, \
    list_all_agent_info_impl, insert_related_agent_impl
from services.conversation_management_service import save_conversation_user, save_conversation_assistant
from services.memory_config_service import build_memory_context
from utils.config_utils import config_manager
from utils.thread_utils import submit
from agents.agent_run_manager import agent_run_manager
from agents.preprocess_manager import preprocess_manager


router = APIRouter(prefix="/agent")
# Configure logging
logger = logging.getLogger("agent_app")

# Define API route
@router.post("/run")
async def agent_run_api(agent_request: AgentRequest, http_request: Request, authorization: str = Header(None)):
    """
    Agent execution API endpoint
    """
    user_id, tenant_id, language = get_current_user_info(authorization, http_request)
    memory_context = build_memory_context(user_id, tenant_id, agent_request.agent_id)

    agent_run_info = await create_agent_run_info(agent_id=agent_request.agent_id,
                                                 minio_files=agent_request.minio_files,
                                                 query=agent_request.query,
                                                 history=agent_request.history,
                                                 authorization=authorization,
                                                 language=language)

    agent_run_manager.register_agent_run(agent_request.conversation_id, agent_run_info)
    # Save user message only if not in debug mode
    if not agent_request.is_debug:
        submit(save_conversation_user, agent_request, authorization)

    async def generate():
        messages = []
        try:
            async for chunk in agent_run(agent_run_info, memory_context):
                messages.append(chunk)
                yield f"data: {chunk}\n\n"
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Agent run error: {str(e)}")
        finally:
            # Save assistant message only if not in debug mode
            if not agent_request.is_debug:
                submit(save_conversation_assistant, agent_request, messages, authorization)
            # Unregister agent run instance for both debug and non-debug modes
            agent_run_manager.unregister_agent_run(agent_request.conversation_id)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive"
        }
    )


@router.get("/stop/{conversation_id}")
async def agent_stop_api(conversation_id: int):
    """
    stop agent run and preprocess tasks for specified conversation_id
    """
    # Stop agent run
    agent_stopped = agent_run_manager.stop_agent_run(conversation_id)
    
    # Stop preprocess tasks
    preprocess_stopped = preprocess_manager.stop_preprocess_tasks(conversation_id)
    
    if agent_stopped or preprocess_stopped:
        message_parts = []
        if agent_stopped:
            message_parts.append("agent run")
        if preprocess_stopped:
            message_parts.append("preprocess tasks")
        
        message = f"successfully stopped {' and '.join(message_parts)} for conversation_id {conversation_id}"
        return {"status": "success", "message": message}
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