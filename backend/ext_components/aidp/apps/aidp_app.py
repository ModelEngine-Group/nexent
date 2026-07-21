"""
AIDP App Layer
FastAPI endpoints for AIDP knowledge base list proxy.
"""
import logging
import os
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from consts.error_code import ErrorCode
from consts.exceptions import AppException
from ext_components.aidp.services.aidp_service import (
    fetch_aidp_knowledge_bases_impl,
    fetch_all_aidp_knowledge_bases_impl,
)

router = APIRouter(prefix="/aidp")
logger = logging.getLogger("aidp_app")


def _get_aidp_credentials() -> tuple[str, str]:
    server_url = os.environ.get("AIDP_SERVER_URL", "")
    api_key = os.environ.get("AIDP_API_KEY", "")
    return server_url, api_key


@router.get("/knowledge-bases")
async def fetch_aidp_knowledge_bases_api(
    page: Annotated[int, Query(ge=1, description="Page number starting from 1")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Page size from 1 to 100")] = 10,
) -> JSONResponse:
    """Fetch a single page of knowledge bases from the external AIDP API."""
    try:
        server_url, api_key = _get_aidp_credentials()
        result = fetch_aidp_knowledge_bases_impl(
            server_url=server_url,
            api_key=api_key,
            page=page,
            page_size=page_size,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except AppException:
        raise
    except Exception as e:
        logger.exception("Failed to fetch AIDP knowledge bases: %s", e)
        raise AppException(
            ErrorCode.AIDP_SERVICE_ERROR,
            f"Failed to fetch AIDP knowledge bases: {str(e)}",
        )


@router.get("/knowledge-bases-all")
async def fetch_all_aidp_knowledge_bases_api() -> JSONResponse:
    """Fetch ALL knowledge bases from AIDP (accumulates every page internally).

    Use this when you need the total count and want to handle pagination
    entirely on the client side.
    """
    try:
        server_url, api_key = _get_aidp_credentials()
        result = fetch_all_aidp_knowledge_bases_impl(
            server_url=server_url,
            api_key=api_key,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except AppException:
        raise
    except Exception as e:
        logger.exception("Failed to fetch all AIDP knowledge bases: %s", e)
        raise AppException(
            ErrorCode.AIDP_SERVICE_ERROR,
            f"Failed to fetch all AIDP knowledge bases: {str(e)}",
        )
