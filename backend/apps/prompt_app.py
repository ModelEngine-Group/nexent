import logging
from http import HTTPStatus
from typing import Optional
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from consts.model import GeneratePromptRequest
from services.prompt_service import gen_system_prompt_streamable
from utils.auth_utils import get_current_user_info

router = APIRouter(prefix="/prompt")
logger = logging.getLogger("prompt_app")


@router.post("/generate")
async def generate_and_save_system_prompt_api(
        prompt_request: GeneratePromptRequest,
        http_request: Request,
        authorization: Optional[str] = Header(None)
):
    try:
        user_id, tenant_id, language = get_current_user_info(
            authorization, http_request)
        return StreamingResponse(gen_system_prompt_streamable(
            agent_id=prompt_request.agent_id,
            model_id=prompt_request.model_id,
            task_description=prompt_request.task_description,
            user_id=user_id,
            tenant_id=tenant_id,
            language=language
        ), media_type="text/event-stream")
    except Exception as e:
        logger.exception(f"Error occurred while generating system prompt: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Error occurred while generating system prompt.")
