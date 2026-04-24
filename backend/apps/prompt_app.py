import logging
from http import HTTPStatus
from typing import Optional
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from consts.model import (
    GeneratePromptRequest,
    OptimizePromptRequest,
    PromptTemplateCreateRequest,
    PromptTemplateUpdateRequest,
)
from consts.exceptions import AppException
from services.prompt_service import (
    gen_optimize_prompt_streamable,
    gen_system_prompt_streamable,
)
from services.prompt_template_service import (
    create_prompt_template,
    delete_prompt_template,
    list_prompt_templates,
    update_prompt_template,
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
            user_id=user_id,
            tenant_id=tenant_id,
            language=language,
            template_id=prompt_request.template_id,
            tool_ids=prompt_request.tool_ids,
            sub_agent_ids=prompt_request.sub_agent_ids
        ), media_type="text/event-stream")
    except Exception as e:
        logger.exception(f"Error occurred while generating system prompt: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Error occurred while generating system prompt.")


@router.post("/optimize")
async def optimize_prompt_api(
        prompt_request: OptimizePromptRequest,
        http_request: Request,
        authorization: Optional[str] = Header(None)
):
    try:
        user_id, tenant_id, language = get_current_user_info(
            authorization, http_request)
        return StreamingResponse(gen_optimize_prompt_streamable(
            agent_id=prompt_request.agent_id,
            model_id=prompt_request.model_id,
            task_description=prompt_request.task_description,
            prompt_type=prompt_request.prompt_type,
            original_content=prompt_request.original_content,
            feedback=prompt_request.feedback,
            user_id=user_id,
            tenant_id=tenant_id,
            language=language,
            tool_ids=prompt_request.tool_ids,
            sub_agent_ids=prompt_request.sub_agent_ids
        ), media_type="text/event-stream")
    except Exception as e:
        logger.exception(f"Error occurred while optimizing prompt: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Error occurred while optimizing prompt.")


@router.get("/templates")
async def list_prompt_templates_api(
    authorization: Optional[str] = Header(None)
) -> JSONResponse:
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization)
        templates = list_prompt_templates(tenant_id, user_id=user_id)
        return JSONResponse(content={"templates": templates})
    except Exception as e:
        logger.exception(f"Error occurred while listing prompt templates: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Error occurred while listing prompt templates."
        )


@router.post("/templates")
async def create_prompt_template_api(
    request: PromptTemplateCreateRequest,
    authorization: Optional[str] = Header(None)
) -> JSONResponse:
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization)
        template = create_prompt_template(request.model_dump(), tenant_id=tenant_id, user_id=user_id)
        return JSONResponse(content=template, status_code=201)
    except AppException as e:
        raise HTTPException(status_code=e.http_status, detail=e.to_dict())
    except Exception as e:
        logger.exception(f"Error occurred while creating prompt template: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Error occurred while creating prompt template."
        )


@router.put("/templates/{template_id}")
async def update_prompt_template_api(
    template_id: int,
    request: PromptTemplateUpdateRequest,
    authorization: Optional[str] = Header(None)
) -> JSONResponse:
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization)
        template = update_prompt_template(
            template_id=template_id,
            template_data=request.model_dump(exclude_unset=True),
            tenant_id=tenant_id,
            user_id=user_id
        )
        return JSONResponse(content=template)
    except AppException as e:
        raise HTTPException(status_code=e.http_status, detail=e.to_dict())
    except Exception as e:
        logger.exception(f"Error occurred while updating prompt template: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Error occurred while updating prompt template."
        )


@router.delete("/templates/{template_id}")
async def delete_prompt_template_api(
    template_id: int,
    authorization: Optional[str] = Header(None)
) -> JSONResponse:
    try:
        user_id, tenant_id, _ = get_current_user_info(authorization)
        deleted = delete_prompt_template(template_id, tenant_id=tenant_id, user_id=user_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Prompt template not found")
        return JSONResponse(content={"message": "Prompt template deleted successfully"})
    except AppException as e:
        raise HTTPException(status_code=e.http_status, detail=e.to_dict())
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error occurred while deleting prompt template: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Error occurred while deleting prompt template."
        )
