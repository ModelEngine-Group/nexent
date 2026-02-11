import logging
from http import HTTPStatus

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from consts.const import DEPLOYMENT_VERSION, APP_VERSION

logger = logging.getLogger("tenant_config_app")
router = APIRouter(prefix="/tenant_config")


@router.get("/deployment_version")
def get_deployment_version():
    """
    Get current deployment version (speed or full)
    """
    try:
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"deployment_version": DEPLOYMENT_VERSION,
                     "app_version": APP_VERSION,
                     "status": "success"}
        )
    except Exception as e:
        logger.error(f"Failed to get deployment version, error: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to get deployment version"
        )



