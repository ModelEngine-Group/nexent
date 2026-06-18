import logging
from http import HTTPStatus
from typing import Optional
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse

from consts.model import GeneratePromptRequest, OptimizePromptSectionRequest
from services.prompt_service import (
    gen_system_prompt_streamable,
    optimize_prompt_section_impl,
)
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
            prompt_template_id=prompt_request.prompt_template_id,
            user_id=user_id,
            tenant_id=tenant_id,
            language=language,
            tool_ids=prompt_request.tool_ids,
            sub_agent_ids=prompt_request.sub_agent_ids,
            knowledge_base_display_names=prompt_request.knowledge_base_display_names,
            has_selected_resources=prompt_request.has_selected_resources,
        ), media_type="text/event-stream")
    except Exception as e:
        logger.exception(f"Error occurred while generating system prompt: {e}")
        raise


@router.post("/optimize")
async def optimize_prompt_section_api(
        optimize_request: OptimizePromptSectionRequest,
        http_request: Request,
        authorization: Optional[str] = Header(None)
):
    try:
        _, tenant_id, language = get_current_user_info(
            authorization, http_request)
        optimized_section = optimize_prompt_section_impl(
            agent_id=optimize_request.agent_id,
            model_id=optimize_request.model_id,
            task_description=optimize_request.task_description,
            tenant_id=tenant_id,
            language=language,
            section_type=optimize_request.section_type,
            section_title=optimize_request.section_title,
            current_content=optimize_request.current_content,
            feedback=optimize_request.feedback,
            tool_ids=optimize_request.tool_ids,
            sub_agent_ids=optimize_request.sub_agent_ids,
            knowledge_base_display_names=optimize_request.knowledge_base_display_names,
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "Prompt section optimized successfully",
                "data": optimized_section,
            }
        )
    except Exception as exc:
        logger.exception(f"Error occurred while optimizing prompt section: {exc}")
        raise
