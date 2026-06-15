"""
AIDP App Layer
FastAPI endpoints for AIDP knowledge base list proxy.
"""
import logging
from http import HTTPStatus

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from consts.error_code import ErrorCode
from consts.exceptions import AppException
from services.aidp_service import fetch_aidp_knowledge_bases_impl

router = APIRouter(prefix="/aidp")
logger = logging.getLogger("aidp_app")


@router.get("/knowledge-bases")
async def fetch_aidp_knowledge_bases_api(
    server_url: str = Query(..., description="AIDP API server URL"),
    api_key: str = Query(..., description="AIDP API key"),
    page: int = Query(1, ge=1, description="Page number starting from 1"),
    page_size: int = Query(20, ge=1, le=100, description="Page size from 1 to 100"),
) -> JSONResponse:
    """Fetch paginated knowledge bases from the external AIDP API."""
    try:
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
        logger.error("Failed to fetch AIDP knowledge bases: %s", e)
        raise AppException(
            ErrorCode.AIDP_SERVICE_ERROR,
            f"Failed to fetch AIDP knowledge bases: {str(e)}",
        )
