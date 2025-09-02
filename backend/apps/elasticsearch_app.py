import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Path, Query
from nexent.vector_database.elasticsearch_core import ElasticSearchCore

from consts.model import IndexingResponse
from database.knowledge_db import delete_knowledge_record, get_knowledge_record
from services.elasticsearch_service import ElasticSearchService, get_embedding_model, get_es_core
from services.redis_service import get_redis_service
from utils.auth_utils import get_current_user_id

router = APIRouter(prefix="/indices")
service = ElasticSearchService()
logger = logging.getLogger("elasticsearch_app")


@router.get("/check_exist/{index_name}")
async def check_knowledge_base_exist(
        index_name: str = Path(..., description="Name of the index to check"),
        es_core: ElasticSearchCore = Depends(get_es_core),
        authorization: Optional[str] = Header(None)
):
    """Check if a knowledge base name exists and in which scope."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)

        # 1. Check index existence in ES and corresponding record in PG
        es_exists = es_core.client.indices.exists(index=index_name)
        pg_record = get_knowledge_record({"index_name": index_name})

        # Case A: Orphan in ES only (exists in ES, missing in PG)
        if es_exists and not pg_record:
            logger.warning(
                f"Detected orphan knowledge base '{index_name}' – present in ES, absent in PG. Deleting ES index only.")
            try:
                es_core.delete_index(index_name)
                # Clean up Redis records related to this index to avoid stale tasks
                try:
                    from services.redis_service import get_redis_service
                    redis_service = get_redis_service()
                    redis_cleanup = redis_service.delete_knowledgebase_records(
                        index_name)
                    logger.debug(
                        f"Redis cleanup for orphan index '{index_name}': {redis_cleanup['total_deleted']} records removed")
                except Exception as redis_error:
                    logger.warning(
                        f"Redis cleanup failed for orphan index '{index_name}': {str(redis_error)}")
                return {
                    "status": "error_cleaning_orphans",
                    "action": "cleaned_es"
                }
            except Exception as e:
                logger.error(
                    f"Failed to delete orphan ES index '{index_name}': {str(e)}")
                # Still return orphan status so frontend knows it requires attention
                return {"status": "error_cleaning_orphans", "error": True}

        # Case B: Orphan in PG only (missing in ES, present in PG)
        if not es_exists and pg_record:
            logger.warning(
                f"Detected orphan knowledge base '{index_name}' – present in PG, absent in ES. Deleting PG record only.")
            try:
                delete_knowledge_record(
                    {"index_name": index_name, "user_id": user_id})
                return {"status": "error_cleaning_orphans", "action": "cleaned_pg"}
            except Exception as e:
                logger.error(
                    f"Failed to delete orphan PG record for '{index_name}': {str(e)}")
                return {"status": "error_cleaning_orphans", "error": True}

        # Case C: Index/record both absent -> name is available
        if not es_exists and not pg_record:
            return {"status": "available"}

        # Case D: Index and record both exist – check tenant ownership
        record_tenant_id = pg_record.get('tenant_id') if pg_record else None
        if str(record_tenant_id) == str(tenant_id):
            return {"status": "exists_in_tenant"}
        else:
            return {"status": "exists_in_other_tenant"}

    except Exception as e:
        logger.error(
            f"Error checking knowledge base existence for '{index_name}': {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Error checking existence for index: {str(e)}")


@router.post("/{index_name}")
def create_new_index(
        index_name: str = Path(..., description="Name of the index to create"),
        embedding_dim: Optional[int] = Query(
            None, description="Dimension of the embedding vectors"),
        es_core: ElasticSearchCore = Depends(get_es_core),
        authorization: Optional[str] = Header(None)
):
    """Create a new vector index and store it in the knowledge table"""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        return ElasticSearchService.create_index(index_name, embedding_dim, es_core, user_id, tenant_id)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error creating index: {str(e)}")


@router.delete("/{index_name}")
async def delete_index(
        index_name: str = Path(..., description="Name of the index to delete"),
        es_core: ElasticSearchCore = Depends(get_es_core),
        authorization: Optional[str] = Header(None)
):
    """Delete an index and all its related data by calling the centralized service."""
    logger.debug(f"Received request to delete knowledge base: {index_name}")
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        # Call the centralized full deletion service
        result = await ElasticSearchService.full_delete_knowledge_base(index_name, es_core, user_id)
        return result
    except Exception as e:
        logger.error(
            f"Error during API call to delete index '{index_name}': {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Error deleting index: {str(e)}")


@router.get("")
def get_list_indices(
        pattern: str = Query("*", description="Pattern to match index names"),
        include_stats: bool = Query(
            False, description="Whether to include index stats"),
        es_core: ElasticSearchCore = Depends(get_es_core),
        authorization: Optional[str] = Header(None),
):
    """List all user indices with optional stats"""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        return ElasticSearchService.list_indices(pattern, include_stats, tenant_id, es_core)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error get index: {str(e)}")


# Document Operations
@router.post("/{index_name}/documents", response_model=IndexingResponse)
def create_index_documents(
        index_name: str = Path(..., description="Name of the index"),
        data: List[Dict[str, Any]
                   ] = Body(..., description="Document List to process"),
        es_core: ElasticSearchCore = Depends(get_es_core),
        authorization: Optional[str] = Header(None)
):
    """
    Index documents with embeddings, creating the index if it doesn't exist.
    Accepts a document list from data processing.
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        embedding_model = get_embedding_model(tenant_id)
        return ElasticSearchService.index_documents(embedding_model, index_name, data, es_core)
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error indexing documents: {error_msg}")
        raise HTTPException(
            status_code=500, detail=f"Error indexing documents: {error_msg}")


