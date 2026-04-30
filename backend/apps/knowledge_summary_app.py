import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Path, Query, Request
from fastapi.responses import StreamingResponse
from nexent.vector_database.base import VectorDatabaseCore

from consts.model import ChangeSummaryRequest
from services.vectordatabase_service import ElasticSearchService, get_vector_db_core
from utils.auth_utils import get_current_user_id, get_current_user_info
from utils.config_utils import tenant_config_manager

router = APIRouter(prefix="/summary")
logger = logging.getLogger("knowledge_summary_app")


@router.post("/{index_name}/auto_summary")
async def auto_summary(
        http_request: Request,
        index_name: str = Path(...,
                               description="Name of the index to get documents from"),
        batch_size: int = Query(
            1000, description="Number of documents to retrieve per batch"),
        model_id: Optional[int] = Query(
            None, description="Model ID to use for summary generation"),
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
        authorization: Optional[str] = Header(None)
):
    """Summary Elasticsearch index_name by model"""
    try:
        _, tenant_id, language = get_current_user_info(
            authorization, http_request)
        service = ElasticSearchService()

        # Get model_id from tenant config if not provided
        if model_id is None and tenant_id:
            try:
                tenant_config = tenant_config_manager.load_config(tenant_id)
                model_id_str = tenant_config.get("LLM_ID")
                if model_id_str:
                    model_id = int(model_id_str)
                    logger.info(f"Using LLM_ID {model_id} from tenant config for auto-summary")
                else:
                    logger.warning(f"No LLM_ID configured for tenant {tenant_id}, summary may be placeholder")
            except Exception as e:
                logger.warning(f"Failed to get LLM_ID from tenant config: {e}")

        return await service.summary_index_name(
            index_name=index_name,
            batch_size=batch_size,
            vdb_core=vdb_core,
            tenant_id=tenant_id,
            language=language,
            model_id=model_id
        )
    except Exception as e:
        logger.error(
            f"Knowledge base summary generation failed: {e}", exc_info=True)
        return StreamingResponse(
            "data: {{\"status\": \"error\", \"message\": \"Knowledge base summary generation failed due to an internal error.\"}}\n\n",
            media_type="text/event-stream",
            status_code=500
        )


@router.post("/{index_name}/summary")
def change_summary(
        index_name: str = Path(...,
                               description="Name of the index to get documents from"),
        change_summary_request: ChangeSummaryRequest = Body(
            None, description="knowledge base summary"),
        authorization: Optional[str] = Header(None)
):
    """Summary Elasticsearch index_name by user"""
    try:
        user_id = get_current_user_id(authorization)[0]
        summary_result = change_summary_request.summary_result
        return ElasticSearchService().change_summary(index_name=index_name, summary_result=summary_result, user_id=user_id)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Knowledge base summary update failed: {str(e)}")


@router.get("/{index_name}/summary")
def get_summary(
        index_name: str = Path(...,
                               description="Name of the index to get documents from"),
):
    """Get Elasticsearch index_name Summary"""
    try:
        # Try to list indices as a health check
        return ElasticSearchService().get_summary(index_name=index_name)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get knowledge base summary: {str(e)}")
