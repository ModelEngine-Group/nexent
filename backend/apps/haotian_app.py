"""
Haotian App Layer
FastAPI endpoints for Haotian external knowledge base operations.

This module provides proxy APIs so the frontend does not call external services directly.
"""

import logging
from http import HTTPStatus
from typing import Optional, Dict

from fastapi import APIRouter, Header, HTTPException, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from services.haotian_service import (
    fetch_haotian_knowledge_sets_impl,
    test_haotian_connection_impl,
)

router = APIRouter(prefix="/haotian")
logger = logging.getLogger("haotian_app")


class HaotianListRequest(BaseModel):
    list_url: str = Field(..., description="Haotian knowledge sets list URL")
    authorization: str = Field(
        ..., description="Authorization header value, e.g. 'Bearer xxx'"
    )


class HaotianTestConnectionRequest(BaseModel):
    list_url: str = Field(..., description="Haotian knowledge sets list URL")
    authorization: str = Field(
        ..., description="Authorization header value, e.g. 'Bearer xxx'"
    )


@router.post("/knowledge-sets")
async def fetch_haotian_knowledge_sets_api(
    authorization: Optional[str] = Header(None),
    request: HaotianListRequest = Body(...),
) -> JSONResponse:
    """
    Fetch knowledge sets from the external Haotian list_url and return a filtered/normalized payload.
    """
    _ = authorization
    try:
        result: Dict[str, any] = await fetch_haotian_knowledge_sets_impl(
            list_url=request.list_url,
            external_authorization=request.authorization,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except Exception as e:
        logger.error(f"Failed to fetch Haotian knowledge sets: {e}")
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=f"Failed to fetch Haotian knowledge sets: {str(e)}",
        )


@router.post("/test-connection")
async def test_haotian_connection_api(
    authorization: Optional[str] = Header(None),
    request: HaotianTestConnectionRequest = Body(...),
) -> JSONResponse:
    """
    Test connection to Haotian list_url using the provided authorization.
    """
    _ = authorization
    try:
        ok, error_message = await test_haotian_connection_impl(
            list_url=request.list_url,
            external_authorization=request.authorization,
        )
        if ok:
            return JSONResponse(
                status_code=HTTPStatus.OK,
                content={"success": True, "message": "Connection successful"},
            )
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=f"Cannot connect to Haotian server: {error_message}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error testing Haotian connection: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error testing Haotian connection: {str(e)}",
        )
