import logging
from http import HTTPStatus
from typing import Optional

from fastapi import APIRouter, Header, Request, HTTPException
from fastapi.responses import JSONResponse

from consts.const import DATAMATE_URL
from consts.model import GlobalConfig
from services.config_sync_service import save_config_impl, load_config_impl
from utils.auth_utils import get_current_user_id, get_current_user_info
from utils.config_utils import tenant_config_manager

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
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST,
                            detail="Failed to save configuration.")


@router.post("/save_datamate_url")
async def save_datamate_url(data: dict, authorization: Optional[str] = Header(None)):
    """
    Save DataMate URL configuration

    Args:
        data: Dictionary containing datamate_url

    Returns:
        JSONResponse: Success message
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        datamate_url = data.get("datamate_url", "").strip()

        if datamate_url:
            tenant_config_manager.set_single_config(
                user_id, tenant_id, DATAMATE_URL, datamate_url)
            logger.info(f"DataMate URL saved successfully")
        else:
            # If empty, delete the configuration
            tenant_config_manager.delete_single_config(tenant_id, DATAMATE_URL)
            logger.info("DataMate URL deleted (empty value)")

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"message": "DataMate URL saved successfully",
                     "status": "saved"}
        )
    except Exception as e:
        logger.error(f"Failed to save DataMate URL: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST,
                            detail="Failed to save DataMate URL.")


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
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST,
                            detail="Failed to load configuration.")
