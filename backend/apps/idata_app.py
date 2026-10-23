"""
iData App Layer
FastAPI endpoints for iData knowledge space operations.

This module provides API endpoints to interact with iData's API,
including fetching knowledge spaces and transforming responses to a format
compatible with the frontend.
"""
import logging
from http import HTTPStatus

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from consts.error_code import ErrorCode
from consts.exceptions import AppException
from services.idata_service import (
    fetch_idata_knowledge_spaces_impl,
    fetch_idata_datasets_impl,
)

router = APIRouter(prefix="/idata")
logger = logging.getLogger("idata_app")


@router.get("/knowledge-space")
async def fetch_idata_knowledge_spaces_api(
    idata_api_base: str = Query(..., description="iData API base URL"),
    api_key: str = Query(..., description="iData API key"),
    user_id: str = Query(..., description="iData user ID"),
):
    """
    Fetch knowledge spaces from iData API.

    Returns knowledge spaces in a format with id and name for frontend compatibility.
    """
    try:
        # Normalize URL by removing trailing slash
        idata_api_base = idata_api_base.rstrip('/')
    except Exception as e:
        logger.error(f"Invalid iData configuration: {e}")
        raise AppException(
            ErrorCode.IDATA_CONFIG_INVALID,
            f"Invalid URL format: {str(e)}"
        )

    try:
        result = fetch_idata_knowledge_spaces_impl(
            idata_api_base=idata_api_base,
            api_key=api_key,
            user_id=user_id,
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content=result
        )
    except AppException:
        # Re-raise AppException to be handled by global middleware
        raise
    except Exception as e:
        logger.error(f"Failed to fetch iData knowledge spaces: {e}")
        raise AppException(
            ErrorCode.IDATA_SERVICE_ERROR,
            f"Failed to fetch iData knowledge spaces: {str(e)}"
        )


@router.get("/datasets")
async def fetch_idata_datasets_api(
    idata_api_base: str = Query(..., description="iData API base URL"),
    api_key: str = Query(..., description="iData API key"),
    user_id: str = Query(..., description="iData user ID"),
    knowledge_space_id: str = Query(..., description="Knowledge space ID"),
):
    """
    Fetch datasets (knowledge bases) from iData API.

    Returns knowledge bases in a format consistent with DataMate for frontend compatibility.
    """
    try:
        # Normalize URL by removing trailing slash
        idata_api_base = idata_api_base.rstrip('/')
    except Exception as e:
        logger.error(f"Invalid iData configuration: {e}")
        raise AppException(
            ErrorCode.IDATA_CONFIG_INVALID,
            f"Invalid URL format: {str(e)}"
        )

    try:
        result = fetch_idata_datasets_impl(
            idata_api_base=idata_api_base,
            api_key=api_key,
            user_id=user_id,
            knowledge_space_id=knowledge_space_id,
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content=result
        )
    except AppException:
        # Re-raise AppException to be handled by global middleware
        raise
    except Exception as e:
        logger.error(f"Failed to fetch iData datasets: {e}")
        raise AppException(
            ErrorCode.IDATA_SERVICE_ERROR,
            f"Failed to fetch iData datasets: {str(e)}"
        )
