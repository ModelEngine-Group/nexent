"""
Dify API endpoints for knowledge base operations.

This module provides API endpoints for interacting with Dify datasets
(knowledge bases) including listing and fetching dataset information.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from http import HTTPStatus

from services.knowledge_base.dify_service import fetch_dify_datasets_impl
from utils.auth_utils import get_current_user_id

router = APIRouter(prefix="/dify")
logger = logging.getLogger("dify_app")


@router.get("/datasets")
async def list_dify_datasets(
    dify_api_base: str = Query(..., description="Dify API base URL"),
    api_key: str = Query(..., description="Dify API key"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(
        20, ge=1, le=100, description="Number of items per page"),
    authorization: Optional[str] = Header(None)
):
    """
    List all datasets (knowledge bases) from Dify API.

    Returns datasets in DataMate-compatible format for frontend compatibility.
    """
    try:
        logger.info(
            f"Listing Dify datasets, page={page}, page_size={page_size}")

        result = fetch_dify_datasets_impl(
            dify_api_base=dify_api_base,
            api_key=api_key,
            page=page,
            page_size=page_size
        )

        return JSONResponse(status_code=HTTPStatus.OK, content=result)

    except ValueError as e:
        logger.warning(f"Invalid request parameters: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to fetch Dify datasets: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch Dify datasets: {str(e)}"
        )
