"""
Dify App Layer
FastAPI endpoints for Dify knowledge base operations.

This module provides API endpoints to interact with Dify's datasets API,
including fetching knowledge bases and transforming responses to a format
compatible with the frontend.
"""
import logging
from http import HTTPStatus
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse

from consts.error_code import ErrorCode
from consts.exceptions import AppException
from services.dify_service import fetch_dify_datasets_impl
from utils.auth_utils import get_current_user_id

router = APIRouter(prefix="/dify")
logger = logging.getLogger("dify_app")


@router.get("/datasets")
async def fetch_dify_datasets_api(
    dify_api_base: str = Query(..., description="Dify API base URL"),
    api_key: str = Query(..., description="Dify API key"),
    authorization: Optional[str] = Header(None)
):
    """
    Fetch datasets (knowledge bases) from Dify API.

    Returns knowledge bases in a format consistent with DataMate for frontend compatibility.
    """
    try:
        # Normalize URL by removing trailing slash
        dify_api_base = dify_api_base.rstrip('/')
    except Exception as e:
        logger.error(f"Invalid Dify configuration: {e}")
        raise AppException(ErrorCode.DIFY_CONFIG_INVALID,
                           f"Invalid URL format: {str(e)}")


    try:
        result = fetch_dify_datasets_impl(
            dify_api_base=dify_api_base,
            api_key=api_key,
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content=result
        )
    except AppException:
        # Re-raise AppException to be handled by global middleware
        raise
    except Exception as e:
        logger.error(f"Failed to fetch Dify datasets: {e}")
        raise AppException(ErrorCode.DIFY_SERVICE_ERROR,
                           f"Failed to fetch Dify datasets: {str(e)}")
