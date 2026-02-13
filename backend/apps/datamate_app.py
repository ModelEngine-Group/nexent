import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Path
from fastapi.responses import JSONResponse
from fastapi import Body
from pydantic import BaseModel
from http import HTTPStatus

from services.datamate_service import (
    sync_datamate_knowledge_bases_and_create_records,
    fetch_datamate_knowledge_base_file_list,
    check_datamate_connection
)
from utils.auth_utils import get_current_user_id
from consts.exceptions import DataMateConnectionError

router = APIRouter(prefix="/datamate")
logger = logging.getLogger("datamate_app")


class SyncDatamateRequest(BaseModel):
    """Request body for syncing DataMate knowledge bases."""
    datamate_url: Optional[str] = None


@router.post("/sync_datamate_knowledges")
async def sync_datamate_knowledges(
    authorization: Optional[str] = Header(None),
    request: SyncDatamateRequest = Body(None)
):
    """Sync DataMate knowledge bases and create knowledge records in local database."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)

        return await sync_datamate_knowledge_bases_and_create_records(
            tenant_id=tenant_id,
            user_id=user_id,
            datamate_url=request.datamate_url if request else None
        )
    except DataMateConnectionError as e:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error syncing DataMate knowledge bases and creating records: {str(e)}")


@router.get("/{knowledge_base_id}/files")
async def get_datamate_knowledge_base_files_endpoint(
    knowledge_base_id: str = Path(...,
                                  description="ID of the DataMate knowledge base"),
    authorization: Optional[str] = Header(None)
):
    """Get all files from a specific DataMate knowledge base."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        result = await fetch_datamate_knowledge_base_file_list(knowledge_base_id, tenant_id)
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except Exception as e:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error fetching DataMate knowledge base files: {str(e)}")


@router.post("/test_connection")
async def test_datamate_connection_endpoint(
    authorization: Optional[str] = Header(None),
    request: SyncDatamateRequest = Body(None)
):
    """
    Test connection to DataMate server.

    Returns:
        JSON with success status and message
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        datamate_url = request.datamate_url if request else None

        # Test the connection
        is_connected, error_message = await check_datamate_connection(tenant_id, datamate_url)

        if is_connected:
            return JSONResponse(
                status_code=HTTPStatus.OK,
                content={"success": True, "message": "Connection successful"}
            )
        else:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail=f"Cannot connect to DataMate server: {error_message}"
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error testing DataMate connection: {str(e)}"
        )
