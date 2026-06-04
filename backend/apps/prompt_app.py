import logging
from http import HTTPStatus
from typing import Optional
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse

from consts.model import (
    GeneratePromptRequest,
    OptimizePromptSectionRequest,
    OptimizePromptBadCaseRequest,
    OptimizePromptFromDebugRequest,
)
from services.prompt_service import (
    gen_system_prompt_streamable,
    OptimizeRequest,
    OptimizeResult,
    PromptOptimizationService,
)
from backend.adapters.exception import NexentCapabilityError
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
    _, tenant_id, language = get_current_user_info(
        authorization, http_request)

    service = PromptOptimizationService(
        model_id=optimize_request.model_id,
        tenant_id=tenant_id,
        language=language,
    )

    try:
        result = service.optimize(
            OptimizeRequest(
                agent_id=optimize_request.agent_id,
                model_id=optimize_request.model_id,
                task_description=optimize_request.task_description,
                section_type=optimize_request.section_type,
                section_title=optimize_request.section_title,
                current_content=optimize_request.current_content,
                feedback=optimize_request.feedback,
                mode=optimize_request.mode,
                start_pos=optimize_request.start_pos,
                end_pos=optimize_request.end_pos,
                tool_ids=optimize_request.tool_ids,
                sub_agent_ids=optimize_request.sub_agent_ids,
                knowledge_base_display_names=optimize_request.knowledge_base_display_names,
            )
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "Success",
                "data": {
                    "optimized_content": result.optimized_content,
                    "section_type": result.section_type,
                    "section_title": result.section_title,
                    "original_content": result.original_content,
                }
            },
            headers={"X-Prompt-Source": result.source},
        )
    except NexentCapabilityError as e:
        return JSONResponse(
            status_code=HTTPStatus.BAD_REQUEST,
            content={"message": str(e)},
        )
    except Exception as exc:
        logger.exception(f"Error occurred while optimizing prompt section: {exc}")
        raise


@router.post("/optimize/badcase")
async def optimize_prompt_badcase_api(
        badcase_request: OptimizePromptBadCaseRequest,
        http_request: Request,
        authorization: Optional[str] = Header(None)
):
    _, tenant_id, language = get_current_user_info(
        authorization, http_request)

    service = PromptOptimizationService(
        model_id=badcase_request.model_id,
        tenant_id=tenant_id,
        language=language,
    )

    try:
        result = service.optimize_badcase(
            current_content=badcase_request.current_content,
            bad_cases=badcase_request.bad_cases,
            agent_id=badcase_request.agent_id,
            section_type=badcase_request.section_type,
            section_title=badcase_request.section_title,
            tool_ids=badcase_request.tool_ids,
            sub_agent_ids=badcase_request.sub_agent_ids,
            knowledge_base_display_names=badcase_request.knowledge_base_display_names,
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "Success",
                "data": {
                    "optimized_content": result.optimized_content,
                    "section_type": result.section_type,
                    "section_title": result.section_title,
                    "original_content": result.original_content,
                }
            },
            headers={"X-Prompt-Source": result.source},
        )
    except NexentCapabilityError as e:
        return JSONResponse(
            status_code=HTTPStatus.BAD_REQUEST,
            content={"message": str(e)},
        )


@router.post("/optimize/from_debug")
async def optimize_prompt_from_debug_api(
        optimize_request: OptimizePromptFromDebugRequest,
        http_request: Request,
        authorization: Optional[str] = Header(None)
):
    _, tenant_id, language = get_current_user_info(
        authorization, http_request)

    service = PromptOptimizationService(
        model_id=optimize_request.model_id,
        tenant_id=tenant_id,
        language=language,
    )

    try:
        result = service.optimize_from_debug(
            agent_id=optimize_request.agent_id,
            feedback=optimize_request.feedback,
            selected=optimize_request.selected,
            history=optimize_request.history,
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "Success",
                "data": {
                    "original_full_prompt": result.original_content,
                    "optimized_full_prompt": result.optimized_content,
                }
            },
            headers={"X-Prompt-Source": result.source},
        )
    except NexentCapabilityError as e:
        return JSONResponse(
            status_code=HTTPStatus.BAD_REQUEST,
            content={"message": str(e)},
        )
    except Exception as exc:
        logger.exception(f"Error occurred while optimizing prompt from debug: {exc}")
        raise
