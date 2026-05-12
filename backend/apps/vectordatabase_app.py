import logging
import json
from http import HTTPStatus
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Path, Query
from fastapi.responses import JSONResponse
import re

from consts.model import ChunkCreateRequest, ChunkUpdateRequest, HybridSearchRequest, IndexingResponse
from consts.scheduler import VALID_SUMMARY_FREQUENCIES, SUMMARY_FREQUENCY_OPTIONS_FOR_API
from nexent.vector_database.base import VectorDatabaseCore
from services.vectordatabase_service import (
    ElasticSearchService,
    get_embedding_model_by_id,
    get_vector_db_core,
    check_knowledge_base_exist_impl,
    KnowledgeBaseNeedsModelConfigError,
)
from services.redis_service import get_redis_service
from utils.auth_utils import get_current_user_id
from utils.file_management_utils import get_all_files_status
from database.knowledge_db import get_index_name_by_knowledge_name, get_knowledge_record
from database.model_management_db import get_model_by_model_id

router = APIRouter(prefix="/indices")
service = ElasticSearchService()
logger = logging.getLogger("vectordatabase_app")


@router.get("/summary_frequency_options")
async def get_summary_frequency_options():
    """
    Get valid summary frequency options for frontend.
    Frontend should call this API to get the list of valid frequencies.
    """
    return JSONResponse(
        status_code=HTTPStatus.OK,
        content={
            "options": SUMMARY_FREQUENCY_OPTIONS_FOR_API,
            "valid_values": VALID_SUMMARY_FREQUENCIES,
        }
    )

@router.post("/check_exist")
async def check_knowledge_base_exist(
        request: Dict[str, str] = Body(
            ..., description="Request body containing knowledge base name"),
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
        authorization: Optional[str] = Header(None)
):
    """Check if a knowledge base name exists in the current tenant."""
    try:
        knowledge_name = request.get("knowledge_name", "")
        if not knowledge_name:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST, detail="Knowledge base name is required")

        user_id, tenant_id = get_current_user_id(authorization)
        return check_knowledge_base_exist_impl(knowledge_name=knowledge_name, vdb_core=vdb_core, user_id=user_id, tenant_id=tenant_id)
    except Exception as e:
        logger.error(
            f"Error checking knowledge base existence for '{knowledge_name}': {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error checking existence for knowledge base: {str(e)}")


@router.post("/{index_name}")
def create_new_index(
        index_name: str = Path(..., description="Name of the index to create"),
        embedding_dim: Optional[int] = Query(
            None, description="Dimension of the embedding vectors"),
        request: Dict[str, Any] = Body(
            None, description="Request body with optional fields (ingroup_permission, group_ids, embedding_model_name)"),
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
        authorization: Optional[str] = Header(None)
):
    """Create a new vector index and store it in the knowledge table"""
    try:
        user_id, tenant_id = get_current_user_id(authorization)

        # Extract optional fields from request body
        ingroup_permission = None
        group_ids = None
        embedding_model_name = None
        if request:
            ingroup_permission = request.get("ingroup_permission")
            group_ids = request.get("group_ids")
            embedding_model_name = request.get("embedding_model_name")

        # Treat path parameter as user-facing knowledge base name for new creations
        return ElasticSearchService.create_knowledge_base(
            knowledge_name=index_name,
            embedding_dim=embedding_dim,
            vdb_core=vdb_core,
            user_id=user_id,
            tenant_id=tenant_id,
            ingroup_permission=ingroup_permission,
            group_ids=group_ids,
            embedding_model_name=embedding_model_name,
        )
    except Exception as e:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error creating index: {str(e)}")


