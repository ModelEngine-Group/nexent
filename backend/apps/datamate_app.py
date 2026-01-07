import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Path
from fastapi.responses import JSONResponse
from http import HTTPStatus

from services.datamate_service import (
    sync_datamate_knowledge_bases_records,
    fetch_datamate_knowledge_base_file_list
)
from utils.auth_utils import get_current_user_id

router = APIRouter(prefix="/datamate")
logger = logging.getLogger("datamate_app")




@router.post("/sync_and_create_records")
async def sync_datamate_and_create_records_endpoint(
    authorization: Optional[str] = Header(None)
):
    """Sync DataMate knowledge bases and create knowledge records in local database."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)

        return await sync_datamate_knowledge_bases_records(
            tenant_id=tenant_id,
            user_id=user_id
        )
    except Exception as e:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error syncing DataMate knowledge bases and creating records: {str(e)}")


@router.get("/{knowledge_base_id}/files")
async def get_datamate_knowledge_base_files_endpoint(
    knowledge_base_id: str = Path(..., description="ID of the DataMate knowledge base"),
    authorization: Optional[str] = Header(None)
):
    """Get all files from a DataMate knowledge base."""
    try:
        result = await fetch_datamate_knowledge_base_file_list(knowledge_base_id)
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except Exception as e:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error fetching DataMate knowledge base files: {str(e)}")
