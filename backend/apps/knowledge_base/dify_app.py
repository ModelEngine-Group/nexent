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

from services.knowledge_base.dify_service import fetch_dify_datasets_impl
from utils.auth_utils import get_current_user_id

router = APIRouter(prefix="/dify")
logger = logging.getLogger("dify_app")


@router.get("/datasets")
async def fetch_dify_datasets_api(
    dify_api_base: str = Query(..., description="Dify API base URL"),
    api_key: str = Query(..., description="Dify API key"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    authorization: Optional[str] = Header(None)
):
    """
    Fetch datasets (knowledge bases) from Dify API.

    Returns knowledge bases in a format consistent with DataMate for frontend compatibility.
    """
    try:
        _, tenant_id = get_current_user_id(authorization)
        result = fetch_dify_datasets_impl(
            dify_api_base=dify_api_base,
            api_key=api_key,
            page=page,
            page_size=page_size
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content=result
        )
    except ValueError as e:
        logger.warning(f"Invalid Dify configuration: {e}")
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to fetch Dify datasets: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch Dify datasets: {str(e)}"
        )