@router.delete("/{index_name}")
async def delete_index(
        index_name: str = Path(..., description="Name of the index to delete"),
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
        authorization: Optional[str] = Header(None)
):
    """Delete an index and all its related data by calling the centralized service."""
    logger.debug(f"Received request to delete knowledge base: {index_name}")
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        # Call the centralized full deletion service
        result = await ElasticSearchService.full_delete_knowledge_base(index_name, vdb_core, user_id)
        return result
    except Exception as e:
        logger.error(
            f"Error during API call to delete index '{index_name}': {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error deleting index: {str(e)}")


@router.patch("/{index_name}")
async def update_index(
        index_name: str = Path(..., description="Name of the index to update"),
        request: Dict[str, Any] = Body(...,
                                       description="Update payload with knowledge_name, ingroup_permission, group_ids, and/or tenant_id"),
        authorization: Optional[str] = Header(None)
):
    """Update knowledge base information (name, group permission, group assignments)."""
    try:
        user_id, auth_tenant_id = get_current_user_id(authorization)
        # Use explicit tenant_id if provided, otherwise fall back to auth tenant_id
        tenant_id = request.get("tenant_id") or auth_tenant_id

        # Extract update fields
        knowledge_name = request.get("knowledge_name")
        ingroup_permission = request.get("ingroup_permission")
        group_ids = request.get("group_ids")

        # Call service layer to update knowledge base
        result = ElasticSearchService.update_knowledge_base(
            index_name=index_name,
            knowledge_name=knowledge_name,
            ingroup_permission=ingroup_permission,
            group_ids=group_ids,
            tenant_id=tenant_id,
            user_id=user_id,
        )

        if result:
            return JSONResponse(
                status_code=HTTPStatus.OK,
                content={
                    "message": "Knowledge base updated successfully", "status": "success"}
            )
        else:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail=f"Knowledge base '{index_name}' not found"
            )
    except ValueError as exc:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(exc)
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            f"Error updating index '{index_name}': {str(exc)}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error updating index: {str(exc)}")


@router.patch("/{index_name}/summary_frequency")
async def update_summary_frequency_endpoint(
        index_name: Annotated[str, Path(..., description="Name of the index to update")],
        request: Annotated[Dict[str, Any], Body(..., description="Update payload with summary_frequency")],
        authorization: Annotated[Optional[str], Header()] = None,
):
    """Update the auto-summary frequency for a knowledge base."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        summary_frequency = request.get("summary_frequency")

        valid_frequencies = VALID_SUMMARY_FREQUENCIES
        if summary_frequency not in valid_frequencies:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail=f"Invalid summary_frequency. Must be one of: {valid_frequencies}"
            )

        from database.knowledge_db import update_summary_frequency
        success = update_summary_frequency(
            index_name=index_name,
            summary_frequency=summary_frequency,
            _tenant_id=tenant_id,
            user_id=user_id
        )

        if success:
            return JSONResponse(
                status_code=HTTPStatus.OK,
                content={"message": "Summary frequency updated successfully", "status": "success"}
            )
        else:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail=f"Knowledge base '{index_name}' not found"
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error updating summary frequency")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error updating summary frequency: {str(exc)}"
        )


@router.get("/{index_name}/embedding-model-status")
def get_embedding_model_status(
        index_name: str = Path(..., description="Name of the index to check"),
        authorization: Optional[str] = Header(None)
):
    """
    Check the embedding model status of a knowledge base.
    Returns information about whether a model is configured and if an update is needed.

    This endpoint is used by the frontend to determine whether to show
    a dialog prompting the user to select an embedding model for knowledge bases
    that were created before the model ID feature was added.

    Note: The path parameter is the internal index_name.
    """
    try:
        _, tenant_id = get_current_user_id(authorization)

        # Get the knowledge base record by index_name
        knowledge_record = get_knowledge_record({
            "index_name": index_name,
            "tenant_id": tenant_id
        })

        if not knowledge_record:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail=f"Knowledge base '{index_name}' not found"
            )

        # Check if model_id exists
        model_id = knowledge_record.get("embedding_model_id")
        embedding_model_name = knowledge_record.get("embedding_model_name")

        # Get model info if model_id exists
        model_info = None
        if model_id:
            model = get_model_by_model_id(model_id, tenant_id)
            if model:
                model_info = {
                    "model_id": model.get("model_id"),
                    "model_name": model.get("model_name"),
                    "display_name": model.get("display_name"),
                    "model_type": model.get("model_type"),
                }

        # Determine status
        if model_id and model_info:
            status = "configured"
            message = f"Embedding model '{model_info.get('display_name', model_info.get('model_name'))}' is configured"
            needs_config = False
        elif embedding_model_name:
            # Has model name but no model_id (legacy data)
            status = "legacy"
            message = "This knowledge base was created with an older version. Please select an embedding model to ensure proper functionality."
            needs_config = True
        else:
            # No model configured at all
            status = "missing"
            message = "No embedding model configured. Please select an embedding model."
            needs_config = True

        # Get actual internal index_name from the database record
        actual_index_name = knowledge_record.get("index_name")

        return {
            "status": status,
            "needs_config": needs_config,
            "index_name": actual_index_name,
            "knowledge_name": knowledge_record.get("knowledge_name"),
            "model_id": model_id,
            "embedding_model_name": embedding_model_name,
            "model_info": model_info,
            "message": message,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting embedding model status for '{index_name}': {e}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error checking embedding model status: {str(e)}"
        )


@router.put("/{index_name}/embedding-model")
def update_embedding_model(
        index_name: str = Path(..., description="Internal index name of the knowledge base to update"),
        request: Dict[str, Any] = Body(...,
                                       description="Update payload with model_id"),
        authorization: Optional[str] = Header(None)
):
    """
    Update the embedding model for a knowledge base.
    This is used when a user selects an embedding model from the dialog
    for knowledge bases that don't have a model configured.
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)

        model_id = request.get("model_id")
        if not model_id:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail="model_id is required"
            )

        result = ElasticSearchService.update_embedding_model(
            index_name=index_name,
            model_id=model_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content=result
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(exc)
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error updating embedding model for '{index_name}': {exc}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error updating embedding model: {str(exc)}"
        )


