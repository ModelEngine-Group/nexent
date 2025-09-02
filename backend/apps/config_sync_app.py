import logging
from http import HTTPStatus
from typing import Optional

from fastapi import APIRouter, Header, Request, HTTPException
from fastapi.responses import JSONResponse

from consts.model import GlobalConfig
from services.config_sync_service import save_config_impl, load_config_impl
from utils.auth_utils import get_current_user_id, get_current_user_info

router = APIRouter(prefix="/config")
logger = logging.getLogger("config_sync_app")


@router.post("/save_config")
async def save_config(config: GlobalConfig, authorization: Optional[str] = Header(None)):
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        logger.info(
            f"Start to save config, user_id: {user_id}, tenant_id: {tenant_id}")
        await save_config_impl(config, tenant_id, user_id)
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"message": "Configuration saved successfully",
                     "status": "saved"}
        )
    except Exception as e:
        logger.error(f"Failed to save configuration: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="Failed to save configuration.")


@router.get("/load_config")
async def load_config(authorization: Optional[str] = Header(None), request: Request = None):
    """
    Load configuration from environment variables

    Returns:
        JSONResponse: JSON object containing configuration content
    """
    try:
        # Build configuration object
        user_id, tenant_id, language = get_current_user_info(
            authorization, request)
        config = await load_config_impl(language, tenant_id)
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"config": config}
        )
    except Exception as e:
        logger.error(f"Failed to load configuration: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="Failed to load configuration.")
