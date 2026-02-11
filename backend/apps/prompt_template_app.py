import logging
from http import HTTPStatus
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from consts.model import (
    PromptTemplateCreateRequest,
    PromptTemplateUpdateRequest,
    PromptTemplateDeleteRequest,
)
from services.prompt_template_service import (
    list_templates,
    create_template,
    update_template,
    delete_template,
)
from utils.auth_utils import get_current_user_id

router = APIRouter(prefix="/prompt_template")
logger = logging.getLogger("prompt_template_app")


@router.get("/list")
async def list_prompt_templates_api(
    keyword: Optional[str] = Query(default=None),
    authorization: Optional[str] = Header(None)
):
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        templates = list_templates(tenant_id=tenant_id, user_id=user_id, keyword=keyword)
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"message": "Templates retrieved successfully", "data": jsonable_encoder(templates)}
        )
    except Exception as e:
        logger.error(f"Failed to list prompt templates: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Failed to list prompt templates")


@router.post("/create")
async def create_prompt_template_api(
    request: PromptTemplateCreateRequest,
    authorization: Optional[str] = Header(None)
):
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        template = create_template(tenant_id=tenant_id, user_id=user_id, payload=request.dict())
        return JSONResponse(
            status_code=HTTPStatus.CREATED,
            content={"message": "Template created successfully", "data": jsonable_encoder(template)}
        )
    except Exception as e:
        logger.error(f"Failed to create prompt template: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Failed to create prompt template")


@router.post("/update")
async def update_prompt_template_api(
    request: PromptTemplateUpdateRequest,
    authorization: Optional[str] = Header(None)
):
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        template = update_template(
            tenant_id=tenant_id,
            user_id=user_id,
            template_id=request.template_id,
            payload=request.dict(exclude={"template_id"})
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"message": "Template updated successfully", "data": jsonable_encoder(template)}
        )
    except ValueError as e:
        logger.warning(f"Prompt template not found: {e}")
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Prompt template not found")
    except Exception as e:
        logger.error(f"Failed to update prompt template: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Failed to update prompt template")


@router.post("/delete")
async def delete_prompt_template_api(
    request: PromptTemplateDeleteRequest,
    authorization: Optional[str] = Header(None)
):
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        delete_template(tenant_id=tenant_id, user_id=user_id, template_id=request.template_id)
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"message": "Template deleted successfully"}
        )
    except ValueError as e:
        logger.warning(f"Prompt template not found: {e}")
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Prompt template not found")
    except Exception as e:
        logger.error(f"Failed to delete prompt template: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Failed to delete prompt template")