@router.get("")
def get_list_indices(
        pattern: str = Query("*", description="Pattern to match index names"),
        include_stats: bool = Query(
            False, description="Whether to include index stats"),
        tenant_id: Optional[str] = Query(
            None, description="Tenant ID for filtering (uses auth if not provided)"),
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
        authorization: Optional[str] = Header(None),
):
    """List all user indices with optional stats"""
    try:
        user_id, auth_tenant_id = get_current_user_id(authorization)
        # Use explicit tenant_id if provided, otherwise fall back to auth tenant_id
        effective_tenant_id = tenant_id or auth_tenant_id
        return ElasticSearchService.list_indices(pattern, include_stats, effective_tenant_id, user_id, vdb_core)
    except Exception as e:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error get index: {str(e)}")


# Document Operations
@router.post("/{index_name}/documents", response_model=IndexingResponse)
def create_index_documents(
        index_name: str = Path(..., description="Name of the index"),
        data: List[Dict[str, Any]
                   ] = Body(..., description="Document List to process"),
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
        authorization: Optional[str] = Header(None),
        task_id: Optional[str] = Header(
            None, alias="X-Task-Id", description="Task ID for progress tracking"),
        large_mode: bool = Query(
            False, description="Force large-batch path when current request chunk count is below threshold"),
):
    """
    Index documents with embeddings, creating the index if it doesn't exist.
    Accepts a document list from data processing.
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)

        # Get the knowledge base record to retrieve the saved embedding model
        knowledge_record = get_knowledge_record({'index_name': index_name})
        saved_embedding_model_id = None
        if knowledge_record:
            saved_embedding_model_id = knowledge_record.get('embedding_model_id')

        # Use the saved model from knowledge base by model_id
        embedding_model, _ = get_embedding_model_by_id(tenant_id, saved_embedding_model_id) if saved_embedding_model_id else (None, None)

        return ElasticSearchService.index_documents(
            embedding_model=embedding_model,
            index_name=index_name,
            data=data,
            vdb_core=vdb_core,
            task_id=task_id,
            large_mode=large_mode,
            model_id=saved_embedding_model_id,
        )
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error indexing documents: {error_msg}")

        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error indexing documents: {error_msg}"
        )


@router.get("/{index_name}/files")
async def get_index_files(
        index_name: str = Path(..., description="Name of the index"),
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core)
):
    """Get all files from an index, including those that are not yet stored in ES"""
    try:
        result = await ElasticSearchService.list_files(index_name, include_chunks=False, vdb_core=vdb_core)
        # Transform result to match frontend expectations
        return {
            "status": "success",
            "files": result.get("files", [])
        }
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error indexing documents: {error_msg}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error indexing documents: {error_msg}")


@router.delete("/{index_name}/documents")
def delete_documents(
        index_name: str = Path(..., description="Name of the index"),
        path_or_url: str = Query(...,
                                 description="Path or URL of documents to delete"),
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core)
):
    """Delete documents by path or URL and clean up related Redis records"""
    try:
        # First delete the documents using existing service
        result = ElasticSearchService.delete_documents(
            index_name, path_or_url, vdb_core)

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

    except Exception as e:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error delete indexing documents: {e}")


@router.get("/{index_name}/documents/{path_or_url:path}/error-info")
async def get_document_error_info(
        index_name: str = Path(..., description="Name of the index"),
        path_or_url: str = Path(...,
                                description="Path or URL of the document"),
        authorization: Optional[str] = Header(None)
):
    """Get error information for a document"""
    try:
        celery_task_files = await get_all_files_status(index_name)
        file_status = celery_task_files.get(path_or_url)

        if not file_status:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail=f"Document {path_or_url} not found in index {index_name}"
            )

        task_id = file_status.get('latest_task_id', '')
        if not task_id:
            return {
                "status": "success",
                "error_code": None,
            }

        redis_service = get_redis_service()
        raw_error = redis_service.get_error_info(task_id)
        error_code = None

        if raw_error:
            # Try to parse JSON (new format with error_code only)
            try:
                parsed = json.loads(raw_error)
                if isinstance(parsed, dict) and "error_code" in parsed:
                    error_code = parsed.get("error_code")
            except Exception:
                # Fallback: regex extraction if JSON parsing fails
                try:
                    match = re.search(
                        r'["\']error_code["\']\s*:\s*["\']([^"\']+)["\']', raw_error)
                    if match:
                        error_code = match.group(1)
                except Exception:
                    pass

        return {
            "status": "success",
            "error_code": error_code,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error getting error info for document {path_or_url}: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error getting error info: {str(e)}"
        )


# Health check
@router.get("/health")
def health_check(vdb_core: VectorDatabaseCore = Depends(get_vector_db_core)):
    """Check API and Elasticsearch health"""
    try:
        # Try to list indices as a health check
        return ElasticSearchService.health_check(vdb_core)
    except Exception as e:
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"{str(e)}")


@router.post("/{index_name}/chunks")
def get_index_chunks(
        index_name: str = Path(...,
                               description="Name of the index (or knowledge_name) to get chunks from"),
        page: int = Query(
            None, description="Page number (1-based) for pagination"),
        page_size: int = Query(
            None, description="Number of records per page for pagination"),
        path_or_url: Optional[str] = Query(
            None, description="Filter chunks by document path_or_url"),
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
        authorization: Optional[str] = Header(None)
):
    """Get chunks from the specified index, with optional pagination support"""
    try:
        _, tenant_id = get_current_user_id(authorization)
        actual_index_name = get_index_name_by_knowledge_name(
            index_name, tenant_id)

        result = ElasticSearchService.get_index_chunks(
            index_name=actual_index_name,
            page=page,
            page_size=page_size,
            path_or_url=path_or_url,
            vdb_core=vdb_core,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except ValueError as e:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        error_msg = str(e)
        logger.error(
            f"Error getting chunks for index '{index_name}': {error_msg}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error getting chunks: {error_msg}")


@router.post("/{index_name}/chunk")
def create_chunk(
        index_name: str = Path(...,
                               description="Name of the index (or knowledge_name)"),
        payload: ChunkCreateRequest = Body(..., description="Chunk data"),
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
        authorization: Optional[str] = Header(None),
):
    """Create a manual chunk."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        actual_index_name = get_index_name_by_knowledge_name(
            index_name, tenant_id)
        result = ElasticSearchService.create_chunk(
            index_name=actual_index_name,
            chunk_request=payload,
            vdb_core=vdb_core,
            user_id=user_id,
            tenant_id=tenant_id,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except ValueError as e:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(e)
        )
    except Exception as exc:
        logger.error(
            "Error creating chunk for index %s: %s", index_name, exc, exc_info=True
        )
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(exc)
        )


