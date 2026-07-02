"""
RAGFlow App Layer
FastAPI endpoints for RAGFlow knowledge base operations.
"""
import logging
from http import HTTPStatus
from typing import Annotated, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse

from consts.error_code import ErrorCode
from consts.exceptions import AppException
from services.ragflow_service import fetch_ragflow_datasets_impl

router = APIRouter(prefix="/ragflow")
logger = logging.getLogger("ragflow_app")


@router.get("/datasets")
async def fetch_ragflow_datasets_api(
    ragflow_api_base: Annotated[str, Query(description="RAGFlow API base URL")],
    api_key: Annotated[str, Query(description="RAGFlow API key")],
    authorization: Annotated[Optional[str], Header()] = None
):
    """
    Fetch datasets (knowledge bases) from RAGFlow API.
    """
    try:
        ragflow_api_base = ragflow_api_base.rstrip('/')
    except Exception as e:
        logger.exception("Invalid RAGFlow configuration")
        raise AppException(ErrorCode.RAGFLOW_CONFIG_INVALID,
                           f"Invalid URL format: {str(e)}")

    try:
        result = fetch_ragflow_datasets_impl(
            ragflow_api_base=ragflow_api_base,
            api_key=api_key,
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content=result
        )
    except AppException:
        raise
    except Exception as e:
        logger.exception("Failed to fetch RAGFlow datasets")
        raise AppException(ErrorCode.RAGFLOW_SERVICE_ERROR,
                           f"Failed to fetch RAGFlow datasets: {str(e)}")
