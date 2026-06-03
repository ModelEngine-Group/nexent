import logging
from http import HTTPStatus
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from starlette.responses import JSONResponse

from consts.exceptions import DuplicateError, NotFoundException, ValidationError
from consts.model import PromptTemplateRequest
from services.prompt_template_service import (
    create_prompt_template_impl,
    delete_prompt_template_impl,
    get_prompt_template_detail_impl,
    list_prompt_templates_impl,
    update_prompt_template_impl,
)
from utils.auth_utils import get_current_user_id

router = APIRouter(prefix="/prompt_templates")
logger = logging.getLogger("prompt_template_app")


@router.get("")
async def list_prompt_templates_api(
    authorization: Optional[str] = Header(None),
):
    """List prompt templates for the current user."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        result = list_prompt_templates_impl(tenant_id=tenant_id, user_id=user_id)
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except Exception as exc:
        logger.error(f"Prompt template list error: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Prompt template list error.",
        )


@router.get("/{template_id}")
async def get_prompt_template_api(
    template_id: int,
    authorization: Optional[str] = Header(None),
):
    """Get prompt template detail."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        result = get_prompt_template_detail_impl(
            template_id=template_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except NotFoundException as exc:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(exc))
    except Exception as exc:
        logger.error(f"Prompt template detail error: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Prompt template detail error.",
        )


@router.post("")
async def create_prompt_template_api(
    request: PromptTemplateRequest,
    authorization: Optional[str] = Header(None),
):
    """Create a prompt template."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        result = create_prompt_template_impl(
            request=request,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except DuplicateError as exc:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(exc))
    except ValidationError as exc:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        logger.error(f"Prompt template create error: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Prompt template create error.",
        )


@router.put("/{template_id}")
async def update_prompt_template_api(
    template_id: int,
    request: PromptTemplateRequest,
    authorization: Optional[str] = Header(None),
):
    """Update a prompt template."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        result = update_prompt_template_impl(
            template_id=template_id,
            request=request,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except NotFoundException as exc:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(exc))
    except DuplicateError as exc:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(exc))
    except ValidationError as exc:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        logger.error(f"Prompt template update error: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Prompt template update error.",
        )


@router.delete("/{template_id}")
async def delete_prompt_template_api(
    template_id: int,
    authorization: Optional[str] = Header(None),
):
    """Delete a prompt template."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        result = delete_prompt_template_impl(
            template_id=template_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except NotFoundException as exc:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(exc))
    except ValidationError as exc:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        logger.error(f"Prompt template delete error: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Prompt template delete error.",
        )