@router.put("/{index_name}/chunk/{chunk_id}")
def update_chunk(
        index_name: str = Path(...,
                               description="Name of the index (or knowledge_name)"),
        chunk_id: str = Path(..., description="Chunk identifier"),
        payload: ChunkUpdateRequest = Body(...,
                                           description="Chunk update payload"),
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
        authorization: Optional[str] = Header(None),
):
    """Update an existing chunk."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        actual_index_name = get_index_name_by_knowledge_name(
            index_name, tenant_id)
        result = ElasticSearchService.update_chunk(
            index_name=actual_index_name,
            chunk_id=chunk_id,
            chunk_request=payload,
            vdb_core=vdb_core,
            user_id=user_id,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except ValueError as e:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(e)
        )
    except Exception as exc:
        logger.error(
            "Error updating chunk %s for index %s: %s",
            chunk_id,
            index_name,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(exc)
        )


@router.delete("/{index_name}/chunk/{chunk_id}")
def delete_chunk(
        index_name: str = Path(...,
                               description="Name of the index (or knowledge_name)"),
        chunk_id: str = Path(..., description="Chunk identifier"),
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
        authorization: Optional[str] = Header(None),
):
    """Delete a chunk."""
    try:
        _, tenant_id = get_current_user_id(authorization)
        actual_index_name = get_index_name_by_knowledge_name(
            index_name, tenant_id)
        result = ElasticSearchService.delete_chunk(
            index_name=actual_index_name,
            chunk_id=chunk_id,
            vdb_core=vdb_core,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except ValueError as e:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(e)
        )
    except Exception as exc:
        logger.error(
            "Error deleting chunk %s for index %s: %s",
            chunk_id,
            index_name,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(exc)
        )


@router.post("/search/hybrid")
async def hybrid_search(
        payload: HybridSearchRequest,
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
        authorization: Optional[str] = Header(None),
):
    """Run a hybrid (accurate + semantic) search across indices."""
    try:
        _, tenant_id = get_current_user_id(authorization)
        result = ElasticSearchService.search_hybrid(
            index_names=payload.index_names,
            query=payload.query,
            tenant_id=tenant_id,
            top_k=payload.top_k,
            weight_accurate=payload.weight_accurate,
            vdb_core=vdb_core,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except KnowledgeBaseNeedsModelConfigError as exc:
        # Return a specific error that frontend can detect to show the config dialog
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail={
                "error_type": "KNOWLEDGE_BASE_NEEDS_MODEL_CONFIG",
                "index_name": exc.index_name,
                "message": exc.message,
                "suggestion": "Please select an embedding model for this knowledge base before searching."
            }
        )
    except ValueError as exc:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        logger.error(f"Hybrid search failed: {exc}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error executing hybrid search: {str(exc)}",
        )
