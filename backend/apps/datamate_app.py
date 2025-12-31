import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Path
from fastapi.responses import JSONResponse
from http import HTTPStatus

from services.datamate_service import (
    sync_datamate_knowledge_bases,
    fetch_datamate_knowledge_bases,
    fetch_datamate_knowledge_base_file_list
)
from utils.auth_utils import get_current_user_id

router = APIRouter(prefix="/datamate")
logger = logging.getLogger("datamate_app")


@router.get("/knowledge_bases")
async def get_datamate_knowledge_bases_endpoint(
    authorization: Optional[str] = Header(None)
):
    """Get list of DataMate knowledge bases."""
    try:
        knowledge_bases = await fetch_datamate_knowledge_bases()

        # Transform to the same format as list_indices method
        indices = []
        indices_info = []

        for kb in knowledge_bases:
            kb_id = kb.get("id")
            kb_name = kb.get("name") or kb_id

            # Get stats from the knowledge base data
            stats = kb.get("stats", {})
            chunk_count = kb.get("chunkCount", 0)
            doc_count = kb.get("docCount", 0)

            indices.append(kb_name)
            indices_info.append({
                "name": kb_id,  # Internal index name (used as ID)
                "display_name": kb_name,  # User-facing knowledge base name
                "stats": {
                    "base_info": {
                        "doc_count": doc_count,
                        "chunk_count": chunk_count,
                        "creation_date": kb.get("createdAt"),
                        "update_date": kb.get("updatedAt"),
                        "embedding_model": kb.get("embeddingModel", "unknown"),
                    }
                }
            })

        return {
            "indices": indices,
            "count": len(indices),
            "indices_info": indices_info,
        }
    except Exception as e:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error fetching DataMate knowledge bases: {str(e)}")


@router.post("/sync")
async def sync_datamate_knowledge_bases_endpoint(
    authorization: Optional[str] = Header(None)
):
    """Sync DataMate knowledge bases and their files."""
    try:
        return await sync_datamate_knowledge_bases()
    except Exception as e:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error syncing DataMate knowledge bases: {str(e)}")


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