@router.get("/{index_name}/files")
async def get_index_files(
        index_name: str = Path(..., description="Name of the index"),
        es_core: ElasticSearchCore = Depends(get_es_core)
):
    """Get all files from an index, including those that are not yet stored in ES"""
    try:
        result = await ElasticSearchService.list_files(index_name, include_chunks=False, es_core=es_core)
        # Transform result to match frontend expectations
        return {
            "status": "success",
            "files": result.get("files", [])
        }
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error indexing documents: {error_msg}")
        raise HTTPException(
            status_code=500, detail=f"Error indexing documents: {error_msg}")


@router.delete("/{index_name}/documents")
def delete_documents(
        index_name: str = Path(..., description="Name of the index"),
        path_or_url: str = Query(...,
                                 description="Path or URL of documents to delete"),
        es_core: ElasticSearchCore = Depends(get_es_core)
):
    """Delete documents by path or URL and clean up related Redis records"""
    try:
        # First delete the documents using existing service
        result = ElasticSearchService.delete_documents(
            index_name, path_or_url, es_core)

        # Then clean up Redis records related to this specific document
        try:
            redis_service = get_redis_service()
            redis_cleanup_result = redis_service.delete_document_records(
                index_name, path_or_url)

            # Add Redis cleanup info to the result
            result["redis_cleanup"] = redis_cleanup_result

            # Update the message to include Redis cleanup info
            original_message = result.get(
                "message", "Documents deleted successfully")
            result["message"] = (
                f"{original_message}. "
                f"Cleaned up {redis_cleanup_result['total_deleted']} Redis records "
                f"({redis_cleanup_result['celery_tasks_deleted']} tasks, "
                f"{redis_cleanup_result['cache_keys_deleted']} cache keys)."
            )

            if redis_cleanup_result.get("errors"):
                result["redis_warnings"] = redis_cleanup_result["errors"]

        except Exception as redis_error:
            logger.warning(
                f"Redis cleanup failed for document {path_or_url} in index {index_name}: {str(redis_error)}")
            result["redis_cleanup_error"] = str(redis_error)
            original_message = result.get(
                "message", "Documents deleted successfully")
            result[
                "message"] = f"{original_message}, but Redis cleanup encountered an error: {str(redis_error)}"

        return result

    except HTTPException as e:
        raise HTTPException(
            status_code=500, detail=f"Error delete indexing documents: {e}")


# Health check
@router.get("/health")
def health_check(es_core: ElasticSearchCore = Depends(get_es_core)):
    """Check API and Elasticsearch health"""
    try:
        # Try to list indices as a health check
        return ElasticSearchService.health_check(es_core)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{str(e)}")
